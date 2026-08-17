"""The only thing in this codebase that talks to an MCP transport (mock
or, eventually, real). Every response becomes a deterministic
MCPResponse - a transport exception, a timeout, a non-dict payload, or
an oversized payload never propagate as a raw exception and never become
anything except one of the four failure statuses below. MCP responses
only ever leave this module as MCPResponse.data, a plain dict - inert
data, never anything the orchestrator interprets as an instruction.
"""
from __future__ import annotations

import json
from typing import Protocol

from .schemas import MCPResponse


class MCPTransport(Protocol):
    def discover(self) -> tuple: ...
    def call(self, capability: str, arguments: dict, timeout_seconds: float): ...


class MCPClient:
    def __init__(self, transport: MCPTransport, *, timeout_seconds: float = 30.0,
                 max_response_bytes: int = 200_000):
        self._transport = transport
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes

    def discover(self) -> tuple:
        try:
            return self._transport.discover()
        except Exception:
            return ()

    def call(self, capability: str, arguments: dict) -> MCPResponse:
        try:
            raw = self._transport.call(capability, arguments, self._timeout_seconds)
        except TimeoutError as exc:
            return MCPResponse(status="timeout", data=None, error=str(exc))
        except Exception as exc:
            return MCPResponse(status="error", data=None, error=str(exc))

        if not isinstance(raw, dict):
            return MCPResponse(status="malformed", data=None, error="response was not a JSON object")

        try:
            size = len(json.dumps(raw))
        except (TypeError, ValueError):
            return MCPResponse(status="malformed", data=None, error="response was not JSON-serializable")

        if size > self._max_response_bytes:
            return MCPResponse(
                status="oversized", data=None,
                error=f"response of {size} bytes exceeded the {self._max_response_bytes}-byte limit",
            )

        return MCPResponse(status="ok", data=raw, error=None)
