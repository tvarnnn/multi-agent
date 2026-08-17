"""Turns configured MCP capabilities into typed tools registered in the
SAME ToolRegistry every other tool lives in, and grants for them into
the SAME PermissionEvaluator tool table every other permission lives in
(via the tool_table override parameter it was already built to accept).
This is the entire enforcement of "reuse the existing permission
architecture, do not create an independent MCP permission system": there
is no MCP-specific authority check anywhere - a mcp.<server>.<capability>
call goes through the exact same 6-step ToolGateway pipeline as
filesystem.write or test.run.

Capability registration is the intersection of what a server claims via
discover() and what trusted config declares in
MCPServerConfig.capabilities - discovery can only narrow what gets
registered, never expand it. A compromised or malicious server claiming
an extra capability cannot get a tool registered for it.
"""
from __future__ import annotations

import json

from ..security.enums import Role, ToolPermission
from ..tools.registry import ToolRegistry
from ..tools.schemas import ToolArgumentError, ToolExecutionContext, ToolSpec
from .client import MCPClient
from .schemas import MCPServerConfig
from .secrets import redact_secret_string, redact_secrets

_RESERVED_MCP_ARG_KEYS = {"server_id", "credential", "capability", "endpoint"}
_MAX_MCP_ARGUMENT_BYTES = 50_000


def _no_precondition(args: dict, ctx: ToolExecutionContext) -> None:
    return None


def _validate_mcp_arguments(args: dict) -> dict:
    if not isinstance(args, dict):
        raise ToolArgumentError("arguments must be an object")
    reserved = set(args) & _RESERVED_MCP_ARG_KEYS
    if reserved:
        raise ToolArgumentError(
            f"reserved argument key(s) not allowed from callers: {sorted(reserved)} - "
            "server identity and credentials come from trusted configuration only"
        )
    try:
        serialized = json.dumps(args)
    except (TypeError, ValueError) as exc:
        raise ToolArgumentError(f"arguments must be JSON-serializable: {exc}")
    if len(serialized) > _MAX_MCP_ARGUMENT_BYTES:
        raise ToolArgumentError(f"arguments exceed the {_MAX_MCP_ARGUMENT_BYTES}-byte limit")
    return dict(args)


def _make_mcp_executor(client: MCPClient, capability: str, secrets: tuple):
    def execute(args: dict, ctx: ToolExecutionContext) -> dict:
        response = client.call(capability, args)
        return {
            "status": response.status,
            "data": redact_secrets(response.data, secrets),
            "error": redact_secret_string(response.error, secrets),
        }
    return execute


def _usable_capabilities(server_config: MCPServerConfig, client: MCPClient) -> set:
    discovered = set(client.discover())
    allowed = set(server_config.capabilities)
    return discovered & allowed


def build_mcp_tool_specs(server_config: MCPServerConfig, client: MCPClient) -> list:
    secrets = (server_config.credential,) if server_config.credential else ()
    specs = []
    for capability in sorted(_usable_capabilities(server_config, client)):
        specs.append(ToolSpec(
            name=f"mcp.{server_config.server_id}.{capability}",
            validate_arguments=_validate_mcp_arguments,
            path_argument_key=None,
            check_preconditions=_no_precondition,
            execute=_make_mcp_executor(client, capability, secrets),
        ))
    return specs


def build_mcp_permission_grants(server_config: MCPServerConfig, client: MCPClient,
                                 roles: tuple) -> dict:
    grants = {}
    for capability in _usable_capabilities(server_config, client):
        tool_name = f"mcp.{server_config.server_id}.{capability}"
        for role in roles:
            grants[(role, tool_name)] = ToolPermission.ALLOW
    return grants


def register_mcp_capabilities(registry: ToolRegistry, server_configs: tuple,
                               clients: dict, roles: tuple) -> dict:
    grants: dict = {}
    for server_config in server_configs:
        client = clients[server_config.server_id]
        for spec in build_mcp_tool_specs(server_config, client):
            registry.register(spec)
        grants.update(build_mcp_permission_grants(server_config, client, roles))
    return grants
