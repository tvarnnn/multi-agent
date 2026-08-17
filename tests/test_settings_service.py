import pytest

from agent_platform.security.enums import SessionMode
from agent_platform.settings.service import SettingsService


@pytest.fixture
def global_path(tmp_path):
    path = tmp_path / "global-settings.yaml"
    path.write_text(
        "models:\n  planner: global-planner\n  coder: global-coder\n"
        "mcp:\n  docs:\n    capabilities: [search]\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def workspace_path(tmp_path):
    path = tmp_path / "workspace-settings.yaml"
    path.write_text("models:\n  coder: workspace-coder\n", encoding="utf-8")
    return path


def test_loads_and_merges_global_and_workspace(global_path, workspace_path):
    service = SettingsService.load(global_path=global_path, workspace_path=workspace_path)
    assert service.model_settings.coder == "workspace-coder"  # workspace wins
    assert service.mcp_server_configs[0].server_id == "docs"  # global's mcp section, unset in workspace


def test_missing_files_produce_all_defaults(tmp_path):
    service = SettingsService.load(global_path=tmp_path / "no.yaml", workspace_path=tmp_path / "also-no.yaml")
    assert service.model_settings.planner is None
    assert service.mcp_server_configs == ()
    assert service.platform_config_kwargs == {}


def test_platform_config_kwargs_available(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text("agent_behavior:\n  max_fix_iterations: 9\n  session_mode: MANUAL\n", encoding="utf-8")
    service = SettingsService.load(global_path=None, workspace_path=path)
    assert service.platform_config_kwargs["max_fix_iterations"] == 9
    assert service.platform_config_kwargs["session_mode"] == SessionMode.MANUAL


def test_safe_view_never_includes_credential(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_PLATFORM_MCP_CREDENTIAL_GITHUB", "super-secret-value")
    path = tmp_path / "settings.yaml"
    path.write_text(
        "mcp:\n  github:\n    capabilities: [repository.read]\n    credential: github\n",
        encoding="utf-8",
    )
    service = SettingsService.load(global_path=None, workspace_path=path)
    view = service.safe_view()
    assert "super-secret-value" not in str(view)
    assert "credential" not in str(view["mcp"]["github"])


def test_safe_view_reports_model_ids():
    service = SettingsService.load(global_path=None, workspace_path=None)
    view = service.safe_view()
    assert "models" in view
    assert set(view["models"].keys()) == {"planner", "coder", "reviewer"}


def test_safe_view_reports_precedence_info(global_path, workspace_path, tmp_path):
    service = SettingsService.load(global_path=global_path, workspace_path=workspace_path)
    view = service.safe_view()
    assert view["precedence"] == {"global_loaded": True, "workspace_loaded": True}

    service2 = SettingsService.load(global_path=tmp_path / "nope.yaml", workspace_path=workspace_path)
    assert service2.safe_view()["precedence"] == {"global_loaded": False, "workspace_loaded": True}
