"""CRUD for the `sessions` table - the one persistence table with real
UPDATEs, so route handlers get O(1) "current status" without scanning.
Every method opens a short-lived connection per call (contextlib.closing)
rather than holding one shared connection - simplest correct approach for
a local, single-user dev tool driven by FastAPI's sync-route threadpool.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Optional

from .db import connect
from .records import SessionRecord


class SessionNotFoundError(Exception):
    def __init__(self, session_id: str):
        super().__init__(f"no persisted session: {session_id!r}")
        self.session_id = session_id


def _row_to_record(row: sqlite3.Row) -> SessionRecord:
    return SessionRecord(
        session_id=row["session_id"], operating_mode=row["operating_mode"],
        session_mode=row["session_mode"], spec_id=row["spec_id"], status=row["status"],
        active_spec_version=row["active_spec_version"], active_plan_id=row["active_plan_id"],
        current_checkpoint_id=row["current_checkpoint_id"],
        fix_iteration_count=row["fix_iteration_count"],
        clarification_round_count=row["clarification_round_count"],
        created_at=row["created_at"], updated_at=row["updated_at"], archived_at=row["archived_at"],
    )


class SessionStore:
    def __init__(self, db_path: Path):
        self._db_path = db_path

    def create(self, *, session_id: str, operating_mode: str, session_mode: str,
               spec_id: Optional[str], status: str = "ACTIVE") -> SessionRecord:
        now = time.time()
        with closing(connect(self._db_path)) as conn:
            conn.execute(
                "INSERT INTO sessions (session_id, operating_mode, session_mode, spec_id, status, "
                "fix_iteration_count, clarification_round_count, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?)",
                (session_id, operating_mode, session_mode, spec_id, status, now, now),
            )
            conn.commit()
        return self.get(session_id)

    def get(self, session_id: str) -> Optional[SessionRecord]:
        with closing(connect(self._db_path)) as conn:
            row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        return _row_to_record(row) if row is not None else None

    def list(self, statuses: Optional[tuple] = None) -> tuple:
        with closing(connect(self._db_path)) as conn:
            if statuses is None:
                rows = conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC").fetchall()
            else:
                placeholders = ",".join("?" for _ in statuses)
                rows = conn.execute(
                    f"SELECT * FROM sessions WHERE status IN ({placeholders}) ORDER BY updated_at DESC",
                    tuple(statuses),
                ).fetchall()
        return tuple(_row_to_record(r) for r in rows)

    def _require_exists(self, conn: sqlite3.Connection, session_id: str) -> None:
        row = conn.execute("SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        if row is None:
            raise SessionNotFoundError(session_id)

    def touch(self, session_id: str) -> None:
        with closing(connect(self._db_path)) as conn:
            self._require_exists(conn, session_id)
            conn.execute("UPDATE sessions SET updated_at = ? WHERE session_id = ?", (time.time(), session_id))
            conn.commit()

    def set_status(self, session_id: str, status: str) -> None:
        with closing(connect(self._db_path)) as conn:
            self._require_exists(conn, session_id)
            conn.execute(
                "UPDATE sessions SET status = ?, updated_at = ? WHERE session_id = ?",
                (status, time.time(), session_id),
            )
            conn.commit()

    def set_active_spec_version(self, session_id: str, version: int) -> None:
        with closing(connect(self._db_path)) as conn:
            self._require_exists(conn, session_id)
            conn.execute(
                "UPDATE sessions SET active_spec_version = ?, updated_at = ? WHERE session_id = ?",
                (version, time.time(), session_id),
            )
            conn.commit()

    def set_active_plan_id(self, session_id: str, plan_id: int) -> None:
        with closing(connect(self._db_path)) as conn:
            self._require_exists(conn, session_id)
            conn.execute(
                "UPDATE sessions SET active_plan_id = ?, updated_at = ? WHERE session_id = ?",
                (plan_id, time.time(), session_id),
            )
            conn.commit()

    def set_current_checkpoint(self, session_id: str, checkpoint_id: int) -> None:
        with closing(connect(self._db_path)) as conn:
            self._require_exists(conn, session_id)
            conn.execute(
                "UPDATE sessions SET current_checkpoint_id = ?, updated_at = ? WHERE session_id = ?",
                (checkpoint_id, time.time(), session_id),
            )
            conn.commit()

    def set_iteration_counters(self, session_id: str, *, fix_iteration_count: Optional[int] = None,
                                clarification_round_count: Optional[int] = None) -> None:
        with closing(connect(self._db_path)) as conn:
            self._require_exists(conn, session_id)
            if fix_iteration_count is not None:
                conn.execute(
                    "UPDATE sessions SET fix_iteration_count = ?, updated_at = ? WHERE session_id = ?",
                    (fix_iteration_count, time.time(), session_id),
                )
            if clarification_round_count is not None:
                conn.execute(
                    "UPDATE sessions SET clarification_round_count = ?, updated_at = ? WHERE session_id = ?",
                    (clarification_round_count, time.time(), session_id),
                )
            conn.commit()

    def archive(self, session_id: str) -> None:
        with closing(connect(self._db_path)) as conn:
            self._require_exists(conn, session_id)
            now = time.time()
            conn.execute(
                "UPDATE sessions SET status = 'ARCHIVED', archived_at = ?, updated_at = ? WHERE session_id = ?",
                (now, now, session_id),
            )
            conn.commit()
