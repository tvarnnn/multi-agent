import pytest

from agent_platform.context.bundle_builder import build_context_bundle
from agent_platform.events import EventLog
from agent_platform.mcp.client import MCPClient
from agent_platform.mcp.gateway_tools import register_mcp_capabilities
from agent_platform.mcp.mock_transport import TIMEOUT, MockMCPTransport, MockServerFailure
from agent_platform.mcp.schemas import MCPServerConfig
from agent_platform.security.enums import Role, SessionMode
from agent_platform.security.permission import PermissionEvaluator
from agent_platform.security.sandbox import FilesystemSandbox
from agent_platform.tools.gateway import ToolGateway
from agent_platform.tools.registry import build_default_registry


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    (root / "MyProj").mkdir()
    return root


def test_mcp_timeout_failure_is_a_clean_observation_not_a_crash(workspace):
    config = MCPServerConfig(server_id="docs", transport="mock", capabilities=("search",))
    client = MCPClient(MockMCPTransport({"search": [TIMEOUT]}))
    registry = build_default_registry()
    sandbox = FilesystemSandbox(workspace)
    grants = register_mcp_capabilities(registry, (config,), {"docs": client}, (Role.CODER,))
    evaluator = PermissionEvaluator(sandbox, tool_table=grants)
    gateway = ToolGateway(registry, evaluator, EventLog())
    obs = gateway.invoke(role=Role.CODER, tool_name="mcp.docs.search", arguments={"query": "x"},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "ok"  # the gateway call succeeded
    assert obs.result["status"] == "timeout"  # the MCP-level result carries the failure


def test_mcp_server_failure_is_a_clean_observation_not_a_crash(workspace):
    config = MCPServerConfig(server_id="docs", transport="mock", capabilities=("search",))
    client = MCPClient(MockMCPTransport({"search": [MockServerFailure("upstream is down")]}))
    registry = build_default_registry()
    sandbox = FilesystemSandbox(workspace)
    grants = register_mcp_capabilities(registry, (config,), {"docs": client}, (Role.CODER,))
    evaluator = PermissionEvaluator(sandbox, tool_table=grants)
    gateway = ToolGateway(registry, evaluator, EventLog())
    obs = gateway.invoke(role=Role.CODER, tool_name="mcp.docs.search", arguments={"query": "x"},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "ok"
    assert obs.result["status"] == "error"


def test_unauthorized_mcp_request_is_denied(workspace):
    config = MCPServerConfig(server_id="docs", transport="mock", capabilities=("search",))
    client = MCPClient(MockMCPTransport({"search": [{"results": []}]}))
    registry = build_default_registry()
    sandbox = FilesystemSandbox(workspace)
    # Only CODER is granted access - PLANNER is not, in this configuration.
    grants = register_mcp_capabilities(registry, (config,), {"docs": client}, (Role.CODER,))
    evaluator = PermissionEvaluator(sandbox, tool_table=grants)
    gateway = ToolGateway(registry, evaluator, EventLog())
    obs = gateway.invoke(role=Role.PLANNER, tool_name="mcp.docs.search", arguments={"query": "x"},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "denied"


def test_context_retrieval_degrades_gracefully_when_a_gateway_call_is_denied(workspace):
    # A role with no filesystem.list grant (there isn't one in the
    # default table, so this simulates the general "a gateway call
    # inside retrieval fails" case) must not crash retrieval - it should
    # simply retrieve nothing rather than propagate an exception.
    sandbox = FilesystemSandbox(workspace)
    evaluator = PermissionEvaluator(sandbox, tool_table={})  # no grants for anyone
    gateway = ToolGateway(build_default_registry(), evaluator, EventLog())
    bundle = build_context_bundle(gateway=gateway, role=Role.CODER, session_mode=SessionMode.AUTO,
                                   project_root=(workspace / "MyProj").resolve(),
                                   reference_hints=("fix app.py",))
    # No real file could be discovered or read (every gateway call is
    # denied) - the engine degrades to the well-formed, empty tree-listing
    # fallback rather than crashing, hanging, or fabricating content.
    assert bundle.changed_files == ()
    assert all(f.category == "tree" and f.content == "" for f in bundle.files)
