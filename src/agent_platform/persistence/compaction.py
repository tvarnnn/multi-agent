"""Percent-of-budget compaction threshold math, plus forced-milestone
triggers. Never deletes/truncates messages/decisions - the database stays
the complete history (never treat the context window as the database);
compaction only ever adds a checkpoint that later reconstruction can use
instead of full history. Token estimation reuses
context/limits.py's existing estimate_tokens - never reinvented, never a
hardcoded token number.
"""
from __future__ import annotations

from typing import Callable, Optional

from ..context.limits import estimate_tokens
from .records import CheckpointRecord

FORCED_REASONS = frozenset({"plan_approved", "plan_rejected", "terminal_state", "archive"})


def should_compact(*, message_store, checkpoint_store, session_id: str, enabled: bool,
                    budget: int, threshold_percent: int) -> bool:
    if not enabled:
        return False
    last_checkpoint = checkpoint_store.latest(session_id)
    since_seq = last_checkpoint.covers_through_seq if last_checkpoint is not None else 0
    unchecked = message_store.since(session_id, since_seq=since_seq)
    estimated = estimate_tokens("\n".join(m.content for m in unchecked)) if unchecked else 0
    threshold = budget * threshold_percent / 100
    return estimated >= threshold


def maybe_compact(*, session_id: str, message_store, checkpoint_store, session_store,
                   build_checkpoint: Callable[[str], CheckpointRecord], enabled: bool, budget: int,
                   threshold_percent: int, reason_if_forced: Optional[str] = None) -> Optional[CheckpointRecord]:
    if reason_if_forced is not None:
        if reason_if_forced not in FORCED_REASONS:
            raise ValueError(f"unknown forced compaction reason: {reason_if_forced!r}")
        reason = reason_if_forced
    else:
        if not should_compact(message_store=message_store, checkpoint_store=checkpoint_store,
                               session_id=session_id, enabled=enabled, budget=budget,
                               threshold_percent=threshold_percent):
            return None
        reason = "compaction_threshold"

    checkpoint = build_checkpoint(reason)
    appended = checkpoint_store.append(checkpoint, token_estimate=checkpoint.token_estimate)
    session_store.set_current_checkpoint(session_id, appended.id)
    return appended
