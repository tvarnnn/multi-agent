import pytest

from agent_platform.mcp.schemas import MCPServerConfig
from agent_platform.security.enums import SessionMode
from agent_platform.settings.builder import build_mcp_server_configs, build_platform_config_kwargs
from agent_platform.settings.loader import SettingsValidationError
from agent_platform.settings.schema import AgentBehaviorSettings, McpServerSettingsEntry, WorkspaceSettings


# ------------------------------------------------- build_platform_config_kwargs

def test_no_agent_behavior_settings_produces_empty_kwargs():
    kwargs = build_platform_config_kwargs(WorkspaceSettings())
    assert kwargs == {}


def test_explicit_fields_are_included():
    settings = WorkspaceSettings(agent_behavior=AgentBehaviorSettings(
        max_fix_iterations=5, context_compaction_threshold_percent=70))
    kwargs = build_platform_config_kwargs(settings)
    assert kwargs == {"max_fix_iterations": 5, "context_compaction_threshold_percent": 70}


def test_session_mode_string_converted_to_enum():
    settings = WorkspaceSettings(agent_behavior=AgentBehaviorSettings(session_mode="MANUAL"))
    kwargs = build_platform_config_kwargs(settings)
    assert kwargs["session_mode"] == SessionMode.MANUAL


def test_invalid_session_mode_string_raises():
    settings = WorkspaceSettings(agent_behavior=AgentBehaviorSettings(session_mode="NOT_A_REAL_MODE"))
    with pytest.raises(SettingsValidationError):
        build_platform_config_kwargs(settings)


def test_kwargs_feed_platform_config_load_successfully(tmp_path):
    from agent_platform.config import PlatformConfig
    settings = WorkspaceSettings(agent_behavior=AgentBehaviorSettings(max_fix_iterations=7))
    kwargs = build_platform_config_kwargs(settings)
    config = PlatformConfig.load(str(tmp_path), **kwargs)
    assert config.max_fix_iterations == 7


def test_kwargs_still_rejected_by_platform_config_loads_own_validation(tmp_path):
    """builder.py does not duplicate PlatformConfig's validation - an
    out-of-range value it passes through is still caught by
    PlatformConfig.load() itself."""
    from agent_platform.config import ConfigurationError, PlatformConfig
    settings = WorkspaceSettings(agent_behavior=AgentBehaviorSettings(max_fix_iterations=-1))
    kwargs = build_platform_config_kwargs(settings)
    with pytest.raises(ConfigurationError):
        PlatformConfig.load(str(tmp_path), **kwargs)


# ----------------------------------------------------- build_mcp_server_configs

def test_empty_mcp_settings_produces_empty_tuple():
    assert build_mcp_server_configs(WorkspaceSettings()) == ()


def test_enabled_server_is_included(monkeypatch):
    monkeypatch.setenv("AGENT_PLATFORM_MCP_CREDENTIAL_GITHUB", "resolved-secret")
    settings = WorkspaceSettings(mcp={"github": McpServerSettingsEntry(
        server_id="github", enabled=True, transport="stdio",
        capabilities=("repository.read",), credential_reference="github")})
    configs = build_mcp_server_configs(settings)
    assert len(configs) == 1
    assert isinstance(configs[0], MCPServerConfig)
    assert configs[0].server_id == "github"
    assert configs[0].capabilities == ("repository.read",)
    assert configs[0].credential == "resolved-secret"


def test_disabled_server_is_excluded_entirely():
    settings = WorkspaceSettings(mcp={"github": McpServerSettingsEntry(server_id="github", enabled=False)})
    assert build_mcp_server_configs(settings) == ()


def test_missing_credential_env_var_yields_none_credential(monkeypatch):
    monkeypatch.delenv("AGENT_PLATFORM_MCP_CREDENTIAL_GITHUB", raising=False)
    settings = WorkspaceSettings(mcp={"github": McpServerSettingsEntry(
        server_id="github", credential_reference="github")})
    configs = build_mcp_server_configs(settings)
    assert configs[0].credential is None


def test_no_credential_reference_yields_none_credential():
    settings = WorkspaceSettings(mcp={"github": McpServerSettingsEntry(server_id="github")})
    configs = build_mcp_server_configs(settings)
    assert configs[0].credential is None
