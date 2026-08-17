"""Deterministic, in-process mock MCP server/transport - proves the full
MCP integration end to end without a real external server. Scriptable
per capability, mirroring FakeModelProvider's queue-based design from
Phase 1: each capability gets a list of pre-configured raw responses
(dicts), exceptions to raise, or the TIMEOUT sentinel, popped in order.
"""
from __future__ import annotations


class MockServerFailure(Exception):
    pass


class _TimeoutSentinel:
    def __repr__(self) -> str:
        return "MCP_TIMEOUT"


TIMEOUT = _TimeoutSentinel()


class MockMCPTransport:
    def __init__(self, capabilities: dict):
        self._capabilities = {name: list(responses) for name, responses in capabilities.items()}

    def discover(self) -> tuple:
        return tuple(self._capabilities.keys())

    def call(self, capability: str, arguments: dict, timeout_seconds: float):
        if capability not in self._capabilities:
            raise MockServerFailure(f"unknown capability: {capability}")
        queue = self._capabilities[capability]
        if not queue:
            raise MockServerFailure(f"mock transport exhausted for capability: {capability}")
        item = queue.pop(0)
        if item is TIMEOUT:
            raise TimeoutError("mock MCP request timed out")
        if isinstance(item, Exception):
            raise item
        return item
