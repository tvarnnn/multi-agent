import sqlite3
from contextlib import closing

import pytest

from agent_platform.persistence.db import (
    ProjectRootMismatchError,
    SchemaVersionMismatchError,
    connect,
    ensure_schema,
    resolve_agent_paths,
)
from agent_platform.security.sandbox import FilesystemSandbox

EXPECTED_TABLES = {
    "schema_meta", "sessions", "messages", "decisions", "spec_versions",
    "plan_snapshots", "checkpoints", "tool_observations",
}


@pytest.fixture
def project(tmp_path):
    workspace = tmp_path / "Projects"
    workspace.mkdir()
    proj = workspace / "MyProj"
    proj.mkdir()
    return proj.resolve()


@pytest.fixture
def sandbox(project):
    return FilesystemSandbox(project.parent)


# --------------------------------------------------------- path resolution

def test_resolve_agent_paths_defaults_under_dot_agent(project, sandbox):
    paths = resolve_agent_paths(sandbox, project, ".agent")
    assert paths.db_path == (project / ".agent" / "agent.db").resolve(strict=False)
    assert paths.checkpoints_dir == (project / ".agent" / "context" / "checkpoints").resolve(strict=False)


def test_resolve_agent_paths_honors_custom_agent_data_dir(project, sandbox):
    paths = resolve_agent_paths(sandbox, project, ".custom-agent-dir")
    assert paths.db_path == (project / ".custom-agent-dir" / "agent.db").resolve(strict=False)


def test_resolve_agent_paths_rejects_traversal_escape(project, sandbox):
    with pytest.raises(Exception):
        resolve_agent_paths(sandbox, project, "../../escape")


def test_resolve_agent_paths_rejects_absolute_agent_data_dir(project, sandbox):
    with pytest.raises(Exception):
        resolve_agent_paths(sandbox, project, "C:\\Windows\\Temp")


# --------------------------------------------------------------- schema init

def test_ensure_schema_creates_all_tables(project, sandbox):
    paths = resolve_agent_paths(sandbox, project, ".agent")
    ensure_schema(paths.db_path, project)
    with closing(sqlite3.connect(paths.db_path)) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = {r[0] for r in rows}
    assert EXPECTED_TABLES <= names


def test_ensure_schema_is_idempotent(project, sandbox):
    paths = resolve_agent_paths(sandbox, project, ".agent")
    ensure_schema(paths.db_path, project)
    ensure_schema(paths.db_path, project)  # must not raise, must not duplicate schema_meta
    with closing(sqlite3.connect(paths.db_path)) as conn:
        count = conn.execute("SELECT COUNT(*) FROM schema_meta").fetchone()[0]
    assert count == 1


def test_ensure_schema_records_project_root(project, sandbox):
    paths = resolve_agent_paths(sandbox, project, ".agent")
    ensure_schema(paths.db_path, project)
    with closing(sqlite3.connect(paths.db_path)) as conn:
        row = conn.execute("SELECT project_root FROM schema_meta").fetchone()
    assert row[0] == str(project)


def test_ensure_schema_rejects_project_root_mismatch(project, sandbox):
    paths = resolve_agent_paths(sandbox, project, ".agent")
    ensure_schema(paths.db_path, project)
    other_root = project.parent / "OtherProj"
    other_root.mkdir()
    with pytest.raises(ProjectRootMismatchError):
        ensure_schema(paths.db_path, other_root.resolve())


def test_ensure_schema_rejects_schema_version_mismatch(project, sandbox):
    paths = resolve_agent_paths(sandbox, project, ".agent")
    ensure_schema(paths.db_path, project)
    with closing(sqlite3.connect(paths.db_path)) as conn:
        conn.execute("UPDATE schema_meta SET schema_version = 999")
        conn.commit()
    with pytest.raises(SchemaVersionMismatchError):
        ensure_schema(paths.db_path, project)


def test_connect_enables_foreign_keys(project, sandbox):
    paths = resolve_agent_paths(sandbox, project, ".agent")
    ensure_schema(paths.db_path, project)
    with closing(connect(paths.db_path)) as conn:
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1


def test_connect_uses_row_factory(project, sandbox):
    paths = resolve_agent_paths(sandbox, project, ".agent")
    ensure_schema(paths.db_path, project)
    with closing(connect(paths.db_path)) as conn:
        conn.execute(
            "INSERT INTO sessions (session_id, operating_mode, session_mode, status, "
            "fix_iteration_count, clarification_round_count, created_at, updated_at) "
            "VALUES ('s1', 'CHAT', 'AUTO', 'ACTIVE', 0, 0, 0.0, 0.0)")
        conn.commit()
        row = conn.execute("SELECT * FROM sessions").fetchone()
    assert row["session_id"] == "s1"
