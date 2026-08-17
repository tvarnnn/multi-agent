"""Deterministic permission evaluation: role x session mode x tool x
concrete arguments x active project x filesystem path -> decision.

LLMs never make security decisions and prompts are not security controls -
this evaluator is the only thing that decides whether a tool call
proceeds, and it never consults model output to do so. Permission is
evaluated per invocation with concrete arguments, never by tool name
alone - see test_allow_tool_with_denied_path_is_still_denied.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .enums import Role, SessionMode, ToolPermission
from .sandbox import FilesystemSandbox

_TIER = {ToolPermission.DENY: 0, ToolPermission.CONFIRM: 1, ToolPermission.ALLOW: 2}
_TIER_TO_PERMISSION = {v: k for k, v in _TIER.items()}

_SESSION_CEILING = {
    SessionMode.AUTO: ToolPermission.ALLOW,
    SessionMode.CONFIRMATION: ToolPermission.CONFIRM,
    SessionMode.MANUAL: ToolPermission.CONFIRM,
}

# Absolute denies: no role, no session mode, no table entry can ever grant
# these. Git write operations are here because git is human-controlled -
# the agent never commits, never inits, never pushes. shell.run is here
# because Phase 0/1 ship with typed tools only, no unrestricted shell.
ABSOLUTE_DENY_TOOLS: frozenset[str] = frozenset({
    "git.init", "git.add", "git.commit", "git.push",
    "git.reset", "git.rebase", "shell.run",
})

ToolTable = dict[tuple[Role, str], ToolPermission]


def _default_tool_table() -> ToolTable:
    table: ToolTable = {}
    read_tools = [
        "filesystem.read", "filesystem.list",
        "git.status", "git.diff", "git.log", "git.branch",
    ]
    for role in Role:
        for tool in read_tools:
            table[(role, tool)] = ToolPermission.ALLOW
    table[(Role.CODER, "filesystem.write")] = ToolPermission.ALLOW
    table[(Role.CODER, "filesystem.create_directory")] = ToolPermission.ALLOW
    for tool in ("test.run", "lint.run", "typecheck.run"):
        table[(Role.CODER, tool)] = ToolPermission.ALLOW
        table[(Role.REVIEWER, tool)] = ToolPermission.ALLOW
    return table


@dataclass(frozen=True)
class ToolCall:
    role: Role
    tool_name: str
    path_argument: Optional[str] = None
    scope_root: Optional[Path] = None


@dataclass(frozen=True)
class PermissionDecision:
    permission: ToolPermission
    reason: str
    resolved_path: Optional[Path] = None

    @property
    def is_denied(self) -> bool:
        return self.permission == ToolPermission.DENY


class PermissionEvaluator:
    def __init__(self, sandbox: FilesystemSandbox, tool_table: Optional[ToolTable] = None):
        self._sandbox = sandbox
        self._table: ToolTable = dict(_default_tool_table())
        if tool_table is not None:
            self._table.update(tool_table)

    def evaluate(self, call: ToolCall, session_mode: SessionMode) -> PermissionDecision:
        if call.tool_name in ABSOLUTE_DENY_TOOLS:
            return PermissionDecision(
                ToolPermission.DENY, f"{call.tool_name} is an absolute deny, no exceptions"
            )

        static_permission = self._table.get((call.role, call.tool_name), ToolPermission.DENY)
        if static_permission == ToolPermission.DENY:
            return PermissionDecision(
                ToolPermission.DENY,
                f"no ALLOW/CONFIRM grant for {call.role.value}:{call.tool_name}",
            )

        resolved_path: Optional[Path] = None
        if call.path_argument is not None:
            path_decision = self._sandbox.authorize(call.path_argument, scope_root=call.scope_root)
            if not path_decision.allowed:
                return PermissionDecision(ToolPermission.DENY, f"sandbox denial: {path_decision.reason}")
            resolved_path = path_decision.resolved_path

        ceiling = _SESSION_CEILING[session_mode]
        effective_tier = min(_TIER[static_permission], _TIER[ceiling])
        effective = _TIER_TO_PERMISSION[effective_tier]
        return PermissionDecision(
            effective, f"{static_permission.value} capped by {session_mode.value} ceiling",
            resolved_path=resolved_path,
        )
