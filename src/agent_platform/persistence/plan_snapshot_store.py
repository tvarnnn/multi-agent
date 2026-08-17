"""Append-only history of StructuredPlan drafts/revisions/approvals per
(session_id, spec_id) - the explicit JSON field mapping needed because
Orchestrator._plan_sessions is in-memory only. The plan's Markdown
artifact stays non-authoritative exactly as Phase 9 designed it (never
re-read as input to any decision); this module persists the structured
StructuredPlan object itself, mirroring api_serialization.py's
field-by-field discipline rather than any implicit serialization.
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Optional

from ..orchestrator.plan_schemas import StructuredPlan
from .db import PersistedStateCorruptionError, connect, safe_json_loads
from .records import PlanSnapshotRecord


def _plan_to_dict(plan: StructuredPlan) -> dict:
    return {
        "objective": plan.objective,
        "requirements": list(plan.requirements),
        "existing_context": list(plan.existing_context),
        "proposed_architecture": plan.proposed_architecture,
        "files_to_create": list(plan.files_to_create),
        "files_to_modify": list(plan.files_to_modify),
        "dependencies": list(plan.dependencies),
        "implementation_steps": list(plan.implementation_steps),
        "validation_strategy": list(plan.validation_strategy),
        "risks": list(plan.risks),
        "unknowns": list(plan.unknowns),
        "acceptance_criteria": list(plan.acceptance_criteria),
        "reviewer_feedback": list(plan.reviewer_feedback),
        "target_spec_version_label": plan.target_spec_version_label,
    }


def _plan_from_dict(d: dict) -> StructuredPlan:
    return StructuredPlan(
        objective=d["objective"], requirements=tuple(d["requirements"]),
        existing_context=tuple(d["existing_context"]), proposed_architecture=d["proposed_architecture"],
        files_to_create=tuple(d["files_to_create"]), files_to_modify=tuple(d["files_to_modify"]),
        dependencies=tuple(d["dependencies"]), implementation_steps=tuple(d["implementation_steps"]),
        validation_strategy=tuple(d["validation_strategy"]), risks=tuple(d["risks"]),
        unknowns=tuple(d["unknowns"]), acceptance_criteria=tuple(d["acceptance_criteria"]),
        reviewer_feedback=tuple(d["reviewer_feedback"]),
        target_spec_version_label=d["target_spec_version_label"],
    )


def _row_to_record(row: sqlite3.Row) -> PlanSnapshotRecord:
    try:
        finalized_paths = safe_json_loads(row["finalized_paths_json"],
                                           context=f"plan_snapshots.finalized_paths_json (id={row['id']})")
        plan_dict = safe_json_loads(row["plan_json"], context=f"plan_snapshots.plan_json (id={row['id']})")
        plan = _plan_from_dict(plan_dict)
    except (KeyError, TypeError) as exc:
        raise PersistedStateCorruptionError(
            f"plan_snapshots row (id={row['id']}) failed to decode: {exc}") from exc
    return PlanSnapshotRecord(
        id=row["id"], session_id=row["session_id"], spec_id=row["spec_id"], version=row["version"],
        status=row["status"], path=row["path"], spec_version_label=row["spec_version_label"],
        finalized_paths=tuple(finalized_paths), plan=plan, created_at=row["created_at"],
    )


class PlanSnapshotStore:
    def __init__(self, db_path: Path):
        self._db_path = db_path

    def append(self, *, session_id: str, spec_id: str, version: int, status: str, path: str,
               spec_version_label: str, finalized_paths: tuple, plan: StructuredPlan,
               created_at: Optional[float] = None) -> PlanSnapshotRecord:
        created_at = time.time() if created_at is None else created_at
        with closing(connect(self._db_path)) as conn:
            cur = conn.execute(
                "INSERT INTO plan_snapshots (session_id, spec_id, version, status, path, "
                "spec_version_label, finalized_paths_json, plan_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, spec_id, version, status, path, spec_version_label,
                 json.dumps(list(finalized_paths)), json.dumps(_plan_to_dict(plan)), created_at),
            )
            row_id = cur.lastrowid
            conn.commit()
        return PlanSnapshotRecord(id=row_id, session_id=session_id, spec_id=spec_id, version=version,
                                   status=status, path=path, spec_version_label=spec_version_label,
                                   finalized_paths=tuple(finalized_paths), plan=plan, created_at=created_at)

    def latest(self, session_id: str, spec_id: str) -> Optional[PlanSnapshotRecord]:
        with closing(connect(self._db_path)) as conn:
            row = conn.execute(
                "SELECT * FROM plan_snapshots WHERE session_id = ? AND spec_id = ? ORDER BY id DESC LIMIT 1",
                (session_id, spec_id),
            ).fetchone()
        return _row_to_record(row) if row is not None else None

    def list_for_session_spec(self, session_id: str, spec_id: str) -> tuple:
        with closing(connect(self._db_path)) as conn:
            rows = conn.execute(
                "SELECT * FROM plan_snapshots WHERE session_id = ? AND spec_id = ? ORDER BY id",
                (session_id, spec_id),
            ).fetchall()
        return tuple(_row_to_record(r) for r in rows)
