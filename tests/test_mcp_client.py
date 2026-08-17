import pytest

from agent_platform.mcp.client import MCPClient
from agent_platform.mcp.mock_transport import TIMEOUT, MockMCPTransport, MockServerFailure


def test_discover_returns_configured_capability_names():
    transport = MockMCPTransport({"search": [{"results": []}], "fetch": [{"content": ""}]})
    client = MCPClient(transport)
    assert set(client.discover()) == {"search", "fetch"}


def test_successful_call_returns_ok_status_with_data():
    transport = MockMCPTransport({"search": [{"results": ["a", "b"]}]})
    client = MCPClient(transport)
    response = client.call("search", {"query": "fastapi"})
    assert response.status == "ok"
    assert response.data == {"results": ["a", "b"]}
    assert response.error is None


def test_non_dict_response_is_malformed():
    transport = MockMCPTransport({"search": ["not a dict, just a string"]})
    client = MCPClient(transport)
    response = client.call("search", {})
    assert response.status == "malformed"
    assert response.data is None


def test_oversized_response_is_rejected_without_being_returned_as_data():
    transport = MockMCPTransport({"search": [{"results": "x" * 1000}]})
    client = MCPClient(transport, max_response_bytes=100)
    response = client.call("search", {})
    assert response.status == "oversized"
    assert response.data is None


def test_timeout_sentinel_produces_a_timeout_status_not_a_raised_exception():
    transport = MockMCPTransport({"search": [TIMEOUT]})
    client = MCPClient(transport)
    response = client.call("search", {})
    assert response.status == "timeout"
    assert response.data is None


def test_server_failure_produces_an_error_status_not_a_raised_exception():
    transport = MockMCPTransport({"search": [MockServerFailure("upstream exploded")]})
    client = MCPClient(transport)
    response = client.call("search", {})
    assert response.status == "error"
    assert "upstream exploded" in response.error


def test_calling_an_unknown_capability_is_an_error_not_a_crash():
    transport = MockMCPTransport({"search": [{"results": []}]})
    client = MCPClient(transport)
    response = client.call("does-not-exist", {})
    assert response.status == "error"


def test_discover_failure_returns_empty_tuple_not_a_raised_exception():
    class BrokenTransport:
        def discover(self):
            raise RuntimeError("discovery endpoint down")

        def call(self, capability, arguments, timeout_seconds):
            raise RuntimeError("unreachable")

    client = MCPClient(BrokenTransport())
    assert client.discover() == ()
