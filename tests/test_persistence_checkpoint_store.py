import pytest

from agent_platform.persistence.checkpoint_schema import render_checkpoint_markdown
from agent_platform.persistence.checkpoint_store import CheckpointStore
from agent_platform.persistence.db import ensure_schema, resolve_agent_paths
from agent_platform.persistence.records import CheckpointRecord
from agent_platform.persistence.session_store import SessionStore
from agent_platform.security.sandbox import FilesystemSandbox


@pytest.fixture
def project(tmp_path):
    workspace = tmp_path / "Projects"
    workspace.mkdir()
    project = workspace / "MyProj"
    project.mkdir()
    return project.resolve()


@pytest.fixture
def sandbox(project):
    return FilesystemSandbox(project.parent)


@pytest.fixture
def db_path(project, sandbox):
    paths = resolve_agent_paths(sandbox, project, ".agent")
    ensure_schema(paths.db_path, project)
    return paths.db_path


@pytest.fixture
def session_id(db_path):
    SessionStore(db_path).create(session_id="s1", operating_mode="CODE", session_mode="AUTO", spec_id="spec-1")
    return "s1"


@pytest.fixture
def store(db_path, project, sandbox):
    return CheckpointStore(db_path, sandbox=sandbox, project_root=project,
                            checkpoints_relative_dir=".agent/context/checkpoints")


def _checkpoint(session_id, **overrides):
    defaults = dict(
        session_id=session_id, seq=0, spec_id="spec-1", spec_version_label="spec-1-v1",
        plan_snapshot_id=None, operating_mode="CODE", objective="Add health check",
        completed_work=("wrote health.py",), current_problem="", relevant_decisions=(),
        reviewer_feedback=(), validation_passed=None, validation_details=(),
        changed_file_hashes={"health.py": "abc123"}, next_action="run tests",
        constraints=(), context_references=("health.py",), reason="compaction_threshold",
    )
    defaults.update(overrides)
    return CheckpointRecord(**defaults)


def test_append_writes_db_row_and_markdown_file(store, project, session_id):
    checkpoint = _checkpoint(session_id)
    record = store.append(checkpoint, token_estimate=500)
    assert record.id is not None
    assert record.seq == 1
    assert record.content_hash
    md_file = project / record.markdown_path
    assert md_file.is_file()


def test_append_markdown_content_matches_renderer(store, project, session_id):
    checkpoint = _checkpoint(session_id)
    record = store.append(checkpoint, token_estimate=500)
    on_disk = (project / record.markdown_path).read_text(encoding="utf-8")
    assert on_disk == render_checkpoint_markdown(record)


def test_append_mints_sequential_seq_per_session(store, session_id):
    r1 = store.append(_checkpoint(session_id), token_estimate=100)
    r2 = store.append(_checkpoint(session_id), token_estimate=100)
    assert r1.seq == 1
    assert r2.seq == 2


def test_list_desc_orders_newest_first(store, session_id):
    store.append(_checkpoint(session_id, objective="first"), token_estimate=100)
    store.append(_checkpoint(session_id, objective="second"), token_estimate=100)
    listed = store.list_desc(session_id)
    assert [c.objective for c in listed] == ["second", "first"]


def test_latest_returns_most_recent(store, session_id):
    store.append(_checkpoint(session_id, objective="first"), token_estimate=100)
    store.append(_checkpoint(session_id, objective="second"), token_estimate=100)
    assert store.latest(session_id).objective == "second"


def test_latest_returns_none_when_no_checkpoints(store, session_id):
    assert store.latest(session_id) is None


def test_load_latest_valid_returns_latest_when_intact(store, session_id):
    store.append(_checkpoint(session_id, objective="first"), token_estimate=100)
    store.append(_checkpoint(session_id, objective="second"), token_estimate=100)
    result = store.load_latest_valid(session_id)
    assert result.objective == "second"


def test_load_latest_valid_falls_back_on_corrupted_hash(store, project, session_id):
    store.append(_checkpoint(session_id, objective="first"), token_estimate=100)
    second = store.append(_checkpoint(session_id, objective="second"), token_estimate=100)
    (project / second.markdown_path).write_text("tampered content", encoding="utf-8")
    result = store.load_latest_valid(session_id)
    assert result.objective == "first"


def test_load_latest_valid_falls_back_on_missing_file(store, project, session_id):
    store.append(_checkpoint(session_id, objective="first"), token_estimate=100)
    second = store.append(_checkpoint(session_id, objective="second"), token_estimate=100)
    (project / second.markdown_path).unlink()
    result = store.load_latest_valid(session_id)
    assert result.objective == "first"


def test_load_latest_valid_returns_none_when_all_corrupted(store, project, session_id):
    only = store.append(_checkpoint(session_id, objective="only"), token_estimate=100)
    (project / only.markdown_path).unlink()
    assert store.load_latest_valid(session_id) is None


def test_load_latest_valid_returns_none_when_no_checkpoints(store, session_id):
    assert store.load_latest_valid(session_id) is None


def test_append_rejects_traversal_checkpoints_dir(db_path, project, sandbox, session_id):
    malicious_store = CheckpointStore(db_path, sandbox=sandbox, project_root=project,
                                       checkpoints_relative_dir="../../escape")
    with pytest.raises(Exception):
        malicious_store.append(_checkpoint(session_id), token_estimate=100)
