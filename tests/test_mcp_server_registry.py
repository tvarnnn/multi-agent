from agent_platform.mcp.schemas import MCPServerConfig
from agent_platform.mcp.server_registry import MCPServerRegistry


def _config(server_id="mock-docs"):
    return MCPServerConfig(server_id=server_id, transport="mock", capabilities=("search", "fetch"))


def test_get_returns_a_registered_server():
    registry = MCPServerRegistry((_config(),))
    assert registry.get("mock-docs").transport == "mock"


def test_get_returns_none_for_an_unregistered_server():
    registry = MCPServerRegistry((_config(),))
    assert registry.get("does-not-exist") is None


def test_list_servers_returns_every_configured_server():
    registry = MCPServerRegistry((_config("a"), _config("b")))
    ids = {s.server_id for s in registry.list_servers()}
    assert ids == {"a", "b"}


def test_registry_exposes_no_mutation_method():
    # Structural proof, not just a convention: nothing reachable from
    # model output, an MCP response, or a caller argument can register a
    # new server or change an existing one - because no such method
    # exists on this class at all.
    registry = MCPServerRegistry((_config(),))
    mutating_names = {"register", "add", "add_server", "update", "set", "remove", "delete"}
    present = mutating_names & set(dir(registry))
    assert not present, f"unexpected mutating method(s) found: {present}"


def test_empty_registry_is_valid():
    registry = MCPServerRegistry(())
    assert registry.list_servers() == ()
    assert registry.get("anything") is None
