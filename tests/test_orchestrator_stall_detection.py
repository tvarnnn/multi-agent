import pytest

from agent_platform.events import EventLog
from agent_platform.orchestrator.core import Orchestrator, State
from agent_platform.orchestrator.fake_model import FakeModelProvider
from agent_platform.orchestrator.validation import AcceptanceCriteriaFileValidator
from agent_platform.security.enums import SessionMode
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


def test_identical_fix_attempt_escalates_without_waiting_for_the_full_iteration_cap(workspace):
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []}],
        coder_responses=[
            {"status": "completed", "spec_version_label": "task-1-v1", "summary": "attempt 1",
             "file_writes": [{"path": "app.py", "content": "same content every time"}]},
            {"status": "completed", "spec_version_label": "task-1-v1", "summary": "attempt 2 (identical)",
             "file_writes": [{"path": "app.py", "content": "same content every time"}]},
        ],
        reviewer_responses=[
            {"spec_version_label": "task-1-v1", "decision": "REJECT", "requirements_met": False,
             "security_ok": True, "validation_ok": True,
             "issues": [{"severity": "high", "file": "app.py", "description": "still wrong",
                         "required_fix": "change it"}]},
        ],
    )
    orchestrator, event_log = _build_orchestrator(workspace, model, max_fix_iterations=5)
    result = orchestrator.run("task-1", "build an app")
    assert result.final_state == State.ESCALATE_TO_USER
    assert "negligible" in result.summary.lower()
    # Only 2 coder calls and 1 reviewer call were needed - proof this
    # stopped well before the max_fix_iterations=5 cap would have.
    transitions = [e.payload["to"] for e in event_log.internal_stream() if e.event_type.name == "STATE_TRANSITION"]
    assert transitions.count("IMPLEMENT_FIX") == 1


def test_repeated_identical_review_rejection_escalates_early(workspace):
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []}],
        coder_responses=[
            {"status": "completed", "spec_version_label": "task-1-v1", "summary": f"attempt {i}",
             "file_writes": [{"path": "app.py", "content": f"version {i}"}]} for i in range(1, 4)
        ],
        reviewer_responses=[
            {"spec_version_label": "task-1-v1", "decision": "REJECT", "requirements_met": False,
             "security_ok": True, "validation_ok": True,
             "issues": [{"severity": "high", "file": "app.py", "description": "same root cause",
                         "required_fix": "fix root cause"}]} for _ in range(3)
        ],
    )
    orchestrator, _ = _build_orchestrator(workspace, model, max_fix_iterations=5)
    result = orchestrator.run("task-1", "build an app")
    assert result.final_state == State.ESCALATE_TO_USER
    assert "repeated" in result.summary.lower() or "same" in result.summary.lower()


def test_genuinely_different_fix_attempts_are_not_flagged_as_stalled(workspace):
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []}],
        coder_responses=[
            {"status": "completed", "spec_version_label": "task-1-v1", "summary": "v1",
             "file_writes": [{"path": "app.py", "content": "buggy version"}]},
            {"status": "completed", "spec_version_label": "task-1-v1", "summary": "v2 fixed",
             "file_writes": [{"path": "app.py", "content": "corrected version"}]},
        ],
        reviewer_responses=[
            {"spec_version_label": "task-1-v1", "decision": "REJECT", "requirements_met": False,
             "security_ok": True, "validation_ok": True,
             "issues": [{"severity": "high", "file": "app.py", "description": "has a bug",
                         "required_fix": "fix the bug"}]},
            {"spec_version_label": "task-1-v1", "decision": "APPROVE", "requirements_met": True,
             "security_ok": True, "validation_ok": True, "issues": []},
        ],
    )
    orchestrator, _ = _build_orchestrator(workspace, model, max_fix_iterations=5)
    result = orchestrator.run("task-1", "build an app")
    assert result.final_state == State.COMPLETE
