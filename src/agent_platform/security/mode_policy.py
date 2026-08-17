"""OperatingMode policy table: the additive, per-session tool/role
restriction layer PermissionEvaluator consults after its existing
base-table lookup. CODE and EDIT are strict no-ops - None means "no
additional restriction" for both allowed_roles and allowed_tools - so
today's Code/Edit behavior is byte-for-byte unchanged (see
test_code_and_edit_preserve_existing_permission_behavior). CHAT, PLAN,
and REVIEW narrow what today's base tool table would otherwise allow;
they never grant anything the base table + mode_grants doesn't already
establish.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .enums import OperatingMode, Role, ToolPermission

# Read-only fs + read-only git, the common allowance shared by every
# restricted (non-Code/Edit) mode.
_READ_ONLY_TOOLS: frozenset[str] = frozenset({
    "filesystem.read", "filesystem.list",
    "git.status", "git.diff", "git.log", "git.branch",
})

_PLAN_WRITE_TOOLS: frozenset[str] = frozenset({
    "filesystem.write", "filesystem.create_directory",
})

# Relative to the active project root - the only place Planner may write
# while in PLAN mode.
PLAN_SCOPE_DIRECTORY = ".agent/plans"


@dataclass(frozen=True)
class ModePolicy:
    allowed_roles: Optional[frozenset]  # None = no role filter (CODE/EDIT)
    allowed_tools: Optional[frozenset]  # None = no allowlist filter (CODE/EDIT)
    mode_grants: dict = field(default_factory=dict)  # additive grants that exist ONLY in this mode
    write_scope: dict = field(default_factory=dict)  # tool_name -> scope subdirectory name


MODE_POLICIES: dict[OperatingMode, ModePolicy] = {
    OperatingMode.CODE: ModePolicy(allowed_roles=None, allowed_tools=None),
    OperatingMode.EDIT: ModePolicy(allowed_roles=None, allowed_tools=None),
    OperatingMode.CHAT: ModePolicy(
        allowed_roles=frozenset({Role.PLANNER}),
        allowed_tools=_READ_ONLY_TOOLS,
    ),
    OperatingMode.PLAN: ModePolicy(
        allowed_roles=frozenset({Role.PLANNER, Role.REVIEWER}),
        allowed_tools=_READ_ONLY_TOOLS | _PLAN_WRITE_TOOLS,
        mode_grants={
            (Role.PLANNER, "filesystem.write"): ToolPermission.ALLOW,
            (Role.PLANNER, "filesystem.create_directory"): ToolPermission.ALLOW,
        },
        write_scope={
            "filesystem.write": PLAN_SCOPE_DIRECTORY,
            "filesystem.create_directory": PLAN_SCOPE_DIRECTORY,
        },
    ),
    OperatingMode.REVIEW: ModePolicy(
        allowed_roles=frozenset({Role.REVIEWER}),
        allowed_tools=_READ_ONLY_TOOLS,
    ),
}
