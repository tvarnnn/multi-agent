"""Plan artifact filename derivation and Markdown writing. Every write
goes through the existing ToolGateway as Role.PLANNER +
OperatingMode.PLAN - the exact same 6-step pipeline (and PLAN mode's
.agent/plans/** sandbox scope, security/mode_policy.py) every other tool
call uses. There is no privileged write path here.

Immutability (design §5.3): a file is only overwritten while its status
is DRAFT or REVISED. This module has no memory of its own - PlanSession
(orchestrator/core.py) is the single source of truth for "which artifact
for this spec_id, and is it still mutable"; this module just derives
filenames and performs the write.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path

from ..security.enums import OperatingMode, Role, SessionMode
from ..spec.versioning import SpecStore
from ..tools.gateway import ToolGateway, ToolObservation
from .plan_markdown import render_plan_markdown
from .plan_schemas import StructuredPlan

PLAN_DIRECTORY = ".agent/plans"

_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")
_MAX_SLUG_LENGTH = 40


def slugify(text: str) -> str:
    slug = _SLUG_PATTERN.sub("-", text.lower()).strip("-")
    return slug[:_MAX_SLUG_LENGTH].rstrip("-")


def predicted_next_version(spec_store: SpecStore, spec_id: str) -> int:
    """A *prediction* of the version this plan becomes if approved -
    never a reservation. SpecStore.create() is only ever called from
    approve_plan (design §7); nothing here touches SpecStore."""
    try:
        return spec_store.latest(spec_id).version + 1
    except KeyError:
        return 1


def plan_artifact_path(spec_id: str, version: int, *, slug: str = "", today: date | None = None) -> str:
    today = today or datetime.now(timezone.utc).date()
    base = f"{today.isoformat()}-{spec_id}-spec-v{version}"
    if slug:
        base = f"{base}-{slug}"
    return f"{PLAN_DIRECTORY}/{base}.md"


def write_plan_artifact(gateway: ToolGateway, *, session_mode: SessionMode, project_root: Path,
                         path: str, plan: StructuredPlan, status: str,
                         spec_version_label: str) -> ToolObservation:
    content = render_plan_markdown(plan, status=status, spec_version_label=spec_version_label)
    return gateway.invoke(
        role=Role.PLANNER, tool_name="filesystem.write",
        arguments={"path": path, "content": content},
        session_mode=session_mode, project_root=project_root,
        operating_mode=OperatingMode.PLAN,
    )
