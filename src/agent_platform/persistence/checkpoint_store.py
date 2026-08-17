"""Append checkpoint rows + their Markdown mirror, and load them back
with corrupted-latest recovery. Every checkpoint file path is built
exclusively from `checkpoints_relative_dir` (a fixed trusted-config
value) and a backend-minted `(session_id, seq)` pair - never from spec_id
or any model/checkpoint-content string - and is authorized through
FilesystemSandbox.authorize() before every write or read, exactly like
orchestrator/plan_artifacts.py already does for plan files. The Markdown
file is read back only to verify its SHA-256 hash against the DB row;
its content is never parsed as structured data (see checkpoint_schema.py).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Optional

from ..security.sandbox import FilesystemSandbox
from .checkpoint_schema import render_checkpoint_markdown
from .db import PersistedStateCorruptionError, PersistencePathError, connect, safe_json_loads
from .records import CheckpointRecord


def _summary_to_json(checkpoint: CheckpointRecord) -> str:
    return json.dumps({
        "objective": checkpoint.objective,
        "completed_work": list(checkpoint.completed_work),
        "current_problem": checkpoint.current_problem,
        "relevant_decisions": list(checkpoint.relevant_decisions),
        "next_action": checkpoint.next_action,
        "constraints": list(checkpoint.constraints),
        "context_references": list(checkpoint.context_references),
    })


def _row_to_record(row: sqlite3.Row) -> CheckpointRecord:
    try:
        summary = safe_json_loads(row["summary"], context=f"checkpoints.summary (id={row['id']})")
        validation_result = safe_json_loads(
            row["validation_result_json"], context=f"checkpoints.validation_result_json (id={row['id']})",
        ) if row["validation_result_json"] else {"passed": None, "details": []}
        reviewer_feedback = safe_json_loads(
            row["reviewer_feedback_json"], context=f"checkpoints.reviewer_feedback_json (id={row['id']})")
        changed_file_hashes = safe_json_loads(
            row["changed_files_json"], context=f"checkpoints.changed_files_json (id={row['id']})")
        return CheckpointRecord(
            id=row["id"], session_id=row["session_id"], seq=row["seq"],
            covers_through_seq=row["covers_through_seq"], spec_id=row["spec_id"],
            spec_version_label=row["spec_version_label"], plan_snapshot_id=row["plan_snapshot_id"],
            operating_mode=row["operating_mode"], objective=summary["objective"],
            completed_work=tuple(summary["completed_work"]), current_problem=summary["current_problem"],
            relevant_decisions=tuple(summary["relevant_decisions"]),
            reviewer_feedback=tuple(reviewer_feedback),
            validation_passed=validation_result["passed"], validation_details=tuple(validation_result["details"]),
            changed_file_hashes=changed_file_hashes,
            next_action=summary["next_action"], constraints=tuple(summary["constraints"]),
            context_references=tuple(summary["context_references"]), reason=row["reason"],
            content_hash=row["content_hash"], markdown_path=row["markdown_path"],
            token_estimate=row["token_estimate"], created_at=row["created_at"],
        )
    except (KeyError, TypeError) as exc:
        raise PersistedStateCorruptionError(f"checkpoints row (id={row['id']}) failed to decode: {exc}") from exc


class CheckpointStore:
    def __init__(self, db_path: Path, *, sandbox: FilesystemSandbox, project_root: Path,
                 checkpoints_relative_dir: str):
        self._db_path = db_path
        self._sandbox = sandbox
        self._project_root = project_root
        self._checkpoints_relative_dir = checkpoints_relative_dir

    def append(self, checkpoint: CheckpointRecord, *, token_estimate: int,
               created_at: Optional[float] = None) -> CheckpointRecord:
        with closing(connect(self._db_path)) as conn:
            next_seq = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM checkpoints WHERE session_id = ?",
                (checkpoint.session_id,),
            ).fetchone()[0]

            markdown = render_checkpoint_markdown(checkpoint)
            content_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
            filename = f"{next_seq:04d}-{checkpoint.session_id}.md"
            relative_path = f"{self._checkpoints_relative_dir}/{filename}"
            decision = self._sandbox.authorize(relative_path, scope_root=self._project_root)
            if not decision.allowed:
                raise PersistencePathError(f"cannot resolve checkpoint file path: {decision.reason}")
            decision.resolved_path.parent.mkdir(parents=True, exist_ok=True)
            decision.resolved_path.write_text(markdown, encoding="utf-8")

            resolved_created_at = time.time() if created_at is None else created_at
            validation_result_json = json.dumps({
                "passed": checkpoint.validation_passed, "details": list(checkpoint.validation_details),
            })
            cur = conn.execute(
                "INSERT INTO checkpoints (session_id, seq, covers_through_seq, spec_id, spec_version_label, "
                "plan_snapshot_id, operating_mode, summary, changed_files_json, reviewer_feedback_json, "
                "validation_result_json, reason, content_hash, markdown_path, token_estimate, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (checkpoint.session_id, next_seq, checkpoint.covers_through_seq, checkpoint.spec_id,
                 checkpoint.spec_version_label, checkpoint.plan_snapshot_id, checkpoint.operating_mode,
                 _summary_to_json(checkpoint), json.dumps(checkpoint.changed_file_hashes),
                 json.dumps(list(checkpoint.reviewer_feedback)), validation_result_json, checkpoint.reason,
                 content_hash, relative_path, token_estimate, resolved_created_at),
            )
            row_id = cur.lastrowid
            conn.commit()

        return CheckpointRecord(
            id=row_id, session_id=checkpoint.session_id, seq=next_seq,
            covers_through_seq=checkpoint.covers_through_seq, spec_id=checkpoint.spec_id,
            spec_version_label=checkpoint.spec_version_label, plan_snapshot_id=checkpoint.plan_snapshot_id,
            operating_mode=checkpoint.operating_mode, objective=checkpoint.objective,
            completed_work=checkpoint.completed_work, current_problem=checkpoint.current_problem,
            relevant_decisions=checkpoint.relevant_decisions, reviewer_feedback=checkpoint.reviewer_feedback,
            validation_passed=checkpoint.validation_passed, validation_details=checkpoint.validation_details,
            changed_file_hashes=checkpoint.changed_file_hashes, next_action=checkpoint.next_action,
            constraints=checkpoint.constraints, context_references=checkpoint.context_references,
            reason=checkpoint.reason, content_hash=content_hash, markdown_path=relative_path,
            token_estimate=token_estimate, created_at=resolved_created_at,
        )

    def list_desc(self, session_id: str) -> tuple:
        with closing(connect(self._db_path)) as conn:
            rows = conn.execute(
                "SELECT * FROM checkpoints WHERE session_id = ? ORDER BY seq DESC", (session_id,),
            ).fetchall()
        return tuple(_row_to_record(r) for r in rows)

    def latest(self, session_id: str) -> Optional[CheckpointRecord]:
        listed = self.list_desc(session_id)
        return listed[0] if listed else None

    def _verify(self, record: CheckpointRecord) -> bool:
        decision = self._sandbox.authorize(record.markdown_path, scope_root=self._project_root)
        if not decision.allowed or not decision.resolved_path.is_file():
            return False
        on_disk = decision.resolved_path.read_text(encoding="utf-8")
        return hashlib.sha256(on_disk.encode("utf-8")).hexdigest() == record.content_hash

    def load_latest_valid(self, session_id: str) -> Optional[CheckpointRecord]:
        for record in self.list_desc(session_id):
            if self._verify(record):
                return record
        return None
