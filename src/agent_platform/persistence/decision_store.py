"""Append-only decision history: structured, itemized moments (plan
approved/rejected/revised, spec version created, ...) rather than raw
EventLog dumps. Every event_type has an explicit payload-key allowlist -
an unexpected key fails closed rather than being silently stored, so a
future internal event accidentally carrying more than intended can never
reach the database just by existing on some internal dict.
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Optional

from .db import PersistedStateCorruptionError, connect, safe_json_loads
from .records import DecisionRecord

PAYLOAD_ALLOWLIST: dict = {
    "PLAN_CREATED": frozenset({"spec_id", "path"}),
    "PLAN_REVISED": frozenset({"spec_id", "path"}),
    "PLAN_APPROVED": frozenset({"spec_id", "path"}),
    "PLAN_REJECTED": frozenset({"spec_id", "path", "reason"}),
    "PLAN_ARTIFACT_WRITTEN": frozenset({"spec_id", "path", "status"}),
    "PLAN_REVIEWED": frozenset({"spec_id"}),
    "SPEC_VERSION_CREATED": frozenset({"version_label"}),
}


class DecisionValidationError(Exception):
    pass


def _row_to_record(row: sqlite3.Row) -> DecisionRecord:
    payload = safe_json_loads(row["payload_json"], context=f"decisions.payload_json (id={row['id']})")
    if not isinstance(payload, dict):
        raise PersistedStateCorruptionError(f"decisions.payload_json (id={row['id']}) is not a JSON object")
    return DecisionRecord(id=row["id"], session_id=row["session_id"], seq=row["seq"],
                           event_type=row["event_type"], payload=payload, created_at=row["created_at"])


class DecisionStore:
    def __init__(self, db_path: Path):
        self._db_path = db_path

    def append(self, *, session_id: str, event_type: str, payload: dict,
               created_at: Optional[float] = None) -> DecisionRecord:
        allowed_keys = PAYLOAD_ALLOWLIST.get(event_type)
        if allowed_keys is None:
            raise DecisionValidationError(f"unknown decision event_type: {event_type!r}")
        extra_keys = set(payload.keys()) - allowed_keys
        if extra_keys:
            raise DecisionValidationError(
                f"payload for {event_type!r} has unallowlisted keys: {sorted(extra_keys)}"
            )
        try:
            payload_json = json.dumps(payload)
        except TypeError as exc:
            raise DecisionValidationError(f"payload for {event_type!r} is not JSON-serializable: {exc}") from exc

        created_at = time.time() if created_at is None else created_at
        with closing(connect(self._db_path)) as conn:
            next_seq = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM decisions WHERE session_id = ?", (session_id,),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO decisions (session_id, seq, event_type, payload_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, next_seq, event_type, payload_json, created_at),
            )
            conn.commit()
        return DecisionRecord(session_id=session_id, seq=next_seq, event_type=event_type,
                               payload=dict(payload), created_at=created_at)

    def since(self, session_id: str, since_seq: int = 0) -> tuple:
        with closing(connect(self._db_path)) as conn:
            rows = conn.execute(
                "SELECT * FROM decisions WHERE session_id = ? AND seq > ? ORDER BY seq",
                (session_id, since_seq),
            ).fetchall()
        return tuple(_row_to_record(r) for r in rows)
