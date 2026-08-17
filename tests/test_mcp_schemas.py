import dataclasses

import pytest

from agent_platform.mcp.schemas import MCPResponse, MCPServerConfig


def test_server_config_is_immutable():
    config = MCPServerConfig(server_id="mock-docs", transport="mock",
                              capabilities=("search",), credential="secret-token")
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.credential = "different"


def test_server_config_credential_defaults_to_none():
    config = MCPServerConfig(server_id="mock-docs", transport="mock", capabilities=("search",))
    assert config.credential is None


def test_response_is_immutable():
    response = MCPResponse(status="ok", data={"x": 1}, error=None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        response.status = "error"
