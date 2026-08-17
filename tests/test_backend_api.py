import pytest
from fastapi.testclient import TestClient

from agent_platform.backend_api import BackendServices, create_app
from agent_platform.events import EventLog
from agent_platform.mcp.client import MCPClient
from agent_platform.mcp.mock_transport import MockMCPTransport
from agent_platform.mcp.preferences import MCPUserPreferences
from agent_platform.mcp.schemas import MCPServerConfig
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


def _services(workspace, model=None, mcp_servers=(), mcp_clients=None, mcp_preferences=None):
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
        project_root=project_root, spec_store=spec_store,
        model=model or FakeModelProvider(), validator=AcceptanceCriteriaFileValidator(),
        registry=registry, evaluator=evaluator, sandbox=sandbox, persistence=persistence,
        settings=settings, session_mode=SessionMode.AUTO, mcp_servers=mcp_servers,
        mcp_clients=mcp_clients or {}, mcp_preferences=mcp_preferences or MCPUserPreferences(),
    )


def _client(workspace, **kwargs):
    services = _services(workspace, **kwargs)
    app = create_app(services, TOKEN)
    return TestClient(app)


# ----------------------------------------------------------------- auth

def test_missing_token_is_401_before_any_session_created(workspace):
    client = _client(workspace)
    resp = client.post("/sessions", json={"operating_mode": "CHAT"})
    assert resp.status_code == 401
    body = resp.json()
    assert "error" in body["detail"] or "error" in body
    resp2 = client.get("/sessions/does-not-exist/state")
    assert resp2.status_code == 401


def test_wrong_token_is_401(workspace):
    client = _client(workspace)
    resp = client.post("/sessions", json={"operating_mode": "CHAT"},
                        headers={"Authorization": "Bearer wrong-token"})
    assert resp.status_code == 401


def test_unknown_route_with_bad_token_is_401_not_404(workspace):
    # Auth is enforced by middleware before Starlette's routing resolves a
    # handler, so an unauthenticated caller can't distinguish real routes
    # from nonexistent ones by probing status codes.
    client = _client(workspace)
    resp = client.get("/totally/made/up/route", headers={"Authorization": "Bearer wrong-token"})
    assert resp.status_code == 401
    resp2 = client.get("/totally/made/up/route")
    assert resp2.status_code == 401


def test_unknown_route_with_correct_token_is_404(workspace):
    client = _client(workspace)
    resp = client.get("/totally/made/up/route", headers=AUTH)
    assert resp.status_code == 404


def test_correct_token_is_authorized(workspace):
    client = _client(workspace)
    resp = client.post("/sessions", json={"operating_mode": "CHAT"}, headers=AUTH)
    assert resp.status_code == 200
    assert "session_id" in resp.json()


# -------------------------------------------------------------- sessions

def test_create_session_and_send_chat_message(workspace):
    model = FakeModelProvider(chat_responses=[{"message": "hi there"}])
    client = _client(workspace, model=model)
    session_id = client.post("/sessions", json={"operating_mode": "CHAT"}, headers=AUTH).json()["session_id"]
    resp = client.post(f"/sessions/{session_id}/messages", json={"message": "hello"}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["message"] == "hi there"


def test_unknown_session_is_404(workspace):
    client = _client(workspace)
    resp = client.get("/sessions/nope/state", headers=AUTH)
    assert resp.status_code == 404


# --------------------------------------------------------- plan lifecycle

def test_plan_session_full_lifecycle_via_http(workspace):
    model = FakeModelProvider(
        plan_mode_responses=[_plan_dict()],
        review_plan_responses=[_review_dict()],
    )
    client = _client(workspace, model=model)
    session_id = client.post("/sessions", json={"operating_mode": "PLAN", "spec_id": "widget"},
                              headers=AUTH).json()["session_id"]
    draft_resp = client.post(f"/sessions/{session_id}/messages", json={"message": "build a widget"}, headers=AUTH)
    assert draft_resp.status_code == 200
    draft = draft_resp.json()
    assert draft["status"] == "DRAFT"

    plan_resp = client.get(f"/sessions/{session_id}/plan", headers=AUTH)
    assert plan_resp.status_code == 200
    assert plan_resp.json()["status"] == "DRAFT"

    approve_resp = client.post(f"/sessions/{session_id}/plan/approve", headers=AUTH)
    assert approve_resp.status_code == 200
    assert approve_resp.json()["spec_version_label"] == "widget-v1"


def test_plan_reject_via_http(workspace):
    model = FakeModelProvider(
        plan_mode_responses=[_plan_dict()],
        review_plan_responses=[_review_dict()],
    )
    client = _client(workspace, model=model)
    session_id = client.post("/sessions", json={"operating_mode": "PLAN", "spec_id": "widget"},
                              headers=AUTH).json()["session_id"]
    client.post(f"/sessions/{session_id}/messages", json={"message": "build a widget"}, headers=AUTH)
    resp = client.post(f"/sessions/{session_id}/plan/reject", json={"reason": "nope"}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["status"] == "REJECTED"


def test_plan_revise_via_http(workspace):
    model = FakeModelProvider(
        plan_mode_responses=[_plan_dict(), _plan_dict(objective="v2")],
        review_plan_responses=[_review_dict(), _review_dict()],
    )
    client = _client(workspace, model=model)
    session_id = client.post("/sessions", json={"operating_mode": "PLAN", "spec_id": "widget"},
                              headers=AUTH).json()["session_id"]
    client.post(f"/sessions/{session_id}/messages", json={"message": "build a widget"}, headers=AUTH)
    resp = client.post(f"/sessions/{session_id}/plan/revise", json={"revision_request": "add auth"}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["status"] == "REVISED"


def test_approve_without_active_draft_is_409(workspace):
    client = _client(workspace)
    session_id = client.post("/sessions", json={"operating_mode": "PLAN", "spec_id": "widget"},
                              headers=AUTH).json()["session_id"]
    resp = client.post(f"/sessions/{session_id}/plan/approve", headers=AUTH)
    assert resp.status_code == 409


def test_invalid_spec_id_is_400_not_normalized(workspace):
    client = _client(workspace)
    resp = client.post("/sessions", json={"operating_mode": "PLAN", "spec_id": "../escape"}, headers=AUTH)
    assert resp.status_code == 400


# ------------------------------------------------------------ wrong mode

def test_plan_route_on_chat_session_is_409(workspace):
    model = FakeModelProvider(chat_responses=[{"message": "hi"}])
    client = _client(workspace, model=model)
    session_id = client.post("/sessions", json={"operating_mode": "CHAT"}, headers=AUTH).json()["session_id"]
    resp = client.post(f"/sessions/{session_id}/plan/approve", headers=AUTH)
    assert resp.status_code == 409


# Phase 12: CODE/EDIT sessions now DO support /messages (design doc §12-14) -
# this used to assert a 409 here, documenting a gap rather than a deliberate
# boundary. The current, correct behavior for CODE/EDIT is covered in
# tests/test_backend_api_code_edit.py, the dedicated file for that contract.


# ---------------------------------------------------------------- events

def test_events_stream_excludes_internal_events(workspace):
    model = FakeModelProvider(chat_responses=[{"message": "hi there"}])
    client = _client(workspace, model=model)
    session_id = client.post("/sessions", json={"operating_mode": "CHAT"}, headers=AUTH).json()["session_id"]
    client.post(f"/sessions/{session_id}/messages", json={"message": "hello"}, headers=AUTH)
    resp = client.get(f"/sessions/{session_id}/events", headers=AUTH)
    assert resp.status_code == 200
    body = resp.text
    assert "STATE_TRANSITION" not in body
    assert "TOOL_INVOKED" not in body


def test_events_are_isolated_per_session(workspace):
    model = FakeModelProvider(chat_responses=[{"message": "reply-a"}, {"message": "reply-b"}])
    client = _client(workspace, model=model)
    session_a = client.post("/sessions", json={"operating_mode": "CHAT"}, headers=AUTH).json()["session_id"]
    session_b = client.post("/sessions", json={"operating_mode": "CHAT"}, headers=AUTH).json()["session_id"]
    client.post(f"/sessions/{session_a}/messages", json={"message": "hi"}, headers=AUTH)
    events_b = client.get(f"/sessions/{session_b}/events", headers=AUTH).text
    assert "reply-a" not in events_b


# ------------------------------------------------------------- mcp servers

def _mcp_fixture():
    config = MCPServerConfig(server_id="github", transport="mock",
                              capabilities=("repository_read",), credential="super-secret-value")
    client = MCPClient(MockMCPTransport({"repository_read": [{"ok": True}]}))
    return config, client


def test_mcp_servers_route_never_includes_credential(workspace):
    config, client = _mcp_fixture()
    api_client = _client(workspace, mcp_servers=(config,), mcp_clients={"github": client})
    resp = api_client.get("/mcp/servers", headers=AUTH)
    assert resp.status_code == 200
    body = resp.text
    assert "super-secret-value" not in body
    assert resp.json()["servers"][0]["server_id"] == "github"


def test_mcp_preferences_route_is_narrowing_only(workspace):
    config, client = _mcp_fixture()
    prefs = MCPUserPreferences()
    api_client = _client(workspace, mcp_servers=(config,), mcp_clients={"github": client}, mcp_preferences=prefs)
    # Attempt to "enable" a capability absent from trusted config/discovery.
    resp = api_client.put("/mcp/servers/github/preferences", headers=AUTH,
                           json={"capability_overrides": {"delete_repo": True}})
    assert resp.status_code == 200
    assert "delete_repo" not in resp.json()["capabilities"]
    assert resp.json()["capabilities"] == ["repository_read"]

    disable_resp = api_client.put("/mcp/servers/github/preferences", headers=AUTH, json={"enabled": False})
    assert disable_resp.status_code == 200
    assert disable_resp.json()["capabilities"] == []
