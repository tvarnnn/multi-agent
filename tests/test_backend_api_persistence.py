import pytest
from fastapi.testclient import TestClient

from agent_platform.backend_api import BackendServices, create_app
from agent_platform.events import EventLog
from agent_platform.orchestrator.fake_model import FakeModelProvider
from agent_platform.orchestrator.validation import AcceptanceCriteriaFileValidator
from agent_platform.persistence.db import ensure_schema, resolve_agent_paths
from agent_platform.persistence.service import SessionPersistenceService
from agent_platform.security.enums import SessionMode
from agent_platform.security.permission import PermissionEvaluator
from agent_platform.security.sandbox import FilesystemSandbox
from agent_platform.settings.service import SettingsService
from agent_platform.spec.versioning import SpecStore
from agent_platform.tools.gateway import ToolGateway
from agent_platform.tools.registry import build_default_registry

TOKEN = "test-token-abc123"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _plan_dict(**overrides):
    d = {
        "kind": "plan", "objective": "Build the widget", "requirements": ["req1"],
        "existing_context": [], "proposed_architecture": "single module",
        "files_to_create": ["widget.py"], "files_to_modify": [], "dependencies": [],
        "implementation_steps": ["step1"], "validation_strategy": ["test1"],
        "risks": [], "unknowns": [], "acceptance_criteria": ["file:widget.py"],
    }
    d.update(overrides)
    return d


def _review_dict():
    return {"comments": [], "missing_requirements": [], "security_concerns": [], "unnecessary_complexity": []}


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    (root / "MyProj").mkdir()
    return root


def _services(workspace, model=None):
    sandbox = FilesystemSandbox(workspace)
    evaluator = PermissionEvaluator(sandbox)
    registry = build_default_registry()
    project_root = (workspace / "MyProj").resolve()
    spec_store = SpecStore()
    paths = resolve_agent_paths(sandbox, project_root, ".agent")
    ensure_schema(paths.db_path, project_root)
    persistence = SessionPersistenceService(
        db_path=paths.db_path, sandbox=sandbox, project_root=project_root,
        checkpoints_relative_dir=".agent/context/checkpoints",
        gateway=ToolGateway(registry, evaluator, EventLog()), spec_store=spec_store,
    )
    settings = SettingsService.load(global_path=None, workspace_path=None)
    return BackendServices(
        project_root=project_root, spec_store=spec_store, model=model or FakeModelProvider(),
        validator=AcceptanceCriteriaFileValidator(), registry=registry, evaluator=evaluator,
        sandbox=sandbox, persistence=persistence, settings=settings, session_mode=SessionMode.AUTO,
    )


def _client(workspace, **kwargs):
    return TestClient(create_app(_services(workspace, **kwargs), TOKEN))


# ------------------------------------------------------------------- auth

def test_list_sessions_requires_auth(workspace):
    client = _client(workspace)
    assert client.get("/sessions").status_code == 401


def test_resume_requires_auth(workspace):
    client = _client(workspace)
    assert client.post("/sessions/whatever/resume").status_code == 401


# --------------------------------------------------------- session_id format

@pytest.mark.parametrize("bad_id", ["../../etc/passwd", "a%2Fb", "x" * 200, "a b", "id;drop table"])
def test_malformed_session_id_is_400_on_new_routes(workspace, bad_id):
    client = _client(workspace)
    assert client.get(f"/sessions/{bad_id}", headers=AUTH).status_code in (400, 404)
    assert client.get(f"/sessions/{bad_id}/history", headers=AUTH).status_code in (400, 404)
    assert client.post(f"/sessions/{bad_id}/resume", headers=AUTH).status_code in (400, 404)


def test_unknown_but_well_formed_session_id_is_404(workspace):
    client = _client(workspace)
    resp = client.get("/sessions/abcDEF123-_45", headers=AUTH)
    assert resp.status_code == 404
    assert "unknown session" in resp.json()["detail"]["error"]


# ------------------------------------------------------------- list/detail

def test_list_and_get_session(workspace):
    client = _client(workspace)
    created = client.post("/sessions", json={"operating_mode": "CHAT"}, headers=AUTH).json()
    session_id = created["session_id"]

    listed = client.get("/sessions", headers=AUTH).json()["sessions"]
    assert any(s["session_id"] == session_id for s in listed)

    detail = client.get(f"/sessions/{session_id}", headers=AUTH).json()
    assert detail["operating_mode"] == "CHAT"
    assert detail["status"] == "ACTIVE"


# --------------------------------------------------------------- history

def test_history_records_chat_turn(workspace):
    model = FakeModelProvider(chat_responses=[{"message": "hi there"}])
    client = _client(workspace, model=model)
    session_id = client.post("/sessions", json={"operating_mode": "CHAT"}, headers=AUTH).json()["session_id"]
    client.post(f"/sessions/{session_id}/messages", json={"message": "hello"}, headers=AUTH)

    history = client.get(f"/sessions/{session_id}/history", headers=AUTH).json()["messages"]
    assert [m["speaker"] for m in reversed(history)] == ["user", "assistant"]
    assert history[-1]["content"] == "hello"
    assert history[0]["content"] == "hi there"


def test_history_limit_is_clamped(workspace):
    model = FakeModelProvider(chat_responses=[{"message": f"r{i}"} for i in range(5)])
    client = _client(workspace, model=model)
    session_id = client.post("/sessions", json={"operating_mode": "CHAT"}, headers=AUTH).json()["session_id"]
    for i in range(5):
        client.post(f"/sessions/{session_id}/messages", json={"message": f"m{i}"}, headers=AUTH)
    resp = client.get(f"/sessions/{session_id}/history?limit=999999", headers=AUTH)
    assert resp.status_code == 200
    assert len(resp.json()["messages"]) <= 200


# ------------------------------------------------------------------ plan flow

def test_plan_approve_persists_snapshot_decision_and_checkpoint(workspace):
    model = FakeModelProvider(
        plan_mode_responses=[_plan_dict()], review_plan_responses=[_review_dict()])
    client = _client(workspace, model=model)
    session_id = client.post("/sessions", json={"operating_mode": "PLAN", "spec_id": "spec-1"},
                              headers=AUTH).json()["session_id"]
    client.post(f"/sessions/{session_id}/messages", json={"message": "build a widget"}, headers=AUTH)
    approve = client.post(f"/sessions/{session_id}/plan/approve", headers=AUTH)
    assert approve.status_code == 200

    checkpoints = client.get(f"/sessions/{session_id}/checkpoints", headers=AUTH).json()["checkpoints"]
    assert any(c["reason"] == "plan_approved" for c in checkpoints)

    detail = client.get(f"/sessions/{session_id}", headers=AUTH).json()
    assert detail["active_spec_version"] == 1
    assert detail["active_plan_id"] is not None


# ------------------------------------------------------------------- resume

def test_resume_restores_authoritative_operating_mode_from_db_not_checkpoint(workspace):
    model = FakeModelProvider(chat_responses=[{"message": "hi there"}])
    client = _client(workspace, model=model)
    session_id = client.post("/sessions", json={"operating_mode": "CHAT"}, headers=AUTH).json()["session_id"]
    client.post(f"/sessions/{session_id}/messages", json={"message": "hello"}, headers=AUTH)

    resumed = client.post(f"/sessions/{session_id}/resume", headers=AUTH)
    assert resumed.status_code == 200
    body = resumed.json()
    assert body["operating_mode"] == "CHAT"
    assert body["session_mode"] == "AUTO"


def test_resumed_session_can_continue(workspace):
    model = FakeModelProvider(chat_responses=[{"message": "first reply"}, {"message": "second reply"}])
    client = _client(workspace, model=model)
    session_id = client.post("/sessions", json={"operating_mode": "CHAT"}, headers=AUTH).json()["session_id"]
    client.post(f"/sessions/{session_id}/messages", json={"message": "hello"}, headers=AUTH)
    client.post(f"/sessions/{session_id}/resume", headers=AUTH)
    resp = client.post(f"/sessions/{session_id}/messages", json={"message": "hello again"}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["message"] == "second reply"


def test_resume_restores_plan_draft_for_get_plan(workspace):
    model = FakeModelProvider(plan_mode_responses=[_plan_dict()], review_plan_responses=[_review_dict()])
    client = _client(workspace, model=model)
    session_id = client.post("/sessions", json={"operating_mode": "PLAN", "spec_id": "spec-1"},
                              headers=AUTH).json()["session_id"]
    client.post(f"/sessions/{session_id}/messages", json={"message": "build a widget"}, headers=AUTH)

    client.post(f"/sessions/{session_id}/resume", headers=AUTH)
    plan = client.get(f"/sessions/{session_id}/plan", headers=AUTH)
    assert plan.status_code == 200
    assert plan.json()["status"] == "DRAFT"


def test_resume_of_unknown_session_is_404(workspace):
    client = _client(workspace)
    resp = client.post("/sessions/abcDEF123-_45/resume", headers=AUTH)
    assert resp.status_code == 404


# ------------------------------------------------------------------ archive

def test_archive_marks_status_and_removes_live_session(workspace):
    client = _client(workspace)
    session_id = client.post("/sessions", json={"operating_mode": "CHAT"}, headers=AUTH).json()["session_id"]
    archive = client.post(f"/sessions/{session_id}/archive", headers=AUTH)
    assert archive.status_code == 200
    assert archive.json()["status"] == "ARCHIVED"

    detail = client.get(f"/sessions/{session_id}", headers=AUTH).json()
    assert detail["status"] == "ARCHIVED"

    # No longer live - /state (which requires an in-memory Orchestrator) is gone.
    assert client.get(f"/sessions/{session_id}/state", headers=AUTH).status_code == 404


def test_archived_session_has_at_least_one_checkpoint(workspace):
    client = _client(workspace)
    session_id = client.post("/sessions", json={"operating_mode": "CHAT"}, headers=AUTH).json()["session_id"]
    client.post(f"/sessions/{session_id}/archive", headers=AUTH)
    checkpoints = client.get(f"/sessions/{session_id}/checkpoints", headers=AUTH).json()["checkpoints"]
    assert len(checkpoints) >= 1
    assert checkpoints[0]["reason"] == "archive"
