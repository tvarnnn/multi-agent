import dataclasses

import pytest

from agent_platform.spec.versioning import SpecStore, SpecVersionMismatchError


def test_create_first_version_is_v1():
    store = SpecStore()
    spec = store.create("task-1", goals=["build a thing"], constraints=[], acceptance_criteria=["tests pass"])
    assert spec.version == 1
    assert spec.version_label == "task-1-v1"


def test_create_second_version_increments():
    store = SpecStore()
    store.create("task-1", goals=["v1 goal"], constraints=[], acceptance_criteria=[])
    v2 = store.create("task-1", goals=["v2 goal"], constraints=[], acceptance_criteria=[])
    assert v2.version == 2
    assert v2.version_label == "task-1-v2"


def test_creating_a_new_version_does_not_mutate_the_previous_one():
    store = SpecStore()
    v1 = store.create("task-1", goals=["v1 goal"], constraints=[], acceptance_criteria=[])
    store.create("task-1", goals=["v2 goal"], constraints=[], acceptance_criteria=[])
    fetched_v1 = store.get("task-1", 1)
    assert fetched_v1.goals == ("v1 goal",)
    assert v1.goals == ("v1 goal",)


def test_latest_returns_the_most_recent_version():
    store = SpecStore()
    store.create("task-1", goals=["v1"], constraints=[], acceptance_criteria=[])
    v2 = store.create("task-1", goals=["v2"], constraints=[], acceptance_criteria=[])
    assert store.latest("task-1") == v2


def test_latest_on_unknown_spec_id_raises_key_error():
    store = SpecStore()
    with pytest.raises(KeyError):
        store.latest("does-not-exist")


def test_get_unknown_version_raises_key_error():
    store = SpecStore()
    store.create("task-1", goals=["v1"], constraints=[], acceptance_criteria=[])
    with pytest.raises(KeyError):
        store.get("task-1", 99)


def test_assert_current_passes_for_the_latest_version():
    store = SpecStore()
    store.create("task-1", goals=["v1"], constraints=[], acceptance_criteria=[])
    result = store.assert_current("task-1", "task-1-v1")
    assert result.version == 1


def test_assert_current_rejects_a_stale_version_after_amendment():
    store = SpecStore()
    store.create("task-1", goals=["v1"], constraints=[], acceptance_criteria=[])
    store.create("task-1", goals=["v2"], constraints=[], acceptance_criteria=[])
    with pytest.raises(SpecVersionMismatchError) as exc_info:
        store.assert_current("task-1", "task-1-v1")
    assert exc_info.value.expected == "task-1-v2"
    assert exc_info.value.actual == "task-1-v1"


def test_spec_version_is_immutable():
    store = SpecStore()
    spec = store.create("task-1", goals=["v1"], constraints=[], acceptance_criteria=[])
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.goals = ("tampered",)


def test_spec_version_fields_are_tuples_not_lists():
    store = SpecStore()
    spec = store.create("task-1", goals=["v1"], constraints=["c1"], acceptance_criteria=["a1"])
    assert isinstance(spec.goals, tuple)
    assert isinstance(spec.constraints, tuple)
    assert isinstance(spec.acceptance_criteria, tuple)
