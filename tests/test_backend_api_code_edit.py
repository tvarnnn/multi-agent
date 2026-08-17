"""Phase 12's one identified backend contract gap (design doc §12-14):
CODE/EDIT sessions had no HTTP route at all. The smallest additive fix -
two more branches on the existing POST /sessions/{id}/messages handler,
mirroring the CHAT/PLAN/REVIEW branches already there - plus a fourth
explicit-field OrchestratorResult serializer. Zero changes to
Orchestrator/ToolGateway/PermissionEvaluator/the state machine.
"""
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


def _coder_completed(**overrides):
    d = {"status": "completed", "spec_version_label": "spec-1-v1", "summary": "did the thing",
         "file_writes": [{"path": "main.py", "content": "print('hi')\n"}]}
    d.update(overrides)
    return d


def _reviewer_approve(**overrides):
    d = {"decision": "APPROVE", "spec_version_label": "spec-1-v1", "requirements_met": True,
         "security_ok": True, "validation_ok": True, "issues": []}
    d.update(overrides)
    return d


def _planner_spec(**overrides):
    d = {"kind": "spec", "goals": ["g1"], "constraints": [], "acceptance_criteria": ["file:main.py"]}
    d.update(overrides)
    return d


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    (root / "MyProj").mkdir()
    return root


def _services(workspace, model=None):
    project_root = (workspace / "MyProj").resolve()
    sandbox = FilesystemSandbox(workspace)
    evaluator = PermissionEvaluator(sandbox)
    registry = build_default_registry()
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


# --------------------------------------------------------- session creation

def test_code_session_requires_spec_id(workspace):
    client = _client(workspace)
    resp = client.post("/sessions", json={"operating_mode": "CODE"}, headers=AUTH)
    assert resp.status_code == 400


def test_edit_session_requires_spec_id(workspace):
    client = _client(workspace)
    resp = client.post("/sessions", json={"operating_mode": "EDIT"}, headers=AUTH)
    assert resp.status_code == 400


def test_code_session_with_spec_id_creates_successfully(workspace):
    client = _client(workspace)
    resp = client.post("/sessions", json={"operating_mode": "CODE", "spec_id": "spec-1"}, headers=AUTH)
    assert resp.status_code == 200


# ---------------------------------------------------------------- CODE mode

def test_code_mode_message_runs_the_full_orchestrator_and_reaches_complete(workspace):
    model = FakeModelProvider(
        planner_responses=[_planner_spec()], coder_responses=[_coder_completed()],
        reviewer_responses=[_reviewer_approve()],
    )
    client = _client(workspace, model=model)
    session_id = client.post("/sessions", json={"operating_mode": "CODE", "spec_id": "spec-1"},
                              headers=AUTH).json()["session_id"]
    resp = client.post(f"/sessions/{session_id}/messages",
                        json={"message": "write a hello world script"}, headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["final_state"] == "COMPLETE"
    assert body["spec_id"] == "spec-1"
    assert body["summary"] == "did the thing"


def test_code_mode_persists_spec_version_for_rehydration(workspace):
    model = FakeModelProvider(
        planner_responses=[_planner_spec()], coder_responses=[_coder_completed()],
        reviewer_responses=[_reviewer_approve()],
    )
    client = _client(workspace, model=model)
    session_id = client.post("/sessions", json={"operating_mode": "CODE", "spec_id": "spec-1"},
                              headers=AUTH).json()["session_id"]
    client.post(f"/sessions/{session_id}/messages", json={"message": "write a hello world script"},
                headers=AUTH)
    detail = client.get(f"/sessions/{session_id}", headers=AUTH).json()
    assert detail["active_spec_version"] == 1


def test_code_mode_completion_forces_a_checkpoint(workspace):
    model = FakeModelProvider(
        planner_responses=[_planner_spec()], coder_responses=[_coder_completed()],
        reviewer_responses=[_reviewer_approve()],
    )
    client = _client(workspace, model=model)
    session_id = client.post("/sessions", json={"operating_mode": "CODE", "spec_id": "spec-1"},
                              headers=AUTH).json()["session_id"]
    client.post(f"/sessions/{session_id}/messages", json={"message": "write a hello world script"},
                headers=AUTH)
    checkpoints = client.get(f"/sessions/{session_id}/checkpoints", headers=AUTH).json()["checkpoints"]
    assert any(c["reason"] == "terminal_state" for c in checkpoints)


def test_code_mode_records_conversation_history(workspace):
    model = FakeModelProvider(
        planner_responses=[_planner_spec()], coder_responses=[_coder_completed()],
        reviewer_responses=[_reviewer_approve()],
    )
    client = _client(workspace, model=model)
    session_id = client.post("/sessions", json={"operating_mode": "CODE", "spec_id": "spec-1"},
                              headers=AUTH).json()["session_id"]
    client.post(f"/sessions/{session_id}/messages", json={"message": "write a hello world script"},
                headers=AUTH)
    history = client.get(f"/sessions/{session_id}/history", headers=AUTH).json()["messages"]
    assert any(m["content"] == "write a hello world script" for m in history)
    assert any(m["content"] == "did the thing" for m in history)


# ---------------------------------------------------------------- EDIT mode

def test_edit_mode_message_runs_amend_requirements(workspace):
    model = FakeModelProvider(
        planner_responses=[_planner_spec()], coder_responses=[_coder_completed()],
        reviewer_responses=[_reviewer_approve()],
    )
    client = _client(workspace, model=model)
    session_id = client.post("/sessions", json={"operating_mode": "EDIT", "spec_id": "spec-1"},
                              headers=AUTH).json()["session_id"]
    resp = client.post(f"/sessions/{session_id}/messages",
                        json={"message": "add error handling"}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["final_state"] == "COMPLETE"


# ---------------------------------------------------- unchanged/regression

def test_chat_mode_still_unaffected(workspace):
    model = FakeModelProvider(chat_responses=[{"message": "hi there"}])
    client = _client(workspace, model=model)
    session_id = client.post("/sessions", json={"operating_mode": "CHAT"}, headers=AUTH).json()["session_id"]
    resp = client.post(f"/sessions/{session_id}/messages", json={"message": "hello"}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == {"session_id": session_id, "message": "hi there"}


def test_plan_mode_still_does_not_require_spec_id_check_change(workspace):
    client = _client(workspace)
    resp = client.post("/sessions", json={"operating_mode": "PLAN"}, headers=AUTH)
    assert resp.status_code == 400
