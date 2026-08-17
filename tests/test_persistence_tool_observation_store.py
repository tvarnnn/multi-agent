import pytest

from agent_platform.persistence.db import ensure_schema, resolve_agent_paths
from agent_platform.persistence.session_store import SessionStore
from agent_platform.persistence.tool_observation_store import ToolObservationStore
from agent_platform.security.sandbox import FilesystemSandbox


@pytest.fixture
def db_path(tmp_path):
    workspace = tmp_path / "Projects"
    workspace.mkdir()
    project = workspace / "MyProj"
    project.mkdir()
    project = project.resolve()
    sandbox = FilesystemSandbox(workspace)
    paths = resolve_agent_paths(sandbox, project, ".agent")
    ensure_schema(paths.db_path, project)
    return paths.db_path


@pytest.fixture
def session_id(db_path):
    SessionStore(db_path).create(session_id="s1", operating_mode="CODE", session_mode="AUTO", spec_id="spec-1")
    return "s1"


def test_append_records_path_but_never_file_content(db_path, session_id):
    store = ToolObservationStore(db_path)
    record = store.append(
        session_id=session_id, tool_name="filesystem.write", status="ok",
        arguments={"path": "secret.py", "content": "API_KEY = 'sk-supersecret12345'"},
        result={"bytes_written": 33},
    )
    assert record.summary.get("path") == "secret.py"
    assert "API_KEY" not in str(record.summary)
    assert "sk-supersecret12345" not in str(record.summary)


def test_append_records_read_result_content_never_persisted(db_path, session_id):
    store = ToolObservationStore(db_path)
    record = store.append(
        session_id=session_id, tool_name="filesystem.read", status="ok",
        arguments={"path": "config.py"}, result={"content": "SECRET_TOKEN=abc"},
    )
    assert "SECRET_TOKEN" not in str(record.summary)
    assert "abc" not in str(record.summary)


def test_append_mints_sequential_seq(db_path, session_id):
    store = ToolObservationStore(db_path)
    r1 = store.append(session_id=session_id, tool_name="git.status", status="ok", arguments={}, result={})
    r2 = store.append(session_id=session_id, tool_name="git.diff", status="ok", arguments={}, result={})
    assert r1.seq == 1
    assert r2.seq == 2


def test_recent_returns_ordered_ascending(db_path, session_id):
    store = ToolObservationStore(db_path)
    for i in range(5):
        store.append(session_id=session_id, tool_name="git.status", status="ok", arguments={}, result={})
    result = store.recent(session_id)
    assert [r.seq for r in result] == [1, 2, 3, 4, 5]


def test_retention_prunes_oldest_beyond_limit(db_path, session_id):
    store = ToolObservationStore(db_path, retention=3)
    for i in range(5):
        store.append(session_id=session_id, tool_name="git.status", status="ok",
                      arguments={"path": f"f{i}.py"}, result={})
    remaining = store.recent(session_id)
    assert len(remaining) == 3
    assert [r.summary.get("path") for r in remaining] == ["f2.py", "f3.py", "f4.py"]


def test_status_field_preserved(db_path, session_id):
    store = ToolObservationStore(db_path)
    record = store.append(session_id=session_id, tool_name="filesystem.write", status="denied",
                           arguments={"path": "x.py"}, result=None)
    assert record.status == "denied"
    assert record.tool_name == "filesystem.write"
