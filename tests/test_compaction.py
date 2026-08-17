import pytest

from agent_platform.persistence.checkpoint_store import CheckpointStore
from agent_platform.persistence.compaction import maybe_compact
from agent_platform.persistence.db import ensure_schema, resolve_agent_paths
from agent_platform.persistence.message_store import MessageStore
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
def stores(db_path, project, sandbox):
    return {
        "session_store": SessionStore(db_path),
        "message_store": MessageStore(db_path),
        "checkpoint_store": CheckpointStore(db_path, sandbox=sandbox, project_root=project,
                                             checkpoints_relative_dir=".agent/context/checkpoints"),
    }


def _fake_checkpoint(session_id, reason, covers_through_seq=0):
    return CheckpointRecord(
        session_id=session_id, seq=0, covers_through_seq=covers_through_seq, spec_id="spec-1",
        spec_version_label="spec-1-v1", plan_snapshot_id=None, operating_mode="CODE", objective="obj",
        completed_work=(), current_problem="", relevant_decisions=(), reviewer_feedback=(),
        validation_passed=None, validation_details=(), changed_file_hashes={}, next_action="",
        constraints=(), context_references=(), reason=reason,
    )


def test_disabled_never_compacts_even_over_threshold(stores, session_id):
    stores["message_store"].append(session_id=session_id, speaker="user", content="x" * 100_000)
    calls = []
    result = maybe_compact(
        session_id=session_id, message_store=stores["message_store"],
        checkpoint_store=stores["checkpoint_store"], session_store=stores["session_store"],
        build_checkpoint=lambda reason: calls.append(reason) or _fake_checkpoint(session_id, reason),
        enabled=False, budget=1000, threshold_percent=85,
    )
    assert result is None
    assert calls == []


def test_below_threshold_does_not_compact(stores, session_id):
    stores["message_store"].append(session_id=session_id, speaker="user", content="short")
    result = maybe_compact(
        session_id=session_id, message_store=stores["message_store"],
        checkpoint_store=stores["checkpoint_store"], session_store=stores["session_store"],
        build_checkpoint=lambda reason: _fake_checkpoint(session_id, reason),
        enabled=True, budget=1000, threshold_percent=85,
    )
    assert result is None


def test_at_or_above_threshold_compacts(stores, session_id):
    # budget=100, threshold=85% -> 85 tokens; ~4 chars/token -> need >=340 chars
    stores["message_store"].append(session_id=session_id, speaker="user", content="x" * 400)
    result = maybe_compact(
        session_id=session_id, message_store=stores["message_store"],
        checkpoint_store=stores["checkpoint_store"], session_store=stores["session_store"],
        build_checkpoint=lambda reason: _fake_checkpoint(session_id, reason),
        enabled=True, budget=100, threshold_percent=85,
    )
    assert result is not None
    assert result.reason == "compaction_threshold"


def test_threshold_compaction_updates_session_current_checkpoint(stores, session_id):
    stores["message_store"].append(session_id=session_id, speaker="user", content="x" * 400)
    result = maybe_compact(
        session_id=session_id, message_store=stores["message_store"],
        checkpoint_store=stores["checkpoint_store"], session_store=stores["session_store"],
        build_checkpoint=lambda reason: _fake_checkpoint(session_id, reason),
        enabled=True, budget=100, threshold_percent=85,
    )
    assert stores["session_store"].get(session_id).current_checkpoint_id == result.id


def test_forced_reason_compacts_regardless_of_threshold(stores, session_id):
    result = maybe_compact(
        session_id=session_id, message_store=stores["message_store"],
        checkpoint_store=stores["checkpoint_store"], session_store=stores["session_store"],
        build_checkpoint=lambda reason: _fake_checkpoint(session_id, reason),
        enabled=True, budget=100, threshold_percent=85, reason_if_forced="plan_approved",
    )
    assert result is not None
    assert result.reason == "plan_approved"


def test_forced_reason_works_even_when_compaction_disabled(stores, session_id):
    result = maybe_compact(
        session_id=session_id, message_store=stores["message_store"],
        checkpoint_store=stores["checkpoint_store"], session_store=stores["session_store"],
        build_checkpoint=lambda reason: _fake_checkpoint(session_id, reason),
        enabled=False, budget=100, threshold_percent=85, reason_if_forced="archive",
    )
    assert result is not None
    assert result.reason == "archive"


def test_unknown_forced_reason_rejected(stores, session_id):
    with pytest.raises(ValueError):
        maybe_compact(
            session_id=session_id, message_store=stores["message_store"],
            checkpoint_store=stores["checkpoint_store"], session_store=stores["session_store"],
            build_checkpoint=lambda reason: _fake_checkpoint(session_id, reason),
            enabled=True, budget=100, threshold_percent=85, reason_if_forced="made_up_reason",
        )


def test_only_messages_since_last_checkpoint_count_toward_threshold(stores, session_id):
    stores["message_store"].append(session_id=session_id, speaker="user", content="x" * 400)
    maybe_compact(
        session_id=session_id, message_store=stores["message_store"],
        checkpoint_store=stores["checkpoint_store"], session_store=stores["session_store"],
        build_checkpoint=lambda reason: _fake_checkpoint(session_id, reason, covers_through_seq=1),
        enabled=True, budget=100, threshold_percent=85,
    )
    # A short new message after the checkpoint should NOT immediately re-trigger.
    stores["message_store"].append(session_id=session_id, speaker="user", content="short")
    result = maybe_compact(
        session_id=session_id, message_store=stores["message_store"],
        checkpoint_store=stores["checkpoint_store"], session_store=stores["session_store"],
        build_checkpoint=lambda reason: _fake_checkpoint(session_id, reason),
        enabled=True, budget=100, threshold_percent=85,
    )
    assert result is None
