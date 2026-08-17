"""Bounded context reconstruction for session resume. Authoritative
identity (operating_mode, session_mode) always comes from the persisted
sessions row, never from checkpoint content. Project content is always
re-read live via ToolGateway (Phase 5's existing build_context_bundle) -
a checkpoint's recorded file hashes are only ever used to DETECT
staleness, never trusted as current content. A stale or corrupted
checkpoint degrades reconstruction (surfaced via `stale`/`stale_reasons`,
or by falling back to an earlier valid checkpoint / no checkpoint at
all) - it never blocks resume and never masquerades as current truth.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Optional

from ..context.bundle_builder import build_context_bundle
from ..context.limits import DEFAULT_LIMITS, ContextLimits, estimate_tokens
from ..security.enums import OperatingMode, Role, SessionMode
from .records import ReconstructedContext
from .session_store import SessionNotFoundError

_ROLE_FOR_MODE = {
    OperatingMode.CHAT: Role.PLANNER,
    OperatingMode.PLAN: Role.PLANNER,
    OperatingMode.REVIEW: Role.REVIEWER,
    OperatingMode.CODE: Role.CODER,
    OperatingMode.EDIT: Role.CODER,
}


def role_for_operating_mode(operating_mode: OperatingMode) -> Role:
    return _ROLE_FOR_MODE[operating_mode]


def _trim_to_budget(recent: tuple, budget: int) -> tuple:
    kept = list(recent)
    dropped = []
    while kept and estimate_tokens("\n".join(m.content for m in kept)) > budget:
        dropped.append(kept.pop(0))
    return tuple(kept), tuple(dropped)


def reconstruct_for_resume(session_id: str, *, session_store, checkpoint_store, message_store, spec_store,
                            gateway, project_root: Path, recent_message_window: int,
                            max_conversation_tokens_estimate: int,
                            checkpoint_max_age_seconds: Optional[float] = None,
                            context_limits: ContextLimits = DEFAULT_LIMITS) -> ReconstructedContext:
    row = session_store.get(session_id)
    if row is None:
        raise SessionNotFoundError(session_id)

    operating_mode = OperatingMode(row.operating_mode)
    session_mode = SessionMode(row.session_mode)
    role = role_for_operating_mode(operating_mode)

    checkpoint = checkpoint_store.load_latest_valid(session_id)

    spec_version = None
    if row.spec_id is not None:
        try:
            spec_version = spec_store.latest(row.spec_id)
        except KeyError:
            spec_version = None

    stale_reasons: list = []
    if checkpoint is not None:
        if spec_version is not None and checkpoint.spec_version_label != spec_version.version_label:
            stale_reasons.append("spec advanced since checkpoint")
        for path, recorded_hash in checkpoint.changed_file_hashes.items():
            obs = gateway.invoke(role=role, tool_name="filesystem.read", arguments={"path": path},
                                  session_mode=session_mode, project_root=project_root,
                                  operating_mode=operating_mode)
            live_hash = (hashlib.sha256(obs.result["content"].encode("utf-8")).hexdigest()
                         if obs.status == "ok" else None)
            if live_hash != recorded_hash:
                stale_reasons.append(f"file changed since checkpoint: {path}")
        if checkpoint_max_age_seconds is not None and (time.time() - checkpoint.created_at) > checkpoint_max_age_seconds:
            stale_reasons.append("checkpoint too old")

    since_seq = checkpoint.covers_through_seq if checkpoint is not None else 0
    recent = message_store.recent(session_id, window=recent_message_window, since_seq=since_seq)

    hints = ()
    if spec_version is not None:
        hints = hints + tuple(spec_version.goals) + tuple(spec_version.constraints)
    if checkpoint is not None:
        hints = hints + checkpoint.changed_files

    project_bundle = build_context_bundle(gateway=gateway, role=role, session_mode=session_mode,
                                           project_root=project_root, reference_hints=hints,
                                           limits=context_limits, operating_mode=operating_mode)

    recent, dropped = _trim_to_budget(recent, max_conversation_tokens_estimate)

    return ReconstructedContext(
        operating_mode=operating_mode.value, session_mode=session_mode.value, spec_id=row.spec_id,
        spec_version=spec_version, checkpoint=checkpoint, stale=bool(stale_reasons),
        stale_reasons=tuple(stale_reasons), recent_messages=recent, project_bundle=project_bundle,
        messages_dropped_for_budget=dropped,
    )
