"""Append-only mirror of every SpecVersion ever created, and the replay
function that rehydrates a fresh, in-memory SpecStore from it at backend
startup. SpecStore itself stays completely unmodified - rehydration only
ever calls its existing public `.create()` method, in the same order
those calls originally happened, so version numbering is derived the
same way it always was, never invented by this module.
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from .db import connect
from .records import SpecVersionRecord


class SpecRehydrationError(Exception):
    """Raised when persisted spec_versions rows can't be replayed safely -
    e.g. a missing version in the sequence for a spec_id. Per the
    confirmed fail-loud decision, this must stop backend startup rather
    than silently producing wrong version numbers."""


def _row_to_record(row: sqlite3.Row) -> SpecVersionRecord:
    return SpecVersionRecord(
        spec_id=row["spec_id"], version=row["version"],
        goals=tuple(json.loads(row["goals_json"])),
        constraints=tuple(json.loads(row["constraints_json"])),
        acceptance_criteria=tuple(json.loads(row["acceptance_criteria_json"])),
        created_at=row["created_at"],
    )


class SpecVersionStore:
    def __init__(self, db_path: Path):
        self._db_path = db_path

    def append(self, *, spec_id: str, version: int, goals: tuple, constraints: tuple,
               acceptance_criteria: tuple, created_at: float = None) -> SpecVersionRecord:
        created_at = time.time() if created_at is None else created_at
        with closing(connect(self._db_path)) as conn:
            conn.execute(
                "INSERT INTO spec_versions (spec_id, version, goals_json, constraints_json, "
                "acceptance_criteria_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (spec_id, version, json.dumps(list(goals)), json.dumps(list(constraints)),
                 json.dumps(list(acceptance_criteria)), created_at),
            )
            conn.commit()
        return SpecVersionRecord(spec_id=spec_id, version=version, goals=tuple(goals),
                                  constraints=tuple(constraints),
                                  acceptance_criteria=tuple(acceptance_criteria), created_at=created_at)

    def list_for_spec(self, spec_id: str) -> tuple:
        with closing(connect(self._db_path)) as conn:
            rows = conn.execute(
                "SELECT * FROM spec_versions WHERE spec_id = ? ORDER BY version", (spec_id,),
            ).fetchall()
        return tuple(_row_to_record(r) for r in rows)

    def list_all(self) -> tuple:
        with closing(connect(self._db_path)) as conn:
            rows = conn.execute("SELECT * FROM spec_versions ORDER BY spec_id, version").fetchall()
        return tuple(_row_to_record(r) for r in rows)


def rehydrate_spec_store(spec_store, records: tuple) -> None:
    by_spec: dict = {}
    for record in records:
        by_spec.setdefault(record.spec_id, []).append(record)

    for spec_id, versions in by_spec.items():
        versions = sorted(versions, key=lambda r: r.version)
        for expected_version, record in enumerate(versions, start=1):
            if record.version != expected_version:
                raise SpecRehydrationError(
                    f"gap or corruption in spec_versions for {spec_id!r}: "
                    f"expected version {expected_version}, found {record.version}"
                )
            created = spec_store.create(
                spec_id, goals=record.goals, constraints=record.constraints,
                acceptance_criteria=record.acceptance_criteria,
            )
            if created.version != record.version:
                raise SpecRehydrationError(
                    f"replay produced version {created.version} for {spec_id!r}, "
                    f"expected {record.version} - SpecStore state is inconsistent"
                )
