"""Frozen, explicit dataclasses for every persisted entity plus the
reconstruction result. No raw sqlite3.Row and no arbitrary object ever
leaves a *_store.py module - every field here is a plain, typed value
(str/int/float/bool/tuple/frozenset of the same), matching the same
explicit-schema discipline api_serialization.py already uses for the HTTP
layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    operating_mode: str
    session_mode: str
    spec_id: Optional[str]
    status: str
    active_spec_version: Optional[int]
    active_plan_id: Optional[int]
    current_checkpoint_id: Optional[int]
    fix_iteration_count: int
    clarification_round_count: int
    created_at: float
    updated_at: float
    archived_at: Optional[float]


@dataclass(frozen=True)
class MessageRecord:
    session_id: str
    seq: int
    speaker: str  # "user" | "assistant"
    content: str
    created_at: float
    id: Optional[int] = None


@dataclass(frozen=True)
class DecisionRecord:
    session_id: str
    seq: int
    event_type: str
    payload: dict
    created_at: float
    id: Optional[int] = None


@dataclass(frozen=True)
class SpecVersionRecord:
    spec_id: str
    version: int
    goals: tuple
    constraints: tuple
    acceptance_criteria: tuple
    created_at: float


@dataclass(frozen=True)
class PlanSnapshotRecord:
    session_id: str
    spec_id: str
    version: int
    status: str  # DRAFT | REVISED | APPROVED | REJECTED
    path: str
    spec_version_label: str
    finalized_paths: tuple
    plan: dict  # explicit StructuredPlan field mapping, see plan_snapshot_store.py
    created_at: float
    id: Optional[int] = None


@dataclass(frozen=True)
class CheckpointRecord:
    """Doubles as both the not-yet-persisted checkpoint content (id=None,
    content_hash/markdown_path/token_estimate not yet computed) and the
    record read back from a DB row + verified Markdown mirror. Every field
    is DERIVED CONTEXT (see persistence/service.py's module docstring) -
    none of it can change permissions, the active spec, or operating mode
    on its own; reconstruction.py only ever reads it as inert data."""
    session_id: str
    seq: int
    spec_id: Optional[str]
    spec_version_label: Optional[str]
    plan_snapshot_id: Optional[int]
    operating_mode: str  # denormalized cross-check ONLY, never authoritative on resume
    objective: str
    completed_work: tuple
    current_problem: str
    relevant_decisions: tuple
    reviewer_feedback: tuple
    validation_passed: Optional[bool]
    validation_details: tuple
    changed_file_hashes: dict  # {path: sha256_hex} - never file content
    next_action: str
    constraints: tuple
    context_references: tuple
    reason: str  # compaction_threshold | plan_approved | plan_rejected | terminal_state | archive
    covers_through_seq: int = 0  # message_store.seq this checkpoint accounts for; NOT the same as `seq` above
    content_hash: str = ""
    markdown_path: str = ""
    token_estimate: int = 0
    created_at: float = 0.0
    id: Optional[int] = None

    @property
    def changed_files(self) -> tuple:
        return tuple(self.changed_file_hashes.keys())


@dataclass(frozen=True)
class ToolObservationRecord:
    session_id: str
    seq: int
    tool_name: str
    status: str
    summary: dict
    created_at: float
    id: Optional[int] = None


@dataclass(frozen=True)
class ReconstructedContext:
    operating_mode: str
    session_mode: str
    spec_id: Optional[str]
    spec_version: object  # SpecVersion | None, left untyped to avoid a spec-module import cycle
    checkpoint: Optional[CheckpointRecord]
    stale: bool
    stale_reasons: tuple
    recent_messages: tuple
    project_bundle: object  # ContextBundle | None
    messages_dropped_for_budget: tuple = field(default_factory=tuple)
