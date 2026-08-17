"""MCP domain types. Credentials live only in MCPServerConfig, set once
from trusted configuration - there is no method anywhere on this class
or on MCPServerRegistry (server_registry.py) that lets model output, an
MCP response, or a caller argument create, replace, or mutate a server
entry after construction.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class MCPServerConfig:
    server_id: str
    transport: str
    capabilities: tuple[str, ...]
    credential: Optional[str] = None


@dataclass(frozen=True)
class MCPResponse:
    status: str
    data: Optional[dict]
    error: Optional[str]
