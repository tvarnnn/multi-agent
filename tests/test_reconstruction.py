import hashlib

import pytest

from agent_platform.context.bundle import ContextBundle
from agent_platform.events import EventLog
from agent_platform.persistence.checkpoint_store import CheckpointStore
from agent_platform.persistence.db import ensure_schema, resolve_agent_paths
from agent_platform.persistence.message_store import MessageStore
from agent_platform.persistence.records import CheckpointRecord
from agent_platform.persistence.reconstruction import reconstruct_for_resume
from agent_platform.persistence.session_store import SessionNotFoundError, SessionStore
from agent_platform.security.enums import SessionMode
from agent_platform.security.permission import PermissionEvaluator
from agent_platform.security.sandbox import FilesystemSandbox
from agent_platform.spec.versioning import SpecStore
from agent_platform.tools.gateway import ToolGateway
from agent_platform.tools.registry import build_default_registry


@pytest.fixture
def project(tmp_path):
    workspace = tmp_path / "Projects"
    workspace.mkdir()
    project = workspace / "MyProj"
    project.mkdir()
    (project / "main.py").write_text("print('hi')\n", encoding="utf-8")
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
def gateway(sandbox):
    evaluator = PermissionEvaluator(sandbox)
    return ToolGateway(build_default_registry(), evaluator, EventLog())


@pytest.fixture
def spec_store():
    return SpecStore()


@pytest.fixture
def stores(db_path, project, sandbox):
    return {
        "session_store": SessionStore(db_path),
        "message_store": MessageStore(db_path),
        "checkpoint_store": CheckpointStore(db_path, sandbox=sandbox, project_root=project,
                                             checkpoints_relative_dir=".agent/context/checkpoints"),
    }


def _make_session(stores, spec_store, session_id="s1", operating_mode="CODE", spec_id=None):
    stores["session_store"].create(session_id=session_id, operating_mode=operating_mode,
                                    session_mode="AUTO", spec_id=spec_id)
    return session_id


def _file_hash(project, name):
    return hashlib.sha256((project / name).read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def _checkpoint(session_id, *, spec_version_label=None, changed_file_hashes=None, covers_through_seq=0):
    return CheckpointRecord(
        session_id=session_id, seq=0, covers_through_seq=covers_through_seq, spec_id="spec-1",
        spec_version_label=spec_version_label, plan_snapshot_id=None, operating_mode="CODE",
        objective="obj", completed_work=(), current_problem="", relevant_decisions=(),
        reviewer_feedback=(), validation_passed=None, validation_details=(),
        changed_file_hashes=changed_file_hashes or {}, next_action="", constraints=(),
        context_references=(), reason="terminal_state",
    )


def _reconstruct(session_id, stores, spec_store, gateway, project, **overrides):
    kwargs = dict(
        session_id=session_id, session_store=stores["session_store"],
        checkpoint_store=stores["checkpoint_store"], message_store=stores["message_store"],
        spec_store=spec_store, gateway=gateway, project_root=project,
        recent_message_window=20, max_conversation_tokens_estimate=20_000,
        checkpoint_max_age_seconds=86_400,
    )
    kwargs.update(overrides)
    return reconstruct_for_resume(**kwargs)


def test_unknown_session_raises(stores, spec_store, gateway, project):
    with pytest.raises(SessionNotFoundError):
        _reconstruct("nope", stores, spec_store, gateway, project)


def test_happy_path_no_checkpoint_yet(stores, spec_store, gateway, project):
    session_id = _make_session(stores, spec_store)
    stores["message_store"].append(session_id=session_id, speaker="user", content="hello")
    result = _reconstruct(session_id, stores, spec_store, gateway, project)
    assert result.checkpoint is None
    assert result.stale is False
    assert result.stale_reasons == ()
    assert len(result.recent_messages) == 1
    assert isinstance(result.project_bundle, ContextBundle)


def test_authoritative_operating_mode_and_session_mode_come_from_db_row(stores, spec_store, gateway, project):
    session_id = _make_session(stores, spec_store, operating_mode="PLAN")
    result = _reconstruct(session_id, stores, spec_store, gateway, project)
    assert result.operating_mode == "PLAN"
    assert result.session_mode == "AUTO"


def test_valid_checkpoint_unchanged_file_is_not_stale(stores, spec_store, gateway, project):
    session_id = _make_session(stores, spec_store, spec_id="spec-1")
    spec_store.create("spec-1", goals=("g",), constraints=(), acceptance_criteria=())
    checkpoint = _checkpoint(session_id, spec_version_label="spec-1-v1",
                              changed_file_hashes={"main.py": _file_hash(project, "main.py")})
    stores["checkpoint_store"].append(checkpoint, token_estimate=10)
    result = _reconstruct(session_id, stores, spec_store, gateway, project)
    assert result.checkpoint is not None
    assert result.stale is False


def test_spec_advanced_since_checkpoint_is_stale(stores, spec_store, gateway, project):
    session_id = _make_session(stores, spec_store, spec_id="spec-1")
    spec_store.create("spec-1", goals=("g1",), constraints=(), acceptance_criteria=())
    spec_store.create("spec-1", goals=("g1", "g2"), constraints=(), acceptance_criteria=())
    checkpoint = _checkpoint(session_id, spec_version_label="spec-1-v1")
    stores["checkpoint_store"].append(checkpoint, token_estimate=10)
    result = _reconstruct(session_id, stores, spec_store, gateway, project)
    assert result.stale is True
    assert any("spec advanced" in r for r in result.stale_reasons)


def test_changed_file_since_checkpoint_is_stale(stores, spec_store, gateway, project):
    session_id = _make_session(stores, spec_store, spec_id="spec-1")
    spec_store.create("spec-1", goals=("g",), constraints=(), acceptance_criteria=())
    checkpoint = _checkpoint(session_id, spec_version_label="spec-1-v1",
                              changed_file_hashes={"main.py": "not-the-real-hash"})
    stores["checkpoint_store"].append(checkpoint, token_estimate=10)
    result = _reconstruct(session_id, stores, spec_store, gateway, project)
    assert result.stale is True
    assert any("main.py" in r for r in result.stale_reasons)


def test_checkpoint_too_old_is_stale(stores, spec_store, gateway, project):
    import time
    session_id = _make_session(stores, spec_store, spec_id="spec-1")
    spec_store.create("spec-1", goals=("g",), constraints=(), acceptance_criteria=())
    checkpoint = _checkpoint(session_id, spec_version_label="spec-1-v1",
                              changed_file_hashes={"main.py": _file_hash(project, "main.py")})
    stores["checkpoint_store"].append(checkpoint, token_estimate=10, created_at=time.time() - 999_999)
    result = _reconstruct(session_id, stores, spec_store, gateway, project, checkpoint_max_age_seconds=100)
    assert result.stale is True
    assert any("too old" in r for r in result.stale_reasons)


def test_corrupted_latest_checkpoint_falls_back_gracefully(stores, spec_store, gateway, project):
    session_id = _make_session(stores, spec_store, spec_id="spec-1")
    spec_store.create("spec-1", goals=("g",), constraints=(), acceptance_criteria=())
    stores["checkpoint_store"].append(
        _checkpoint(session_id, spec_version_label="spec-1-v1", changed_file_hashes={}), token_estimate=10)
    second = stores["checkpoint_store"].append(
        _checkpoint(session_id, spec_version_label="spec-1-v1", changed_file_hashes={}), token_estimate=10)
    (project / second.markdown_path).write_text("tampered", encoding="utf-8")
    result = _reconstruct(session_id, stores, spec_store, gateway, project)
    assert result.checkpoint is not None
    assert result.checkpoint.seq == 1  # fell back to the earlier valid one


def test_recent_messages_respect_window_and_checkpoint_floor(stores, spec_store, gateway, project):
    session_id = _make_session(stores, spec_store)
    for i in range(5):
        stores["message_store"].append(session_id=session_id, speaker="user", content=f"m{i}")
    checkpoint = _checkpoint(session_id, covers_through_seq=5)
    appended = stores["checkpoint_store"].append(checkpoint, token_estimate=10)
    stores["message_store"].append(session_id=session_id, speaker="user", content="after checkpoint")
    result = _reconstruct(session_id, stores, spec_store, gateway, project, recent_message_window=20)
    assert len(result.recent_messages) == 1
    assert result.recent_messages[0].content == "after checkpoint"


def test_budget_trim_drops_oldest_messages_first_never_the_checkpoint(stores, spec_store, gateway, project):
    session_id = _make_session(stores, spec_store)
    for i in range(5):
        stores["message_store"].append(session_id=session_id, speaker="user", content=f"msg-{i}" * 50)
    result = _reconstruct(session_id, stores, spec_store, gateway, project, max_conversation_tokens_estimate=100)
    assert len(result.recent_messages) < 5
    assert result.messages_dropped_for_budget
    assert result.recent_messages[-1].content.startswith("msg-4")
