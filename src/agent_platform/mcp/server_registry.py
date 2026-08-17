"""Trusted-config-only MCP server registry. Constructed once from a
fixed tuple of MCPServerConfig objects; there is no register()/update()
method exposed anywhere - adding or changing a server requires changing
the trusted configuration that constructs this registry, never anything
reachable from model output or an MCP response.
"""
from __future__ import annotations

from typing import Optional

from .schemas import MCPServerConfig


class MCPServerRegistry:
    def __init__(self, servers: tuple[MCPServerConfig, ...]):
        self._servers = {s.server_id: s for s in servers}

    def get(self, server_id: str) -> Optional[MCPServerConfig]:
        return self._servers.get(server_id)

    def list_servers(self) -> tuple[MCPServerConfig, ...]:
        return tuple(self._servers.values())
