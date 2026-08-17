"""SessionPersistenceService: the single facade backend_api.py talks to.
Every method here either delegates to one of the *_store modules or wires
together the pure decision functions in compaction.py/reconstruction.py -
this module has no SQL of its own and no filesystem-security logic of its
own; those all stay in db.py/checkpoint_store.py.

Every CheckpointRecord this module builds is DERIVED CONTEXT (see
records.CheckpointRecord's docstring): it can never change permissions,
the active spec, or operating mode. Authoritative state after a restart
is SpecStore (rehydrated once at startup via rehydrate_spec_store) and
each session's persisted operating_mode/session_mode columns - never
anything reconstructed from a checkpoint.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

from ..context.limits import estimate_tokens
from ..security.enums import OperatingMode, Role, SessionMode
from ..tools.gateway import ToolGateway
from .checkpoint_schema import render_checkpoint_markdown
from .checkpoint_store import CheckpointStore
from .compaction import maybe_compact as _maybe_compact
from .decision_store import DecisionStore
from .message_store import MessageStore
from .plan_snapshot_store import PlanSnapshotStore
from .reconstruction import reconstruct_for_resume, role_for_operating_mode
from .records import CheckpointRecord, DecisionRecord, MessageRecord, PlanSnapshotRecord, SessionRecord
from .session_store import SessionStore
from .spec_version_store import SpecVersionStore, rehydrate_spec_store
from .tool_observation_store import DEFAULT_RETENTION, ToolObservationStore


class SessionPersistenceService:
    def __init__(self, *, db_path: Path, sandbox, project_root: Path, checkpoints_relative_dir: str,
                 gateway: ToolGateway, spec_store, compaction_enabled: bool = True,
                 compaction_threshold_percent: int = 85, max_conversation_tokens_estimate: int = 20_000,
                 recent_message_window: int = 20, checkpoint_max_age_seconds: Optional[float] = None,
                 tool_observation_retention: int = DEFAULT_RETENTION):
        self._session_store = SessionStore(db_path)
        self._message_store = MessageStore(db_path)
        self._decision_store = DecisionStore(db_path)
        self._spec_version_store = SpecVersionStore(db_path)
        self._plan_snapshot_store = PlanSnapshotStore(db_path)
        self._checkpoint_store = CheckpointStore(db_path, sandbox=sandbox, project_root=project_root,
                                                  checkpoints_relative_dir=checkpoints_relative_dir)
        self._tool_observation_store = ToolObservationStore(db_path, retention=tool_observation_retention)
        self._gateway = gateway
        self._spec_store = spec_store
        self._project_root = project_root
        self._compaction_enabled = compaction_enabled
        self._compaction_threshold_percent = compaction_threshold_percent
        self._max_conversation_tokens_estimate = max_conversation_tokens_estimate
        self._recent_message_window = recent_message_window
        self._checkpoint_max_age_seconds = checkpoint_max_age_seconds

    def rehydrate(self) -> None:
        """Replays every persisted SpecVersion into self._spec_store via its
        existing public .create() API. Must be called once at backend
        startup, before any session is created - see server.py. Raises
        SpecRehydrationError (fail loud, per the confirmed decision) if the
        persisted sequence is corrupted."""
        rehydrate_spec_store(self._spec_store, self._spec_version_store.list_all())

    # ------------------------------------------------------------ sessions

    def create_session(self, session_id: str, *, operating_mode: str, session_mode: str,
                        spec_id: Optional[str]) -> SessionRecord:
        return self._session_store.create(session_id=session_id, operating_mode=operating_mode,
                                           session_mode=session_mode, spec_id=spec_id)

    def get_session(self, session_id: str) -> Optional[SessionRecord]:
        return self._session_store.get(session_id)

    def list_sessions(self, statuses: Optional[tuple] = None) -> tuple:
        return self._session_store.list(statuses=statuses)

    def set_active_spec_version(self, session_id: str, version: int) -> None:
        self._session_store.set_active_spec_version(session_id, version)

    # ------------------------------------------------------------ messages

    def record_message(self, session_id: str, *, speaker: str, content: str) -> MessageRecord:
        record = self._message_store.append(session_id=session_id, speaker=speaker, content=content)
        self._session_store.touch(session_id)
        return record

    def get_history(self, session_id: str, *, before_seq: Optional[int] = None, limit: int = 50) -> tuple:
        return self._message_store.list_page(session_id, before_seq=before_seq, limit=limit)

    # ----------------------------------------------------------- decisions

    def record_decision(self, session_id: str, *, event_type: str, payload: dict) -> DecisionRecord:
        return self._decision_store.append(session_id=session_id, event_type=event_type, payload=payload)

    def get_decisions(self, session_id: str) -> tuple:
        return self._decision_store.since(session_id)

    # -------------------------------------------------------- spec versions

    def record_spec_version(self, spec_version) -> None:
        """spec_version is a spec.versioning.SpecVersion - call this every
        time SpecStore.create() produces one, so rehydrate() can replay it
        after a restart."""
        self._spec_version_store.append(
            spec_id=spec_version.spec_id, version=spec_version.version, goals=spec_version.goals,
            constraints=spec_version.constraints, acceptance_criteria=spec_version.acceptance_criteria,
            created_at=spec_version.created_at,
        )

    # -------------------------------------------------------- plan snapshots

    def record_plan_snapshot(self, session_id: str, *, spec_id: str, version: int, status: str, path: str,
                              spec_version_label: str, finalized_paths: tuple, plan) -> PlanSnapshotRecord:
        record = self._plan_snapshot_store.append(
            session_id=session_id, spec_id=spec_id, version=version, status=status, path=path,
            spec_version_label=spec_version_label, finalized_paths=finalized_paths, plan=plan,
        )
        self._session_store.set_active_plan_id(session_id, record.id)
        return record

    def latest_plan_snapshot(self, session_id: str, spec_id: str) -> Optional[PlanSnapshotRecord]:
        return self._plan_snapshot_store.latest(session_id, spec_id)

    # ------------------------------------------------------ tool observations

    def record_tool_observation(self, session_id: str, *, tool_name: str, status: str,
                                 arguments: Optional[dict] = None, result: Optional[dict] = None):
        return self._tool_observation_store.append(session_id=session_id, tool_name=tool_name, status=status,
                                                     arguments=arguments, result=result)

    # -------------------------------------------------------------- checkpoints

    def _hash_changed_files(self, changed_files: tuple, *, role: Role, session_mode: SessionMode,
                             operating_mode: OperatingMode) -> dict:
        hashes = {}
        for path in changed_files:
            obs = self._gateway.invoke(role=role, tool_name="filesystem.read", arguments={"path": path},
                                        session_mode=session_mode, project_root=self._project_root,
                                        operating_mode=operating_mode)
            if obs.status == "ok":
                hashes[path] = hashlib.sha256(obs.result["content"].encode("utf-8")).hexdigest()
        return hashes

    def record_checkpoint(self, session_id: str, *, reason: str, operating_mode: str,
                           session_mode: Optional[str] = None, spec_id: Optional[str] = None,
                           spec_version_label: Optional[str] = None, plan_snapshot_id: Optional[int] = None,
                           objective: str = "", completed_work: tuple = (), current_problem: str = "",
                           relevant_decisions: tuple = (), reviewer_feedback: tuple = (),
                           validation_passed: Optional[bool] = None, validation_details: tuple = (),
                           changed_files: tuple = (), next_action: str = "", constraints: tuple = (),
                           context_references: tuple = ()) -> CheckpointRecord:
        changed_file_hashes = {}
        if changed_files:
            role = role_for_operating_mode(OperatingMode(operating_mode))
            resolved_session_mode = SessionMode(session_mode) if session_mode else SessionMode.AUTO
            changed_file_hashes = self._hash_changed_files(
                tuple(changed_files), role=role, session_mode=resolved_session_mode,
                operating_mode=OperatingMode(operating_mode),
            )

        latest = self._message_store.recent(session_id, window=1)
        covers_through_seq = latest[-1].seq if latest else 0

        content = CheckpointRecord(
            session_id=session_id, seq=0, covers_through_seq=covers_through_seq, spec_id=spec_id,
            spec_version_label=spec_version_label, plan_snapshot_id=plan_snapshot_id,
            operating_mode=operating_mode, objective=objective, completed_work=tuple(completed_work),
            current_problem=current_problem, relevant_decisions=tuple(relevant_decisions),
            reviewer_feedback=tuple(reviewer_feedback), validation_passed=validation_passed,
            validation_details=tuple(validation_details), changed_file_hashes=changed_file_hashes,
            next_action=next_action, constraints=tuple(constraints),
            context_references=tuple(context_references), reason=reason,
        )
        token_estimate = estimate_tokens(render_checkpoint_markdown(content))
        appended = self._checkpoint_store.append(content, token_estimate=token_estimate)
        self._session_store.set_current_checkpoint(session_id, appended.id)
        return appended

    def _build_minimal_checkpoint(self, session_id: str, *, reason: str) -> CheckpointRecord:
        """Best-effort automatic checkpoint content for threshold-triggered
        compaction, where no caller-supplied narrative is available. No
        live file hashing is attempted here - only explicit
        record_checkpoint() calls (forced milestones, where the caller
        knows which files actually changed) hash files."""
        row = self._session_store.get(session_id)
        recent = self._message_store.recent(session_id, window=5)
        next_action = "; ".join(m.content[:200] for m in recent) or "(no recent activity recorded)"
        objective, spec_version_label = "(auto-compacted checkpoint)", None
        if row.spec_id is not None:
            try:
                latest_spec = self._spec_store.latest(row.spec_id)
                objective = "; ".join(latest_spec.goals) or objective
                spec_version_label = latest_spec.version_label
            except KeyError:
                pass
        latest_msg = self._message_store.recent(session_id, window=1)
        covers_through_seq = latest_msg[-1].seq if latest_msg else 0
        return CheckpointRecord(
            session_id=session_id, seq=0, covers_through_seq=covers_through_seq, spec_id=row.spec_id,
            spec_version_label=spec_version_label, plan_snapshot_id=row.active_plan_id,
            operating_mode=row.operating_mode, objective=objective, completed_work=(), current_problem="",
            relevant_decisions=(), reviewer_feedback=(), validation_passed=None, validation_details=(),
            changed_file_hashes={}, next_action=next_action, constraints=(), context_references=(),
            reason=reason,
        )

    def maybe_compact(self, session_id: str) -> Optional[CheckpointRecord]:
        checkpoint = _maybe_compact(
            session_id=session_id, message_store=self._message_store, checkpoint_store=self._checkpoint_store,
            session_store=self._session_store,
            build_checkpoint=lambda reason: self._build_minimal_checkpoint(session_id, reason=reason),
            enabled=self._compaction_enabled, budget=self._max_conversation_tokens_estimate,
            threshold_percent=self._compaction_threshold_percent,
        )
        return checkpoint

    def force_checkpoint(self, session_id: str, *, reason: str) -> CheckpointRecord:
        return _maybe_compact(
            session_id=session_id, message_store=self._message_store, checkpoint_store=self._checkpoint_store,
            session_store=self._session_store,
            build_checkpoint=lambda r: self._build_minimal_checkpoint(session_id, reason=r),
            enabled=self._compaction_enabled, budget=self._max_conversation_tokens_estimate,
            threshold_percent=self._compaction_threshold_percent, reason_if_forced=reason,
        )

    def get_checkpoints(self, session_id: str) -> tuple:
        return self._checkpoint_store.list_desc(session_id)

    def get_checkpoint(self, session_id: str, checkpoint_id: int) -> Optional[CheckpointRecord]:
        for record in self._checkpoint_store.list_desc(session_id):
            if record.id == checkpoint_id:
                return record
        return None

    # ------------------------------------------------------------- resume

    def resume(self, session_id: str):
        return reconstruct_for_resume(
            session_id=session_id, session_store=self._session_store, checkpoint_store=self._checkpoint_store,
            message_store=self._message_store, spec_store=self._spec_store, gateway=self._gateway,
            project_root=self._project_root, recent_message_window=self._recent_message_window,
            max_conversation_tokens_estimate=self._max_conversation_tokens_estimate,
            checkpoint_max_age_seconds=self._checkpoint_max_age_seconds,
        )

    def archive_session(self, session_id: str) -> CheckpointRecord:
        checkpoint = self.force_checkpoint(session_id, reason="archive")
        self._session_store.archive(session_id)
        return checkpoint
