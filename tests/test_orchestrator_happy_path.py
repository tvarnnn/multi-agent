import pytest

from agent_platform.events import EventLog
from agent_platform.orchestrator.core import Orchestrator, State
from agent_platform.orchestrator.fake_model import FakeModelProvider
from agent_platform.orchestrator.validation import AcceptanceCriteriaFileValidator
from agent_platform.security.enums import Role, SessionMode
from agent_platform.security.permission import PermissionEvaluator
from agent_platform.security.sandbox import FilesystemSandbox
from agent_platform.spec.versioning import SpecStore
from agent_platform.tools.gateway import ToolGateway
from agent_platform.tools.registry import build_default_registry


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    (root / "MyProj").mkdir()
    return root


def _build_orchestrator(workspace, model, **overrides):
    sandbox = FilesystemSandbox(workspace)
    evaluator = PermissionEvaluator(sandbox)
    event_log = EventLog()
    gateway = ToolGateway(build_default_registry(), evaluator, event_log)
    kwargs = dict(
        gateway=gateway, model=model, spec_store=SpecStore(), event_log=event_log,
        session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve(),
        validator=AcceptanceCriteriaFileValidator(),
    )
    kwargs.update(overrides)
    return Orchestrator(**kwargs), event_log


def test_full_happy_path_reaches_complete(workspace):
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["build app"], "constraints": [],
                             "acceptance_criteria": ["file:app.py"]}],
        coder_responses=[{"status": "completed", "spec_version_label": "task-1-v1",
                           "summary": "wrote app.py",
                           "file_writes": [{"path": "app.py", "content": "print('hi')"}]}],
        reviewer_responses=[{"spec_version_label": "task-1-v1", "decision": "APPROVE",
                              "requirements_met": True, "security_ok": True,
                              "validation_ok": True, "issues": []}],
    )
    orchestrator, _ = _build_orchestrator(workspace, model)
    result = orchestrator.run("task-1", "build me an app")
    assert result.final_state == State.COMPLETE
    assert (workspace / "MyProj" / "app.py").read_text(encoding="utf-8") == "print('hi')"


def test_final_validation_gate_fails_despite_reviewer_approval_and_returns_to_feedback(workspace):
    # Reviewer approves but the deterministic gate (missing acceptance file)
    # still fails - FINAL_VALIDATION must not treat approval alone as enough.
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["build app"], "constraints": [],
                             "acceptance_criteria": ["file:app.py"]}],
        coder_responses=[
            {"status": "completed", "spec_version_label": "task-1-v1", "summary": "wrote wrong file",
             "file_writes": [{"path": "wrong.py", "content": "x"}]},
            {"status": "completed", "spec_version_label": "task-1-v1", "summary": "wrote app.py",
             "file_writes": [{"path": "app.py", "content": "x"}]},
        ],
        reviewer_responses=[
            {"spec_version_label": "task-1-v1", "decision": "APPROVE", "requirements_met": True,
             "security_ok": True, "validation_ok": True, "issues": []},
            {"spec_version_label": "task-1-v1", "decision": "APPROVE", "requirements_met": True,
             "security_ok": True, "validation_ok": True, "issues": []},
        ],
    )
    orchestrator, _ = _build_orchestrator(workspace, model)
    result = orchestrator.run("task-1", "build me an app")
    assert result.final_state == State.COMPLETE
    assert (workspace / "MyProj" / "app.py").exists()


def test_state_transitions_are_logged_in_order(workspace):
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []}],
        coder_responses=[{"status": "completed", "spec_version_label": "task-1-v1",
                           "summary": "s", "file_writes": []}],
        reviewer_responses=[{"spec_version_label": "task-1-v1", "decision": "APPROVE",
                              "requirements_met": True, "security_ok": True,
                              "validation_ok": True, "issues": []}],
    )
    orchestrator, event_log = _build_orchestrator(workspace, model)
    orchestrator.run("task-1", "build me an app")
    transitions = [e.payload["to"] for e in event_log.internal_stream()
                   if e.event_type.name == "STATE_TRANSITION"]
    assert transitions == ["PLAN", "VALIDATE_PLAN", "IMPLEMENT", "TEST", "REVIEW",
                            "FINAL_VALIDATION", "COMPLETE"]


def test_user_and_internal_streams_stay_separated(workspace):
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []}],
        coder_responses=[{"status": "completed", "spec_version_label": "task-1-v1",
                           "summary": "s", "file_writes": []}],
        reviewer_responses=[{"spec_version_label": "task-1-v1", "decision": "APPROVE",
                              "requirements_met": True, "security_ok": True,
                              "validation_ok": True, "issues": []}],
    )
    orchestrator, event_log = _build_orchestrator(workspace, model)
    orchestrator.run("task-1", "build me an app")
    assert len(event_log.user_stream()) >= 1
    assert all(e.event_type.name != "STATE_TRANSITION" for e in event_log.user_stream())
    assert all(e.event_type.name != "TOOL_INVOKED" or e.stream == "internal"
               for e in event_log.events())
