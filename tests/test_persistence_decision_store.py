import pytest

from agent_platform.persistence.db import ensure_schema, resolve_agent_paths
from agent_platform.persistence.decision_store import DecisionStore, DecisionValidationError
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
    return DecisionStore(db_path)


def test_append_plan_approved_round_trips(store, session_id):
    record = store.append(session_id=session_id, event_type="PLAN_APPROVED",
                           payload={"spec_id": "spec-1", "path": ".agent/plans/x.md"})
    assert record.event_type == "PLAN_APPROVED"
    assert record.payload == {"spec_id": "spec-1", "path": ".agent/plans/x.md"}
    assert record.seq == 1


def test_append_mints_sequential_seq(store, session_id):
    store.append(session_id=session_id, event_type="PLAN_CREATED", payload={"spec_id": "spec-1", "path": "p.md"})
    r2 = store.append(session_id=session_id, event_type="PLAN_REVISED", payload={"spec_id": "spec-1", "path": "p.md"})
    assert r2.seq == 2


def test_append_unknown_event_type_rejected(store, session_id):
    with pytest.raises(DecisionValidationError):
        store.append(session_id=session_id, event_type="NOT_A_REAL_EVENT", payload={})


def test_append_rejects_unallowlisted_payload_key(store, session_id):
    with pytest.raises(DecisionValidationError):
        store.append(session_id=session_id, event_type="PLAN_APPROVED",
                      payload={"spec_id": "spec-1", "path": "p.md", "unexpected_field": "danger"})


def test_append_rejects_non_json_serializable_payload_value(store, session_id):
    with pytest.raises(DecisionValidationError):
        store.append(session_id=session_id, event_type="SPEC_VERSION_CREATED",
                      payload={"version_label": object()})


@pytest.mark.parametrize("event_type,payload", [
    ("PLAN_CREATED", {"spec_id": "spec-1", "path": "p.md"}),
    ("PLAN_REVISED", {"spec_id": "spec-1", "path": "p.md"}),
    ("PLAN_APPROVED", {"spec_id": "spec-1", "path": "p.md"}),
    ("PLAN_REJECTED", {"spec_id": "spec-1", "path": "p.md", "reason": "not needed"}),
    ("PLAN_ARTIFACT_WRITTEN", {"spec_id": "spec-1", "path": "p.md", "status": "DRAFT"}),
    ("PLAN_REVIEWED", {"spec_id": "spec-1"}),
    ("SPEC_VERSION_CREATED", {"version_label": "spec-1-v1"}),
])
def test_all_allowlisted_event_types_accepted(store, session_id, event_type, payload):
    record = store.append(session_id=session_id, event_type=event_type, payload=payload)
    assert record.event_type == event_type
    assert record.payload == payload


def test_since_returns_ordered_by_seq(store, session_id):
    store.append(session_id=session_id, event_type="PLAN_CREATED", payload={"spec_id": "spec-1", "path": "p.md"})
    store.append(session_id=session_id, event_type="PLAN_REVISED", payload={"spec_id": "spec-1", "path": "p.md"})
    store.append(session_id=session_id, event_type="PLAN_APPROVED", payload={"spec_id": "spec-1", "path": "p.md"})
    result = store.since(session_id, since_seq=1)
    assert [r.event_type for r in result] == ["PLAN_REVISED", "PLAN_APPROVED"]
