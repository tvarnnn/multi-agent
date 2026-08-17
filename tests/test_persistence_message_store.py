import pytest

from agent_platform.persistence.db import ensure_schema, resolve_agent_paths
from agent_platform.persistence.message_store import MessageStore
from agent_platform.persistence.session_store import SessionStore
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
    SessionStore(db_path).create(session_id="s1", operating_mode="CHAT", session_mode="AUTO", spec_id=None)
    return "s1"


@pytest.fixture
def store(db_path):
    return MessageStore(db_path)


def test_append_mints_sequential_seq_per_session(store, session_id):
    m1 = store.append(session_id=session_id, speaker="user", content="hello")
    m2 = store.append(session_id=session_id, speaker="assistant", content="hi there")
    assert m1.seq == 1
    assert m2.seq == 2
    assert m1.speaker == "user"
    assert m2.speaker == "assistant"


def test_seq_sequences_are_independent_per_session(store, db_path):
    SessionStore(db_path).create(session_id="s2", operating_mode="CHAT", session_mode="AUTO", spec_id=None)
    store.append(session_id="s2", speaker="user", content="a")
    m2 = store.append(session_id="s2", speaker="user", content="b")
    assert m2.seq == 2


def test_since_returns_messages_after_given_seq_ascending(store, session_id):
    for i in range(5):
        store.append(session_id=session_id, speaker="user", content=f"msg-{i}")
    result = store.since(session_id, since_seq=2)
    assert [m.seq for m in result] == [3, 4, 5]


def test_since_default_returns_all(store, session_id):
    store.append(session_id=session_id, speaker="user", content="a")
    store.append(session_id=session_id, speaker="assistant", content="b")
    result = store.since(session_id)
    assert len(result) == 2


def test_recent_returns_bounded_window_ascending(store, session_id):
    for i in range(10):
        store.append(session_id=session_id, speaker="user", content=f"msg-{i}")
    result = store.recent(session_id, window=3)
    assert [m.seq for m in result] == [8, 9, 10]


def test_recent_respects_since_seq_floor(store, session_id):
    for i in range(10):
        store.append(session_id=session_id, speaker="user", content=f"msg-{i}")
    result = store.recent(session_id, window=100, since_seq=7)
    assert [m.seq for m in result] == [8, 9, 10]


def test_list_page_returns_most_recent_first_bounded_by_limit(store, session_id):
    for i in range(5):
        store.append(session_id=session_id, speaker="user", content=f"msg-{i}")
    page = store.list_page(session_id, limit=2)
    assert [m.seq for m in page] == [5, 4]


def test_list_page_before_seq_paginates_backward(store, session_id):
    for i in range(5):
        store.append(session_id=session_id, speaker="user", content=f"msg-{i}")
    page = store.list_page(session_id, before_seq=4, limit=2)
    assert [m.seq for m in page] == [3, 2]


def test_content_round_trips_exactly(store, session_id):
    store.append(session_id=session_id, speaker="user", content="line1\nline2\ttabbed")
    result = store.since(session_id)
    assert result[0].content == "line1\nline2\ttabbed"
