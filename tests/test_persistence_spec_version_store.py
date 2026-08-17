import pytest

from agent_platform.persistence.db import ensure_schema, resolve_agent_paths
from agent_platform.persistence.spec_version_store import (
    SpecRehydrationError,
    SpecVersionStore,
    rehydrate_spec_store,
)
from agent_platform.security.sandbox import FilesystemSandbox
from agent_platform.spec.versioning import SpecStore


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
def store(db_path):
    return SpecVersionStore(db_path)


def test_append_and_list_for_spec(store):
    store.append(spec_id="spec-1", version=1, goals=("g1",), constraints=("c1",),
                 acceptance_criteria=("file:a.py",))
    store.append(spec_id="spec-1", version=2, goals=("g1", "g2"), constraints=("c1",),
                 acceptance_criteria=("file:a.py",))
    records = store.list_for_spec("spec-1")
    assert [r.version for r in records] == [1, 2]
    assert records[1].goals == ("g1", "g2")


def test_list_for_spec_unknown_returns_empty(store):
    assert store.list_for_spec("no-such-spec") == ()


def test_list_all_orders_by_spec_id_then_version(store):
    store.append(spec_id="spec-b", version=1, goals=(), constraints=(), acceptance_criteria=())
    store.append(spec_id="spec-a", version=1, goals=(), constraints=(), acceptance_criteria=())
    store.append(spec_id="spec-a", version=2, goals=(), constraints=(), acceptance_criteria=())
    records = store.list_all()
    assert [(r.spec_id, r.version) for r in records] == [("spec-a", 1), ("spec-a", 2), ("spec-b", 1)]


def test_rehydrate_replays_single_spec(store):
    store.append(spec_id="spec-1", version=1, goals=("g1",), constraints=(), acceptance_criteria=("file:a.py",))
    store.append(spec_id="spec-1", version=2, goals=("g1", "g2"), constraints=(), acceptance_criteria=("file:a.py",))
    spec_store = SpecStore()
    rehydrate_spec_store(spec_store, store.list_all())
    latest = spec_store.latest("spec-1")
    assert latest.version == 2
    assert latest.goals == ("g1", "g2")
    assert spec_store.get("spec-1", 1).goals == ("g1",)


def test_rehydrate_replays_multiple_interleaved_specs(store):
    store.append(spec_id="spec-a", version=1, goals=("a1",), constraints=(), acceptance_criteria=())
    store.append(spec_id="spec-b", version=1, goals=("b1",), constraints=(), acceptance_criteria=())
    store.append(spec_id="spec-a", version=2, goals=("a1", "a2"), constraints=(), acceptance_criteria=())
    spec_store = SpecStore()
    rehydrate_spec_store(spec_store, store.list_all())
    assert spec_store.latest("spec-a").version == 2
    assert spec_store.latest("spec-b").version == 1


def test_rehydrate_empty_records_is_a_noop(store):
    spec_store = SpecStore()
    rehydrate_spec_store(spec_store, ())
    with pytest.raises(KeyError):
        spec_store.latest("anything")


def test_rehydrate_detects_version_gap_corruption(store):
    store.append(spec_id="spec-1", version=1, goals=("g1",), constraints=(), acceptance_criteria=())
    store.append(spec_id="spec-1", version=3, goals=("g3",), constraints=(), acceptance_criteria=())  # gap: no v2
    spec_store = SpecStore()
    with pytest.raises(SpecRehydrationError):
        rehydrate_spec_store(spec_store, store.list_for_spec("spec-1"))
