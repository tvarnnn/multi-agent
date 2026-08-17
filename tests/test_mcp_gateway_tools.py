import pytest

from agent_platform.events import EventLog
from agent_platform.mcp.client import MCPClient
from agent_platform.mcp.gateway_tools import (
    build_mcp_permission_grants,
    build_mcp_tool_specs,
    register_mcp_capabilities,
)
from agent_platform.mcp.mock_transport import MockMCPTransport
from agent_platform.mcp.preferences import MCPUserPreferences
from agent_platform.mcp.schemas import MCPServerConfig
from agent_platform.security.enums import Role, SessionMode, ToolPermission
from agent_platform.security.permission import PermissionEvaluator
from agent_platform.security.sandbox import FilesystemSandbox
from agent_platform.tools.gateway import ToolGateway
from agent_platform.tools.registry import ToolExecutionContext, build_default_registry


def _server_and_client(capabilities=("search", "fetch"), discovered=None):
    config = MCPServerConfig(server_id="mock-docs", transport="mock", capabilities=capabilities)
    transport = MockMCPTransport({name: [{"ok": True}] for name in (discovered or capabilities)})
    client = MCPClient(transport)
    return config, client


def test_tool_specs_are_named_mcp_serverid_capability():
    config, client = _server_and_client()
    specs = build_mcp_tool_specs(config, client)
    assert {s.name for s in specs} == {"mcp.mock-docs.search", "mcp.mock-docs.fetch"}


def test_discovery_cannot_expand_beyond_trusted_config_capabilities():
    # The server's discover() claims an extra capability the trusted
    # config never authorized - this is the capability-escalation attempt.
    config, client = _server_and_client(capabilities=("search",), discovered=("search", "delete_everything"))
    specs = build_mcp_tool_specs(config, client)
    assert {s.name for s in specs} == {"mcp.mock-docs.search"}


def test_trusted_config_cannot_grant_a_capability_the_server_never_discovered():
    config, client = _server_and_client(capabilities=("search", "fetch", "phantom"), discovered=("search",))
    specs = build_mcp_tool_specs(config, client)
    assert {s.name for s in specs} == {"mcp.mock-docs.search"}


def test_permission_grants_cover_every_requested_role():
    config, client = _server_and_client(capabilities=("search",))
    grants = build_mcp_permission_grants(config, client, (Role.PLANNER, Role.CODER, Role.REVIEWER))
    assert grants[(Role.PLANNER, "mcp.mock-docs.search")] == ToolPermission.ALLOW
    assert grants[(Role.CODER, "mcp.mock-docs.search")] == ToolPermission.ALLOW
    assert grants[(Role.REVIEWER, "mcp.mock-docs.search")] == ToolPermission.ALLOW


def test_tool_spec_validate_arguments_rejects_reserved_keys():
    config, client = _server_and_client(capabilities=("search",))
    spec = build_mcp_tool_specs(config, client)[0]
    from agent_platform.tools.schemas import ToolArgumentError
    with pytest.raises(ToolArgumentError):
        spec.validate_arguments({"server_id": "attacker-controlled"})
    with pytest.raises(ToolArgumentError):
        spec.validate_arguments({"credential": "steal-this"})


def test_tool_spec_validate_arguments_rejects_non_json_serializable_input():
    config, client = _server_and_client(capabilities=("search",))
    spec = build_mcp_tool_specs(config, client)[0]
    from agent_platform.tools.schemas import ToolArgumentError
    with pytest.raises(ToolArgumentError):
        spec.validate_arguments({"query": object()})


def test_tool_spec_execute_redacts_credential_from_response_data(tmp_path):
    config = MCPServerConfig(server_id="mock-docs", transport="mock", capabilities=("search",),
                              credential="sk-super-secret")
    transport = MockMCPTransport({"search": [{"note": "using key sk-super-secret to fetch this"}]})
    client = MCPClient(transport)
    spec = build_mcp_tool_specs(config, client)[0]
    ctx = ToolExecutionContext(resolved_path=None, project_root=tmp_path)
    result = spec.execute({"query": "x"}, ctx)
    assert "sk-super-secret" not in str(result)
    assert "[REDACTED]" in result["data"]["note"]


def test_register_mcp_capabilities_wires_registry_and_returns_grants(tmp_path):
    workspace = tmp_path / "Projects"
    workspace.mkdir()
    (workspace / "MyProj").mkdir()
    config, client = _server_and_client(capabilities=("search",))
    registry = build_default_registry()
    grants = register_mcp_capabilities(registry, (config,), {"mock-docs": client},
                                        (Role.PLANNER, Role.CODER, Role.REVIEWER))
    assert registry.get("mcp.mock-docs.search") is not None
    sandbox = FilesystemSandbox(workspace)
    evaluator = PermissionEvaluator(sandbox, tool_table=grants)
    gateway = ToolGateway(registry, evaluator, EventLog())
    obs = gateway.invoke(role=Role.PLANNER, tool_name="mcp.mock-docs.search", arguments={"query": "fastapi"},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "ok"
    assert obs.result["data"] == {"ok": True}


def test_user_preferences_narrow_registered_tool_specs_never_expand():
    config, client = _server_and_client(capabilities=("search", "fetch"))
    preferences = MCPUserPreferences()
    preferences.set_capability_enabled("mock-docs", "fetch", False)
    specs = build_mcp_tool_specs(config, client, preferences)
    assert {s.name for s in specs} == {"mcp.mock-docs.search"}


def test_user_preferences_disabling_server_removes_all_grants():
    config, client = _server_and_client(capabilities=("search", "fetch"))
    preferences = MCPUserPreferences()
    preferences.set_enabled("mock-docs", False)
    grants = build_mcp_permission_grants(config, client, (Role.PLANNER,), preferences)
    assert grants == {}


def test_unregistered_mcp_capability_is_unknown_tool_at_the_gateway(tmp_path):
    workspace = tmp_path / "Projects"
    workspace.mkdir()
    (workspace / "MyProj").mkdir()
    config, client = _server_and_client(capabilities=("search",), discovered=("search",))
    registry = build_default_registry()
    grants = register_mcp_capabilities(registry, (config,), {"mock-docs": client}, (Role.CODER,))
    sandbox = FilesystemSandbox(workspace)
    evaluator = PermissionEvaluator(sandbox, tool_table=grants)
    gateway = ToolGateway(registry, evaluator, EventLog())
    obs = gateway.invoke(role=Role.CODER, tool_name="mcp.mock-docs.delete_everything", arguments={},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "unknown_tool"
