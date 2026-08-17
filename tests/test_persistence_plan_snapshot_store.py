import pytest

from agent_platform.orchestrator.plan_schemas import StructuredPlan
from agent_platform.persistence.db import ensure_schema, resolve_agent_paths
from agent_platform.persistence.plan_snapshot_store import PlanSnapshotStore
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
    SessionStore(db_path).create(session_id="s1", operating_mode="PLAN", session_mode="AUTO", spec_id="spec-1")
    return "s1"


@pytest.fixture
def store(db_path):
    return PlanSnapshotStore(db_path)


def _plan(**overrides):
    defaults = dict(
        objective="Build the widget", requirements=("req1", "req2"), existing_context=("ctx1",),
        proposed_architecture="single module", files_to_create=("widget.py",), files_to_modify=(),
        dependencies=(), implementation_steps=("step1",), validation_strategy=("test1",),
        risks=("risk1",), unknowns=(), acceptance_criteria=("file:widget.py",),
        reviewer_feedback=("looks fine",), target_spec_version_label="spec-1-v1",
    )
    defaults.update(overrides)
    return StructuredPlan(**defaults)


def test_append_round_trips_structured_plan_exactly(store, session_id):
    plan = _plan()
    record = store.append(session_id=session_id, spec_id="spec-1", version=1, status="DRAFT",
                           path=".agent/plans/2026-08-17-spec-1-spec-v1.md",
                           spec_version_label="spec-1-v1", finalized_paths=(), plan=plan)
    assert record.id is not None
    loaded = store.latest(session_id, "spec-1")
    assert loaded.plan == plan


def test_latest_returns_none_when_no_snapshot(store, session_id):
    assert store.latest(session_id, "spec-1") is None


def test_latest_returns_most_recent_by_insertion_order(store, session_id):
    plan1 = _plan(objective="v1 objective")
    plan2 = _plan(objective="v2 objective")
    store.append(session_id=session_id, spec_id="spec-1", version=1, status="DRAFT",
                  path="p1.md", spec_version_label="spec-1-v1", finalized_paths=(), plan=plan1)
    store.append(session_id=session_id, spec_id="spec-1", version=1, status="REVISED",
                  path="p1.md", spec_version_label="spec-1-v1", finalized_paths=(), plan=plan2)
    latest = store.latest(session_id, "spec-1")
    assert latest.plan.objective == "v2 objective"
    assert latest.status == "REVISED"


def test_latest_is_scoped_per_spec_id(store, session_id):
    store.append(session_id=session_id, spec_id="spec-a", version=1, status="DRAFT",
                  path="a.md", spec_version_label="spec-a-v1", finalized_paths=(), plan=_plan())
    store.append(session_id=session_id, spec_id="spec-b", version=1, status="DRAFT",
                  path="b.md", spec_version_label="spec-b-v1", finalized_paths=(), plan=_plan())
    assert store.latest(session_id, "spec-a").spec_id == "spec-a"
    assert store.latest(session_id, "spec-b").spec_id == "spec-b"


def test_list_for_session_spec_returns_full_history_in_order(store, session_id):
    store.append(session_id=session_id, spec_id="spec-1", version=1, status="DRAFT",
                  path="p.md", spec_version_label="spec-1-v1", finalized_paths=(), plan=_plan())
    store.append(session_id=session_id, spec_id="spec-1", version=1, status="REVISED",
                  path="p.md", spec_version_label="spec-1-v1", finalized_paths=(), plan=_plan())
    store.append(session_id=session_id, spec_id="spec-1", version=1, status="APPROVED",
                  path="p.md", spec_version_label="spec-1-v1", finalized_paths=(), plan=_plan())
    history = store.list_for_session_spec(session_id, "spec-1")
    assert [h.status for h in history] == ["DRAFT", "REVISED", "APPROVED"]


def test_finalized_paths_round_trip(store, session_id):
    store.append(session_id=session_id, spec_id="spec-1", version=2, status="DRAFT",
                  path="p2.md", spec_version_label="spec-1-v2", finalized_paths=("p1.md",), plan=_plan())
    record = store.latest(session_id, "spec-1")
    assert record.finalized_paths == ("p1.md",)
