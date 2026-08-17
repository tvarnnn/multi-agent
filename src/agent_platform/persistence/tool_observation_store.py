"""Bounded, redacted persistence of ToolObservation summaries. A strict
key allowlist - never a denylist - decides what survives into the
summary: only `path` from the call arguments, and a handful of known-safe
scalar result keys. `content`/`entries`/`written`/`created` and every
other result field that could carry file content or secrets is simply
never read, let alone stored. Retention is a hard cap per session, oldest
rows pruned first, so this table can never grow unbounded.
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Optional

from .db import connect
from .records import ToolObservationRecord

_SAFE_ARGUMENT_KEYS = frozenset({"path"})
_SAFE_RESULT_KEYS = frozenset({"passed", "exit_code", "timed_out", "scoped"})

DEFAULT_RETENTION = 200


def build_observation_summary(arguments: dict, result: Optional[dict]) -> dict:
    summary = {k: v for k, v in (arguments or {}).items() if k in _SAFE_ARGUMENT_KEYS}
    if result:
        summary.update({k: v for k, v in result.items() if k in _SAFE_RESULT_KEYS})
    return summary


def _row_to_record(row: sqlite3.Row) -> ToolObservationRecord:
    return ToolObservationRecord(id=row["id"], session_id=row["session_id"], seq=row["seq"],
                                  tool_name=row["tool_name"], status=row["status"],
                                  summary=json.loads(row["summary"]), created_at=row["created_at"])


class ToolObservationStore:
    def __init__(self, db_path: Path, retention: int = DEFAULT_RETENTION):
        self._db_path = db_path
        self._retention = retention

    def append(self, *, session_id: str, tool_name: str, status: str, arguments: Optional[dict] = None,
               result: Optional[dict] = None, created_at: Optional[float] = None) -> ToolObservationRecord:
        summary = build_observation_summary(arguments or {}, result)
        created_at = time.time() if created_at is None else created_at
        with closing(connect(self._db_path)) as conn:
            next_seq = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM tool_observations WHERE session_id = ?", (session_id,),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO tool_observations (session_id, seq, tool_name, status, summary, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, next_seq, tool_name, status, json.dumps(summary), created_at),
            )
            conn.execute(
                "DELETE FROM tool_observations WHERE session_id = ? AND seq <= ?",
                (session_id, next_seq - self._retention),
            )
            conn.commit()
        return ToolObservationRecord(session_id=session_id, seq=next_seq, tool_name=tool_name,
                                      status=status, summary=summary, created_at=created_at)

    def recent(self, session_id: str, limit: Optional[int] = None) -> tuple:
        with closing(connect(self._db_path)) as conn:
            if limit is None:
                rows = conn.execute(
                    "SELECT * FROM tool_observations WHERE session_id = ? ORDER BY seq", (session_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM (SELECT * FROM tool_observations WHERE session_id = ? "
                    "ORDER BY seq DESC LIMIT ?) ORDER BY seq",
                    (session_id, limit),
                ).fetchall()
        return tuple(_row_to_record(r) for r in rows)
