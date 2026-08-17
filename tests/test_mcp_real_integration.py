"""Real MCP integration test - the one real external server this project
integrates with, per the "only one, after the mock is fully tested"
instruction. Spawns @modelcontextprotocol/server-filesystem via npx
(fetched once from the npm registry on first run) scoped to an isolated
sandbox directory, never the real project workspace. Kept in its own
file, excluded from the deterministic --ignore runs, exactly like Phase
2's test_ollama_integration.py.
"""
import shutil
from pathlib import Path

import pytest

from agent_platform.events import EventLog
from agent_platform.mcp.client import MCPClient
from agent_platform.mcp.gateway_tools import register_mcp_capabilities
from agent_platform.mcp.real_stdio_transport import RealMCPStdioTransport
from agent_platform.mcp.schemas import MCPServerConfig
from agent_platform.security.enums import Role, SessionMode
from agent_platform.security.permission import PermissionEvaluator
from agent_platform.security.sandbox import FilesystemSandbox
from agent_platform.tools.gateway import ToolGateway
from agent_platform.tools.registry import build_default_registry

SANDBOX_DIR = Path(__file__).resolve().parent.parent / "mcp_real_server_sandbox"


@pytest.fixture(scope="module")
def real_transport():
    transport = RealMCPStdioTransport(
        ["npx", "-y", "@modelcontextprotocol/server-filesystem", str(SANDBOX_DIR)],
        startup_timeout=60.0,
    )
    yield transport
    transport.close()


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    (root / "MyProj").mkdir()
    return root


def test_real_server_discovers_its_actual_tool_list(real_transport):
    discovered = real_transport.discover()
    assert "read_text_file" in discovered
    assert "write_file" in discovered  # confirms discovery is unfiltered - curation happens at OUR trusted-config layer


def test_curated_config_registers_only_the_read_only_subset(workspace, real_transport):
    # The server offers write_file/edit_file/move_file/create_directory
    # too - trusted config deliberately never lists them, so the
    # intersection (Task 4's _usable_capabilities) excludes them even
    # though the real server would happily execute them.
    config = MCPServerConfig(server_id="real-fs", transport="stdio",
                              capabilities=("read_text_file", "list_directory"))
    client = MCPClient(real_transport)
    registry = build_default_registry()
    sandbox = FilesystemSandbox(workspace)
    grants = register_mcp_capabilities(registry, (config,), {"real-fs": client},
                                        (Role.PLANNER, Role.CODER, Role.REVIEWER))
    assert registry.get("mcp.real-fs.read_text_file") is not None
    assert registry.get("mcp.real-fs.list_directory") is not None
    assert registry.get("mcp.real-fs.write_file") is None
    assert registry.get("mcp.real-fs.edit_file") is None
    assert registry.get("mcp.real-fs.move_file") is None


def test_real_read_through_the_full_gateway_pipeline(workspace, real_transport):
    config = MCPServerConfig(server_id="real-fs", transport="stdio",
                              capabilities=("read_text_file", "list_directory"))
    client = MCPClient(real_transport)
    registry = build_default_registry()
    sandbox = FilesystemSandbox(workspace)
    grants = register_mcp_capabilities(registry, (config,), {"real-fs": client}, (Role.CODER,))
    evaluator = PermissionEvaluator(sandbox, tool_table=grants)
    gateway = ToolGateway(registry, evaluator, EventLog())
    obs = gateway.invoke(role=Role.CODER, tool_name="mcp.real-fs.read_text_file",
                          arguments={"path": "sample.txt"}, session_mode=SessionMode.AUTO,
                          project_root=(workspace / "MyProj").resolve())
    assert obs.status == "ok"
    assert obs.result["status"] == "ok"
    assert "harmless sample file" in obs.result["data"]["content"]


def test_real_server_application_error_becomes_a_clean_error_status(workspace, real_transport):
    config = MCPServerConfig(server_id="real-fs", transport="stdio", capabilities=("read_text_file",))
    client = MCPClient(real_transport)
    registry = build_default_registry()
    sandbox = FilesystemSandbox(workspace)
    grants = register_mcp_capabilities(registry, (config,), {"real-fs": client}, (Role.CODER,))
    evaluator = PermissionEvaluator(sandbox, tool_table=grants)
    gateway = ToolGateway(registry, evaluator, EventLog())
    obs = gateway.invoke(role=Role.CODER, tool_name="mcp.real-fs.read_text_file",
                          arguments={"path": "does_not_exist.txt"}, session_mode=SessionMode.AUTO,
                          project_root=(workspace / "MyProj").resolve())
    # The gateway call itself succeeded (status ok) - the MCP-level
    # result carries the real server's error, exactly like a malformed
    # or timed-out mock response would, never a raised exception.
    assert obs.status == "ok"
    assert obs.result["status"] == "error"
    assert "ENOENT" in obs.result["error"] or "no such file" in obs.result["error"].lower()


def test_git_and_shell_tools_remain_denied_alongside_the_real_mcp_server(workspace, real_transport):
    config = MCPServerConfig(server_id="real-fs", transport="stdio", capabilities=("read_text_file",))
    client = MCPClient(real_transport)
    registry = build_default_registry()
    sandbox = FilesystemSandbox(workspace)
    grants = register_mcp_capabilities(registry, (config,), {"real-fs": client}, (Role.CODER,))
    evaluator = PermissionEvaluator(sandbox, tool_table=grants)
    gateway = ToolGateway(registry, evaluator, EventLog())
    for tool in ("git.commit", "git.push", "shell.run"):
        obs = gateway.invoke(role=Role.CODER, tool_name=tool, arguments={},
                              session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
        assert obs.status != "ok"
