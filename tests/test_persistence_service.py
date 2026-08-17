import pytest

from agent_platform.context.bundle import ContextBundle
from agent_platform.events import EventLog
from agent_platform.orchestrator.plan_schemas import StructuredPlan
from agent_platform.persistence.db import ensure_schema, resolve_agent_paths
from agent_platform.persistence.service import SessionPersistenceService
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
def spec_store():
    return SpecStore()


@pytest.fixture
def gateway(sandbox):
    return ToolGateway(build_default_registry(), PermissionEvaluator(sandbox), EventLog())


@pytest.fixture
def db_path(project, sandbox):
    paths = resolve_agent_paths(sandbox, project, ".agent")
    ensure_schema(paths.db_path, project)
    return paths.db_path


@pytest.fixture
def service(db_path, project, sandbox, spec_store, gateway):
    return SessionPersistenceService(
        db_path=db_path, sandbox=sandbox, project_root=project,
        checkpoints_relative_dir=".agent/context/checkpoints", gateway=gateway, spec_store=spec_store,
        compaction_enabled=True, compaction_threshold_percent=85, max_conversation_tokens_estimate=20_000,
        recent_message_window=20, checkpoint_max_age_seconds=86_400,
    )


def _plan(**overrides):
    defaults = dict(
        objective="obj", requirements=(), existing_context=(), proposed_architecture="",
        files_to_create=(), files_to_modify=(), dependencies=(), implementation_steps=(),
        validation_strategy=(), risks=(), unknowns=(), acceptance_criteria=(),
        reviewer_feedback=(), target_spec_version_label="spec-1-v1",
    )
    defaults.update(overrides)
    return StructuredPlan(**defaults)


def test_create_and_get_session(service):
    created = service.create_session("s1", operating_mode="CHAT", session_mode="AUTO", spec_id=None)
    assert created.session_id == "s1"
    assert service.get_session("s1").operating_mode == "CHAT"


def test_record_message_touches_session(service):
    service.create_session("s1", operating_mode="CHAT", session_mode="AUTO", spec_id=None)
    before = service.get_session("s1").updated_at
    service.record_message("s1", speaker="user", content="hello")
    assert service.get_session("s1").updated_at >= before


def test_get_history_returns_recorded_messages(service):
    service.create_session("s1", operating_mode="CHAT", session_mode="AUTO", spec_id=None)
    service.record_message("s1", speaker="user", content="hello")
    service.record_message("s1", speaker="assistant", content="hi")
    history = service.get_history("s1")
    assert [m.speaker for m in reversed(history)] == ["user", "assistant"]


def test_record_decision_round_trips(service):
    service.create_session("s1", operating_mode="PLAN", session_mode="AUTO", spec_id="spec-1")
    record = service.record_decision("s1", event_type="PLAN_CREATED", payload={"spec_id": "spec-1", "path": "p.md"})
    assert record.event_type == "PLAN_CREATED"


def test_record_spec_version_and_rehydrate_round_trip(service, spec_store, db_path, sandbox, project, gateway):
    service.create_session("s1", operating_mode="CODE", session_mode="AUTO", spec_id="spec-1")
    created = spec_store.create("spec-1", goals=("g1",), constraints=(), acceptance_criteria=("file:a.py",))
    service.record_spec_version(created)

    fresh_spec_store = SpecStore()
    fresh_service = SessionPersistenceService(
        db_path=db_path, sandbox=sandbox, project_root=project,
        checkpoints_relative_dir=".agent/context/checkpoints", gateway=gateway, spec_store=fresh_spec_store,
    )
    fresh_service.rehydrate()
    assert fresh_spec_store.latest("spec-1").goals == ("g1",)


def test_record_plan_snapshot_updates_active_plan_id(service):
    service.create_session("s1", operating_mode="PLAN", session_mode="AUTO", spec_id="spec-1")
    record = service.record_plan_snapshot(
        "s1", spec_id="spec-1", version=1, status="DRAFT", path="p.md",
        spec_version_label="spec-1-v1", finalized_paths=(), plan=_plan(),
    )
    assert service.get_session("s1").active_plan_id == record.id
    assert service.latest_plan_snapshot("s1", "spec-1").status == "DRAFT"


def test_record_tool_observation_redacts_content(service):
    service.create_session("s1", operating_mode="CODE", session_mode="AUTO", spec_id=None)
    record = service.record_tool_observation(
        "s1", tool_name="filesystem.read", status="ok",
        arguments={"path": "main.py"}, result={"content": "print('secret stuff')"},
    )
    assert "secret" not in str(record.summary)
    assert record.summary.get("path") == "main.py"


def test_record_checkpoint_hashes_live_changed_files(service):
    service.create_session("s1", operating_mode="CODE", session_mode="AUTO", spec_id=None)
    checkpoint = service.record_checkpoint(
        "s1", reason="terminal_state", operating_mode="CODE", session_mode="AUTO",
        objective="did a thing", changed_files=("main.py",),
    )
    assert "main.py" in checkpoint.changed_file_hashes
    assert service.get_session("s1").current_checkpoint_id == checkpoint.id


def test_maybe_compact_below_threshold_returns_none(service):
    service.create_session("s1", operating_mode="CHAT", session_mode="AUTO", spec_id=None)
    service.record_message("s1", speaker="user", content="short")
    assert service.maybe_compact("s1") is None


def test_maybe_compact_above_threshold_creates_checkpoint(project, sandbox, spec_store, gateway):
    paths = resolve_agent_paths(sandbox, project, ".agent")
    ensure_schema(paths.db_path, project)
    service = SessionPersistenceService(
        db_path=paths.db_path, sandbox=sandbox, project_root=project,
        checkpoints_relative_dir=".agent/context/checkpoints", gateway=gateway, spec_store=spec_store,
        compaction_enabled=True, compaction_threshold_percent=85, max_conversation_tokens_estimate=100,
        recent_message_window=20, checkpoint_max_age_seconds=86_400,
    )
    service.create_session("s1", operating_mode="CHAT", session_mode="AUTO", spec_id=None)
    service.record_message("s1", speaker="user", content="x" * 400)
    checkpoint = service.maybe_compact("s1")
    assert checkpoint is not None
    assert checkpoint.reason == "compaction_threshold"


def test_force_checkpoint_bypasses_threshold(service):
    service.create_session("s1", operating_mode="PLAN", session_mode="AUTO", spec_id=None)
    checkpoint = service.force_checkpoint("s1", reason="plan_approved")
    assert checkpoint.reason == "plan_approved"


def test_archive_session_forces_checkpoint_and_archives(service):
    service.create_session("s1", operating_mode="CHAT", session_mode="AUTO", spec_id=None)
    checkpoint = service.archive_session("s1")
    assert checkpoint.reason == "archive"
    assert service.get_session("s1").status == "ARCHIVED"


def test_get_checkpoints_and_get_checkpoint(service):
    service.create_session("s1", operating_mode="CHAT", session_mode="AUTO", spec_id=None)
    first = service.force_checkpoint("s1", reason="terminal_state")
    listed = service.get_checkpoints("s1")
    assert listed[0].id == first.id
    assert service.get_checkpoint("s1", first.id).id == first.id
    assert service.get_checkpoint("s1", 999999) is None


def test_resume_returns_reconstructed_context(service):
    service.create_session("s1", operating_mode="CHAT", session_mode="AUTO", spec_id=None)
    service.record_message("s1", speaker="user", content="hello")
    result = service.resume("s1")
    assert result.operating_mode == "CHAT"
    assert isinstance(result.project_bundle, ContextBundle)
