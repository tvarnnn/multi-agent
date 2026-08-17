"""Append-only user-facing message history. `seq` is minted here (per
session, monotonic) rather than taken from EventLog, which has no id -
this is the ordering key every other store's "since this point" queries
use.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Optional

from .db import connect
from .records import MessageRecord


def _row_to_record(row: sqlite3.Row) -> MessageRecord:
    return MessageRecord(id=row["id"], session_id=row["session_id"], seq=row["seq"],
                          speaker=row["speaker"], content=row["content"], created_at=row["created_at"])


class MessageStore:
    def __init__(self, db_path: Path):
        self._db_path = db_path

    def append(self, *, session_id: str, speaker: str, content: str,
               created_at: Optional[float] = None) -> MessageRecord:
        created_at = time.time() if created_at is None else created_at
        with closing(connect(self._db_path)) as conn:
            next_seq = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM messages WHERE session_id = ?", (session_id,),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO messages (session_id, seq, speaker, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, next_seq, speaker, content, created_at),
            )
            row = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? AND seq = ?", (session_id, next_seq),
            ).fetchone()
            conn.commit()
        return _row_to_record(row)

    def since(self, session_id: str, since_seq: int = 0) -> tuple:
        with closing(connect(self._db_path)) as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? AND seq > ? ORDER BY seq",
                (session_id, since_seq),
            ).fetchall()
        return tuple(_row_to_record(r) for r in rows)

    def recent(self, session_id: str, window: int, since_seq: int = 0) -> tuple:
        with closing(connect(self._db_path)) as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? AND seq > ? ORDER BY seq DESC LIMIT ?",
                (session_id, since_seq, window),
            ).fetchall()
        return tuple(_row_to_record(r) for r in reversed(rows))

    def list_page(self, session_id: str, before_seq: Optional[int] = None, limit: int = 50) -> tuple:
        with closing(connect(self._db_path)) as conn:
            if before_seq is None:
                rows = conn.execute(
                    "SELECT * FROM messages WHERE session_id = ? ORDER BY seq DESC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM messages WHERE session_id = ? AND seq < ? ORDER BY seq DESC LIMIT ?",
                    (session_id, before_seq, limit),
                ).fetchall()
        return tuple(_row_to_record(r) for r in rows)
