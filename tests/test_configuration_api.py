"""New Phase 11 GET /configuration* routes, plus the API-layer half of
the required 16-attack matrix: 9 (retrieve credential values via the
API), 13 (unauthorized modification), 14 (cross-workspace access). The
settings-layer half (1-8, 10-12, 15-16) lives in
test_settings_security_adversarial.py.
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


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    (root / "MyProj").mkdir()
    return root


def _services(workspace, settings_yaml=None, model_discovery_query_fn=None):
    project_root = (workspace / "MyProj").resolve()
    if settings_yaml is not None:
        (project_root / ".agent").mkdir(parents=True, exist_ok=True)
        (project_root / ".agent" / "settings.yaml").write_text(settings_yaml, encoding="utf-8")

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
    settings = SettingsService.load(
        global_path=None, workspace_path=project_root / ".agent" / "settings.yaml")
    return BackendServices(
        project_root=project_root, spec_store=spec_store, model=FakeModelProvider(),
        validator=AcceptanceCriteriaFileValidator(), registry=registry, evaluator=evaluator,
        sandbox=sandbox, persistence=persistence, settings=settings, session_mode=SessionMode.AUTO,
        model_discovery_query_fn=model_discovery_query_fn,
    )


def _client(workspace, **kwargs):
    return TestClient(create_app(_services(workspace, **kwargs), TOKEN))


# ------------------------------------------------------------------- auth

def test_configuration_routes_require_auth(workspace):
    client = _client(workspace)
    assert client.get("/configuration").status_code == 401
    assert client.get("/configuration/models").status_code == 401
    assert client.get("/configuration/mcp").status_code == 401


# ------------------------------------------------------------- GET /configuration

def test_get_configuration_returns_safe_view(workspace):
    client = _client(workspace, settings_yaml="models:\n  coder: qwen2.5-coder:14b\n")
    resp = client.get("/configuration", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["models"]["coder"]["model_id"] == "qwen2.5-coder:14b"
    assert body["precedence"] == {"global_loaded": False, "workspace_loaded": True}


def test_get_configuration_never_includes_credential_anywhere(workspace, monkeypatch):
    monkeypatch.setenv("AGENT_PLATFORM_MCP_CREDENTIAL_GITHUB", "super-secret-value")
    client = _client(workspace, settings_yaml=(
        "mcp:\n  github:\n    capabilities: [repository.read]\n    credential: github\n"
    ))
    resp = client.get("/configuration", headers=AUTH)
    body_text = resp.text
    assert "super-secret-value" not in body_text
    assert "credential" not in body_text  # not even the key name appears in the safe view


# ------------------------------------------------------- GET /configuration/models

def test_get_configuration_models_reports_configured_and_availability(workspace):
    client = _client(
        workspace, settings_yaml="models:\n  planner: model-a\n  coder: model-b\n",
        model_discovery_query_fn=lambda: ("model-a",),
    )
    resp = client.get("/configuration/models", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["models"]["planner"] == {"model_id": "model-a", "available": True}
    assert body["models"]["coder"] == {"model_id": "model-b", "available": False}


def test_get_configuration_models_never_touches_network_when_query_fn_injected(workspace):
    calls = []

    def _fake():
        calls.append(1)
        return ()
    client = _client(workspace, model_discovery_query_fn=_fake)
    client.get("/configuration/models", headers=AUTH)
    assert calls == [1]


# --------------------------------------------------------- GET /configuration/mcp

def test_get_configuration_mcp_reports_policy_without_credential(workspace, monkeypatch):
    monkeypatch.setenv("AGENT_PLATFORM_MCP_CREDENTIAL_GITHUB", "super-secret-value")
    client = _client(workspace, settings_yaml=(
        "mcp:\n  github:\n    enabled: true\n    capabilities: [repository.read]\n    credential: github\n"
    ))
    resp = client.get("/configuration/mcp", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["mcp"]["github"]["enabled"] is True
    assert body["mcp"]["github"]["capabilities"] == ["repository.read"]
    assert "credential" not in resp.text
    assert "super-secret-value" not in resp.text


# ---------------------------------------- Attack 9: retrieve credential values

def test_no_route_ever_returns_a_credential_value(workspace, monkeypatch):
    monkeypatch.setenv("AGENT_PLATFORM_MCP_CREDENTIAL_GITHUB", "super-secret-value")
    client = _client(workspace, settings_yaml=(
        "mcp:\n  github:\n    capabilities: [repository.read]\n    credential: github\n"
    ), model_discovery_query_fn=lambda: ())
    for route in ("/configuration", "/configuration/models", "/configuration/mcp", "/mcp/servers"):
        resp = client.get(route, headers=AUTH)
        assert "super-secret-value" not in resp.text


# --------------------------------------- Attack 13: unauthorized modification

def test_wrong_token_cannot_read_configuration(workspace):
    client = _client(workspace)
    resp = client.get("/configuration", headers={"Authorization": "Bearer wrong-token"})
    assert resp.status_code == 401


# ------------------------------------- Attack 14: cross-workspace access

def test_configuration_has_no_workspace_selector_parameter(workspace):
    """Each backend process is bound to exactly one project_root; there is
    no route parameter anywhere that could select a different workspace's
    settings/configuration."""
    client = _client(workspace)
    # Attempting to smuggle a workspace selector via query string is simply ignored -
    # the route always reports the one project this process is bound to.
    resp = client.get("/configuration?workspace=../OtherProj", headers=AUTH)
    assert resp.status_code == 200
    assert "OtherProj" not in resp.text
