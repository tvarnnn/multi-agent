"""Part 10's event/stream contract, audited and extended additively: the
existing SSE route (GET /sessions/{id}/events, unchanged in its own
event-selection logic) only ever replayed EventLog.user_stream() - plain
conversational text, no structured progress. This adds structured,
already-persisted decision events (PLAN_CREATED/PLAN_APPROVED/etc, Phase
10's `decisions` table - itself only ever populated from already-typed
route-handler results, never from draining internal reasoning) into the
same stream, normalized to one stable shape: session_id, event_type,
timestamp, safe payload, spec_version_label where applicable. No change
to orchestrator/core.py or events.py's stream assignments.
"""
import pytest
from fastapi.testclient import TestClient

from agent_platform.backend_api import BackendServices, create_app
from agent_platform.events import EventLog
from agent_platform.orchestrator.fake_model import FakeModelProvider
from agent_platform.orchestrator.validation import AcceptanceCriteriaFileValidator
from agent_platform.persistence.db import ensure_schema, resolve_agent_paths
from agent_platform.persistence.service import SessionPersistenceService
from agent_platform.security.enums import SessionMode
from agent_platform.security.permission import PermissionEvaluator
from agent_platform.security.sandbox import FilesystemSandbox
from agent_platform.settings.service import SettingsService
from agent_platform.spec.versioning import SpecStore
from agent_platform.tools.gateway import ToolGateway
from agent_platform.tools.registry import build_default_registry

TOKEN = "test-token-abc123"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _plan_dict(**overrides):
    d = {
        "kind": "plan", "objective": "Build the widget", "requirements": ["req1"],
        "existing_context": [], "proposed_architecture": "single module",
        "files_to_create": ["widget.py"], "files_to_modify": [], "dependencies": [],
        "implementation_steps": ["step1"], "validation_strategy": ["test1"],
        "risks": [], "unknowns": [], "acceptance_criteria": ["file:widget.py"],
    }
    d.update(overrides)
    return d


def _review_dict():
    return {"comments": [], "missing_requirements": [], "security_concerns": [], "unnecessary_complexity": []}


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    (root / "MyProj").mkdir()
    return root


def _services(workspace, model=None):
    sandbox = FilesystemSandbox(workspace)
    evaluator = PermissionEvaluator(sandbox)
    registry = build_default_registry()
    project_root = (workspace / "MyProj").resolve()
    spec_store = SpecStore()
    paths = resolve_agent_paths(sandbox, project_root, ".agent")
    ensure_schema(paths.db_path, project_root)
    persistence = SessionPersistenceService(
        db_path=paths.db_path, sandbox=sandbox, project_root=project_root,
        checkpoints_relative_dir=".agent/context/checkpoints",
        gateway=ToolGateway(registry, evaluator, EventLog()), spec_store=spec_store,
    )
    settings = SettingsService.load(global_path=None, workspace_path=None)
    return BackendServices(
        project_root=project_root, spec_store=spec_store, model=model or FakeModelProvider(),
        validator=AcceptanceCriteriaFileValidator(), registry=registry, evaluator=evaluator,
        sandbox=sandbox, persistence=persistence, settings=settings, session_mode=SessionMode.AUTO,
    )


def _client(workspace, **kwargs):
    return TestClient(create_app(_services(workspace, **kwargs), TOKEN))


def _sse_events(resp) -> list:
    import json
    events = []
    for line in resp.text.split("\n"):
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


def test_events_stream_includes_structured_plan_decisions(workspace):
    model = FakeModelProvider(plan_mode_responses=[_plan_dict()], review_plan_responses=[_review_dict()])
    client = _client(workspace, model=model)
    session_id = client.post("/sessions", json={"operating_mode": "PLAN", "spec_id": "spec-1"},
                              headers=AUTH).json()["session_id"]
    client.post(f"/sessions/{session_id}/messages", json={"message": "build a widget"}, headers=AUTH)
    client.post(f"/sessions/{session_id}/plan/approve", headers=AUTH)

    resp = client.get(f"/sessions/{session_id}/events", headers=AUTH)
    events = _sse_events(resp)
    event_types = {e["event_type"] for e in events}
    assert "PLAN_CREATED" in event_types
    assert "PLAN_APPROVED" in event_types
    assert "SPEC_VERSION_CREATED" in event_types


def test_every_event_has_the_stable_contract_fields(workspace):
    model = FakeModelProvider(chat_responses=[{"message": "hi there"}])
    client = _client(workspace, model=model)
    session_id = client.post("/sessions", json={"operating_mode": "CHAT"}, headers=AUTH).json()["session_id"]
    client.post(f"/sessions/{session_id}/messages", json={"message": "hello"}, headers=AUTH)

    resp = client.get(f"/sessions/{session_id}/events", headers=AUTH)
    events = _sse_events(resp)
    assert events
    for event in events:
        assert set(event.keys()) == {"session_id", "event_type", "timestamp", "payload", "spec_version_label"}
        assert event["session_id"] == session_id


def test_spec_version_created_event_carries_the_version_label(workspace):
    model = FakeModelProvider(plan_mode_responses=[_plan_dict()], review_plan_responses=[_review_dict()])
    client = _client(workspace, model=model)
    session_id = client.post("/sessions", json={"operating_mode": "PLAN", "spec_id": "spec-1"},
                              headers=AUTH).json()["session_id"]
    client.post(f"/sessions/{session_id}/messages", json={"message": "build a widget"}, headers=AUTH)
    client.post(f"/sessions/{session_id}/plan/approve", headers=AUTH)

    resp = client.get(f"/sessions/{session_id}/events", headers=AUTH)
    events = _sse_events(resp)
    spec_event = next(e for e in events if e["event_type"] == "SPEC_VERSION_CREATED")
    assert spec_event["spec_version_label"] == "spec-1-v1"


def test_events_never_include_internal_model_reasoning_events(workspace):
    """Regression guard: MODEL_OUTPUT_INVALID/STATE_TRANSITION/INTERNAL stay
    excluded - only the whitelisted decision event_types Phase 10 already
    persists (see decision_store.py's PAYLOAD_ALLOWLIST) can appear."""
    from agent_platform.persistence.decision_store import PAYLOAD_ALLOWLIST
    model = FakeModelProvider(chat_responses=[{"message": "hi there"}])
    client = _client(workspace, model=model)
    session_id = client.post("/sessions", json={"operating_mode": "CHAT"}, headers=AUTH).json()["session_id"]
    client.post(f"/sessions/{session_id}/messages", json={"message": "hello"}, headers=AUTH)

    resp = client.get(f"/sessions/{session_id}/events", headers=AUTH)
    events = _sse_events(resp)
    for event in events:
        assert event["event_type"] in {"USER_REQUEST_RECEIVED", "USER_MESSAGE", *PAYLOAD_ALLOWLIST.keys()}


def test_events_are_still_isolated_per_session(workspace):
    model = FakeModelProvider(chat_responses=[{"message": "reply-a"}, {"message": "reply-b"}])
    client = _client(workspace, model=model)
    a = client.post("/sessions", json={"operating_mode": "CHAT"}, headers=AUTH).json()["session_id"]
    b = client.post("/sessions", json={"operating_mode": "CHAT"}, headers=AUTH).json()["session_id"]
    client.post(f"/sessions/{a}/messages", json={"message": "hello from a"}, headers=AUTH)

    events_a = _sse_events(client.get(f"/sessions/{a}/events", headers=AUTH))
    events_b = _sse_events(client.get(f"/sessions/{b}/events", headers=AUTH))
    assert any("hello from a" in str(e["payload"]) for e in events_a)
    assert not any("hello from a" in str(e["payload"]) for e in events_b)
