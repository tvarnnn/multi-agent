import pytest

from agent_platform.persistence.db import ensure_schema, resolve_agent_paths
from agent_platform.persistence.session_store import SessionNotFoundError, SessionStore
from agent_platform.security.sandbox import FilesystemSandbox


@pytest.fixture
def db_path(tmp_path):
    workspace = tmp_path / "Projects"
    workspace.mkdir()
    project = (workspace / "MyProj")
    project.mkdir()
    project = project.resolve()
    sandbox = FilesystemSandbox(workspace)
    paths = resolve_agent_paths(sandbox, project, ".agent")
    ensure_schema(paths.db_path, project)
    return paths.db_path


@pytest.fixture
def store(db_path):
    return SessionStore(db_path)


def test_create_returns_session_record_with_defaults(store):
    record = store.create(session_id="s1", operating_mode="CHAT", session_mode="AUTO", spec_id=None)
    assert record.session_id == "s1"
    assert record.operating_mode == "CHAT"
    assert record.session_mode == "AUTO"
    assert record.spec_id is None
    assert record.status == "ACTIVE"
    assert record.fix_iteration_count == 0
    assert record.clarification_round_count == 0
    assert record.archived_at is None


def test_get_returns_created_session(store):
    store.create(session_id="s1", operating_mode="PLAN", session_mode="AUTO", spec_id="spec-1")
    record = store.get("s1")
    assert record.session_id == "s1"
    assert record.spec_id == "spec-1"


def test_get_returns_none_for_unknown_session(store):
    assert store.get("does-not-exist") is None


def test_list_orders_by_updated_at_descending(store):
    store.create(session_id="s1", operating_mode="CHAT", session_mode="AUTO", spec_id=None)
    store.create(session_id="s2", operating_mode="CHAT", session_mode="AUTO", spec_id=None)
    store.touch("s1")
    records = store.list()
    assert [r.session_id for r in records] == ["s1", "s2"]


def test_list_filters_by_status(store):
    store.create(session_id="s1", operating_mode="CHAT", session_mode="AUTO", spec_id=None)
    store.create(session_id="s2", operating_mode="CHAT", session_mode="AUTO", spec_id=None)
    store.set_status("s2", "ARCHIVED")
    active = store.list(statuses=("ACTIVE",))
    assert [r.session_id for r in active] == ["s1"]


def test_set_status_updates_status_and_updated_at(store):
    before = store.create(session_id="s1", operating_mode="CHAT", session_mode="AUTO", spec_id=None)
    store.set_status("s1", "COMPLETED")
    after = store.get("s1")
    assert after.status == "COMPLETED"
    assert after.updated_at >= before.updated_at


def test_set_status_unknown_session_raises(store):
    with pytest.raises(SessionNotFoundError):
        store.set_status("nope", "COMPLETED")


def test_archive_sets_status_and_archived_at(store):
    store.create(session_id="s1", operating_mode="CHAT", session_mode="AUTO", spec_id=None)
    store.archive("s1")
    record = store.get("s1")
    assert record.status == "ARCHIVED"
    assert record.archived_at is not None


def test_set_active_spec_version(store):
    store.create(session_id="s1", operating_mode="PLAN", session_mode="AUTO", spec_id="spec-1")
    store.set_active_spec_version("s1", 2)
    assert store.get("s1").active_spec_version == 2


def test_set_active_plan_id(store):
    store.create(session_id="s1", operating_mode="PLAN", session_mode="AUTO", spec_id="spec-1")
    store.set_active_plan_id("s1", 42)
    assert store.get("s1").active_plan_id == 42


def test_set_current_checkpoint(store):
    store.create(session_id="s1", operating_mode="CHAT", session_mode="AUTO", spec_id=None)
    store.set_current_checkpoint("s1", 7)
    assert store.get("s1").current_checkpoint_id == 7


def test_set_iteration_counters(store):
    store.create(session_id="s1", operating_mode="CODE", session_mode="AUTO", spec_id="spec-1")
    store.set_iteration_counters("s1", fix_iteration_count=2, clarification_round_count=1)
    record = store.get("s1")
    assert record.fix_iteration_count == 2
    assert record.clarification_round_count == 1


def test_create_duplicate_session_id_raises(store):
    store.create(session_id="s1", operating_mode="CHAT", session_mode="AUTO", spec_id=None)
    with pytest.raises(Exception):
        store.create(session_id="s1", operating_mode="CHAT", session_mode="AUTO", spec_id=None)
