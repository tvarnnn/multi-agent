"""A real MCP transport over stdio JSON-RPC 2.0, verified against the
official @modelcontextprotocol/server-filesystem reference server
(protocolVersion 2024-11-05). Spawns the server process once at
construction, performs the initialize/initialized handshake, and
translates tools/call responses - including the server's `isError: true`
convention, where an application-level failure comes back as a normal
JSON-RPC result rather than a JSON-RPC error - into the same plain-dict-
or-raise shape MockMCPTransport uses. MCPClient (client.py) needed zero
changes to accept this: it was written against the MCPTransport Protocol,
not against the mock.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from typing import Optional


class RealMCPStdioTransport:
    def __init__(self, command: list[str], *, startup_timeout: float = 60.0):
        self._proc = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, shell=True,
        )
        self._next_id = 1
        self._lock = threading.Lock()
        self._tools: tuple = ()
        self._handshake(startup_timeout)

    def _send(self, msg: dict) -> None:
        self._proc.stdin.write(json.dumps(msg) + "\n")
        self._proc.stdin.flush()

    def _recv(self, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self._proc.stdout.readline()
            if line.strip():
                return json.loads(line)
        raise TimeoutError("no response from MCP server within timeout")

    def _handshake(self, timeout: float) -> None:
        self._send({
            "jsonrpc": "2.0", "id": self._next_id, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "agent-platform", "version": "0.1.0"}},
        })
        self._next_id += 1
        self._recv(timeout)
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        list_id = self._next_id
        self._next_id += 1
        self._send({"jsonrpc": "2.0", "id": list_id, "method": "tools/list", "params": {}})
        response = self._recv(timeout)
        self._tools = tuple(t["name"] for t in response.get("result", {}).get("tools", []))

    def discover(self) -> tuple:
        return self._tools

    def call(self, capability: str, arguments: dict, timeout_seconds: float) -> dict:
        with self._lock:
            request_id = self._next_id
            self._next_id += 1
            self._send({"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                        "params": {"name": capability, "arguments": arguments}})
            response = self._recv(timeout_seconds)

        if "error" in response:
            raise RuntimeError(response["error"].get("message", "MCP protocol error"))

        result = response.get("result", {})
        content_items = result.get("content", [])
        text = "; ".join(item.get("text", "") for item in content_items if item.get("type") == "text")
        if result.get("isError"):
            raise RuntimeError(text or "MCP tool call reported an error")
        return {"content": text}

    def close(self) -> None:
        self._proc.terminate()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
