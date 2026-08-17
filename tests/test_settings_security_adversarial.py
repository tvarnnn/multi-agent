"""The settings-layer half of Part 11's required 16-attack matrix (items
1-8, 10-12, 15-16). The API-layer half (9: retrieve credentials via API,
13: unauthorized modification, 14: cross-workspace access) lives in
test_configuration_api.py, where a real authenticated FastAPI app exists
to attack.

Configuration is preference, not authority: every test here proves either
a structural absence (no field exists that could express the attack at
all) or that the value still passes through an existing, unmodified
authority (PlatformConfig.load()'s validation, MCPServerRegistry's
discovery-intersection gate) rather than bypassing it.
"""
import pytest

from agent_platform.config import ConfigurationError, PlatformConfig
from agent_platform.events import EventLog
from agent_platform.mcp.client import MCPClient
from agent_platform.mcp.gateway_tools import register_mcp_capabilities
from agent_platform.mcp.mock_transport import MockMCPTransport
from agent_platform.security.enums import Role, SessionMode
from agent_platform.security.permission import PermissionEvaluator
from agent_platform.security.sandbox import FilesystemSandbox
from agent_platform.settings.builder import build_mcp_server_configs, build_platform_config_kwargs
from agent_platform.settings.loader import SettingsValidationError, parse_settings
from agent_platform.settings.schema import AgentBehaviorSettings, McpServerSettingsEntry, WorkspaceSettings
from agent_platform.tools.gateway import ToolGateway
from agent_platform.tools.registry import build_default_registry


# ---- 1-4: settings cannot express a permission/role/capability grant at all

@pytest.mark.parametrize("bogus_key", [
    "permissions", "role_permissions", "tool_grants", "filesystem_access",
    "coder_permissions", "security", "sandbox", "disable_security", "operating_mode_policy",
    "specification", "spec_store",
])
def test_no_settings_field_can_express_a_permission_role_or_security_change(bogus_key):
    """Covers attacks 1, 2, 3, 5, 15, 16 in one parametrized sweep: none
    of these concepts have a corresponding settings key at all - the
    schema (schema.py) simply has no field shaped like a permission
    grant, a role assignment, a security toggle, or a spec/mode-policy
    override, so attempting to set one is indistinguishable from any
    other unknown top-level key and is rejected identically."""
    with pytest.raises(SettingsValidationError):
        parse_settings({bogus_key: {"grant": "filesystem.write", "role": "CODER"}})


def test_mcp_capabilities_still_gated_by_discovery_intersection_not_settings_alone():
    """Attack 4: even a settings file boldly declaring an MCP capability
    the server doesn't actually support is still bounded by the existing
    Phase 4 discovery-intersection gate (mcp/gateway_tools.py) - settings
    only supplies one side of that intersection, never bypasses it."""
    settings = WorkspaceSettings(mcp={"docs": McpServerSettingsEntry(
        server_id="docs", capabilities=("search", "delete_everything"))})
    configs = build_mcp_server_configs(settings)
    assert configs[0].capabilities == ("search", "delete_everything")  # trusted config as-declared

    transport = MockMCPTransport({"search": [{"ok": True}]})  # server only actually discovers "search"
    client = MCPClient(transport)
    registry = build_default_registry()
    grants = register_mcp_capabilities(registry, configs, {"docs": client},
                                        (Role.PLANNER, Role.CODER, Role.REVIEWER))
    registered_tools = {name for (_role, name) in grants}
    assert "mcp.docs.search" in registered_tools
    assert "mcp.docs.delete_everything" not in registered_tools  # never discovered -> never registered


# ---- 6-7: path traversal / UNC via agent_data_dir

@pytest.mark.parametrize("malicious_dir", ["../../escape", "..\\..\\escape", "\\\\attacker\\share",
                                            "C:\\Windows\\Temp", "/etc"])
def test_agent_data_dir_traversal_and_unc_rejected_by_existing_platform_config_validation(
        tmp_path, malicious_dir):
    settings = WorkspaceSettings(agent_behavior=AgentBehaviorSettings(agent_data_dir=malicious_dir))
    kwargs = build_platform_config_kwargs(settings)
    with pytest.raises(ConfigurationError):
        PlatformConfig.load(str(tmp_path), **kwargs)


# ---- 8: raw credential value where a reference name was expected

def test_raw_looking_credential_value_is_never_used_as_the_actual_credential(monkeypatch):
    monkeypatch.delenv("AGENT_PLATFORM_MCP_CREDENTIAL_GHP_LIVEXXXXXXXXXXXX", raising=False)
    settings = WorkspaceSettings(mcp={"github": McpServerSettingsEntry(
        server_id="github", credential_reference="ghp_liveXXXXXXXXXXXX")})
    configs = build_mcp_server_configs(settings)
    assert configs[0].credential is None  # treated as a (non-matching) lookup key, never the secret itself


# ---- 10-11: malformed YAML / unknown keys fail closed

def test_malformed_settings_yaml_fails_closed(tmp_path):
    from agent_platform.settings.loader import load_settings_file
    path = tmp_path / "settings.yaml"
    path.write_text("agent_behavior: [unterminated\n  key: value\n", encoding="utf-8")
    with pytest.raises(SettingsValidationError):
        load_settings_file(path)


def test_unknown_nested_key_fails_closed_not_silently_ignored():
    with pytest.raises(SettingsValidationError):
        parse_settings({"models": {"planner": "x", "backdoor": "y"}})


# ---- 12: invalid model identifiers degrade gracefully, never crash

def test_invalid_model_identifier_reports_unavailable_not_a_crash():
    from agent_platform.settings.model_discovery import describe_configured_models
    from agent_platform.settings.schema import ModelSettings
    described = describe_configured_models(
        ModelSettings(planner="totally-made-up-model:999b"), installed=("real-model:7b",))
    assert described["planner"] == {"model_id": "totally-made-up-model:999b", "available": False}


# ---- structural: no code path from settings to PermissionEvaluator/ToolGateway at all

def test_settings_modules_never_import_permission_evaluator_or_toolgateway():
    """The strongest form of 'configuration is not authority': the
    settings package's own source has no import of the enforcement
    modules at all, so there is no *possible* call path from a settings
    file to a permission decision, not just an untested one."""
    import ast
    import pathlib

    from agent_platform import settings as settings_pkg

    forbidden = {"ToolGateway", "PermissionEvaluator", "FilesystemSandbox"}
    package_dir = pathlib.Path(settings_pkg.__file__).parent
    for py_file in package_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        names = {n.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                 for n in node.names}
        assert not (names & forbidden), f"{py_file.name} imports {names & forbidden}"
