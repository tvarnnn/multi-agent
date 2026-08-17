"""SQLite connection lifecycle, schema management, and sandboxed path
resolution for the persistence layer's own infrastructure files
(.agent/agent.db, .agent/context/checkpoints/**).

Every path resolved here is built exclusively from `project_root` (trusted,
resolved once at Orchestrator/BackendServices construction time) and
`agent_data_dir` (a fixed PlatformConfig value, never a session id, spec
id, or any model/user-supplied string) - so this module's file-write
authority can never be steered by anything a model or a persisted
checkpoint says. FilesystemSandbox.authorize() - the one path-containment
primitive in this codebase - is still called on every resolved path before
any read/write; no second filesystem security mechanism is introduced
here.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from ..security.sandbox import FilesystemSandbox

SCHEMA_VERSION = 1

_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    schema_version INTEGER NOT NULL,
    project_root   TEXT NOT NULL,
    created_at     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id                TEXT PRIMARY KEY,
    operating_mode            TEXT NOT NULL,
    session_mode              TEXT NOT NULL,
    spec_id                   TEXT,
    status                    TEXT NOT NULL,
    active_spec_version       INTEGER,
    active_plan_id            INTEGER,
    current_checkpoint_id     INTEGER,
    fix_iteration_count       INTEGER NOT NULL DEFAULT 0,
    clarification_round_count INTEGER NOT NULL DEFAULT 0,
    created_at                REAL NOT NULL,
    updated_at                REAL NOT NULL,
    archived_at                REAL
);
CREATE INDEX IF NOT EXISTS idx_sessions_status_updated ON sessions(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(session_id),
    seq         INTEGER NOT NULL,
    speaker     TEXT NOT NULL CHECK (speaker IN ('user','assistant')),
    content     TEXT NOT NULL,
    created_at  REAL NOT NULL,
    UNIQUE (session_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_messages_session_seq ON messages(session_id, seq);

CREATE TABLE IF NOT EXISTS decisions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL REFERENCES sessions(session_id),
    seq          INTEGER NOT NULL,
    event_type   TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at   REAL NOT NULL,
    UNIQUE (session_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_decisions_session_seq ON decisions(session_id, seq);

CREATE TABLE IF NOT EXISTS spec_versions (
    spec_id                  TEXT NOT NULL,
    version                  INTEGER NOT NULL,
    goals_json                TEXT NOT NULL,
    constraints_json          TEXT NOT NULL,
    acceptance_criteria_json  TEXT NOT NULL,
    created_at                REAL NOT NULL,
    PRIMARY KEY (spec_id, version)
);

CREATE TABLE IF NOT EXISTS plan_snapshots (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id           TEXT NOT NULL REFERENCES sessions(session_id),
    spec_id              TEXT NOT NULL,
    version              INTEGER NOT NULL,
    status               TEXT NOT NULL CHECK (status IN ('DRAFT','REVISED','APPROVED','REJECTED')),
    path                 TEXT NOT NULL,
    spec_version_label   TEXT NOT NULL,
    finalized_paths_json TEXT NOT NULL DEFAULT '[]',
    plan_json            TEXT NOT NULL,
    created_at            REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plan_snapshots_session_spec ON plan_snapshots(session_id, spec_id, id DESC);

CREATE TABLE IF NOT EXISTS checkpoints (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id              TEXT NOT NULL REFERENCES sessions(session_id),
    seq                     INTEGER NOT NULL,
    covers_through_seq      INTEGER NOT NULL DEFAULT 0,
    spec_id                 TEXT,
    spec_version_label      TEXT,
    plan_snapshot_id        INTEGER REFERENCES plan_snapshots(id),
    operating_mode          TEXT NOT NULL,
    summary                 TEXT NOT NULL,
    changed_files_json      TEXT NOT NULL,
    reviewer_feedback_json  TEXT NOT NULL DEFAULT '[]',
    validation_result_json  TEXT,
    reason                  TEXT NOT NULL,
    content_hash            TEXT NOT NULL,
    markdown_path            TEXT NOT NULL,
    token_estimate            INTEGER NOT NULL,
    created_at                REAL NOT NULL,
    UNIQUE (session_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_session_seq ON checkpoints(session_id, seq DESC);

CREATE TABLE IF NOT EXISTS tool_observations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(session_id),
    seq         INTEGER NOT NULL,
    tool_name   TEXT NOT NULL,
    status      TEXT NOT NULL,
    summary     TEXT NOT NULL,
    created_at  REAL NOT NULL,
    UNIQUE (session_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_tool_obs_session_seq ON tool_observations(session_id, seq DESC);
"""


class PersistencePathError(Exception):
    """A resolved persistence path (agent.db or a checkpoint file) was
    denied by FilesystemSandbox - e.g. a traversal/absolute agent_data_dir
    value in trusted config."""


class PersistedStateCorruptionError(Exception):
    """A persisted row's JSON column (or an expected key within it) could
    not be parsed back into a record. Raised explicitly by every store's
    row-decoding path instead of letting a raw json.JSONDecodeError/
    KeyError propagate - fails closed, never silently substitutes a
    default that could masquerade as valid history."""


def safe_json_loads(text: str, *, context: str):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise PersistedStateCorruptionError(f"malformed JSON in {context}: {exc}") from exc


class ProjectRootMismatchError(Exception):
    def __init__(self, expected: str, actual: str):
        super().__init__(f"agent.db is bound to project_root {expected!r}, got {actual!r}")
        self.expected = expected
        self.actual = actual


class SchemaVersionMismatchError(Exception):
    def __init__(self, expected: int, actual: int):
        super().__init__(f"agent.db schema_version {actual} does not match expected {expected}")
        self.expected = expected
        self.actual = actual


@dataclass(frozen=True)
class AgentPaths:
    db_path: Path
    checkpoints_dir: Path


def resolve_agent_paths(sandbox: FilesystemSandbox, project_root: Path, agent_data_dir: str) -> AgentPaths:
    db_decision = sandbox.authorize(f"{agent_data_dir}/agent.db", scope_root=project_root)
    if not db_decision.allowed:
        raise PersistencePathError(f"cannot resolve agent.db path: {db_decision.reason}")
    checkpoints_decision = sandbox.authorize(f"{agent_data_dir}/context/checkpoints", scope_root=project_root)
    if not checkpoints_decision.allowed:
        raise PersistencePathError(f"cannot resolve checkpoints directory: {checkpoints_decision.reason}")
    return AgentPaths(db_path=db_decision.resolved_path, checkpoints_dir=checkpoints_decision.resolved_path)


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_schema(db_path: Path, project_root: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        conn.executescript(_SCHEMA_DDL)
        row = conn.execute("SELECT schema_version, project_root FROM schema_meta").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO schema_meta (schema_version, project_root, created_at) VALUES (?, ?, ?)",
                (SCHEMA_VERSION, str(project_root), time.time()),
            )
            conn.commit()
            return
        if row["schema_version"] != SCHEMA_VERSION:
            raise SchemaVersionMismatchError(SCHEMA_VERSION, row["schema_version"])
        if row["project_root"] != str(project_root):
            raise ProjectRootMismatchError(row["project_root"], str(project_root))
    finally:
        conn.close()
