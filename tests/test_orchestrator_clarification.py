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


def test_coder_blocked_then_clarified_then_completes(workspace):
    model = FakeModelProvider(
        planner_responses=[
            {"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []},
            {"kind": "spec", "goals": ["g", "use OAuth"], "constraints": [], "acceptance_criteria": []},
        ],
        coder_responses=[
            {"status": "blocked", "spec_version_label": "task-1-v1", "reason": "ambiguous auth",
             "attempted": "read existing code", "blocking_questions": ["OAuth or API keys?"]},
            {"status": "completed", "spec_version_label": "task-1-v2", "summary": "used OAuth",
             "file_writes": []},
        ],
        reviewer_responses=[{"spec_version_label": "task-1-v2", "decision": "APPROVE",
                              "requirements_met": True, "security_ok": True,
                              "validation_ok": True, "issues": []}],
    )
    orchestrator, event_log = _build_orchestrator(workspace, model)
    result = orchestrator.run("task-1", "build an app with login")
    assert result.final_state == State.COMPLETE
    transitions = [e.payload["to"] for e in event_log.internal_stream() if e.event_type.name == "STATE_TRANSITION"]
    assert "BLOCKED" in transitions
    assert "RESOLVE_CLARIFICATION" in transitions


def test_planner_itself_needs_user_input_during_clarification(workspace):
    model = FakeModelProvider(
        planner_responses=[
            {"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []},
            {"kind": "needs_user_input", "question": "OAuth or API keys?"},
        ],
        coder_responses=[
            {"status": "blocked", "spec_version_label": "task-1-v1", "reason": "ambiguous auth",
             "attempted": "read existing code", "blocking_questions": ["OAuth or API keys?"]},
        ],
        reviewer_responses=[],
    )
    orchestrator, _ = _build_orchestrator(workspace, model)
    result = orchestrator.run("task-1", "build an app with login")
    assert result.final_state == State.AWAITING_USER_INPUT
    assert result.summary == "OAuth or API keys?"


def test_repeated_blocking_beyond_cap_escalates_to_stuck(workspace):
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []}]
        + [{"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []} for _ in range(5)],
        coder_responses=[
            {"status": "blocked", "spec_version_label": f"task-1-v{i}", "reason": "still ambiguous",
             "attempted": "tried again", "blocking_questions": ["still unclear"]}
            for i in range(1, 6)
        ],
        reviewer_responses=[],
    )
    orchestrator, event_log = _build_orchestrator(workspace, model, max_clarification_rounds=3)
    result = orchestrator.run("task-1", "build something vague")
    assert result.final_state == State.ESCALATE_TO_USER
    transitions = [e.payload["to"] for e in event_log.internal_stream() if e.event_type.name == "STATE_TRANSITION"]
    assert transitions[-2:] == ["STUCK", "ESCALATE_TO_USER"]


def test_coder_pinned_to_stale_spec_version_is_deterministically_rejected(workspace):
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []}],
        coder_responses=[{"status": "completed", "spec_version_label": "task-1-v99",
                           "summary": "s", "file_writes": []}],
        reviewer_responses=[],
    )
    orchestrator, event_log = _build_orchestrator(workspace, model)
    result = orchestrator.run("task-1", "build an app")
    assert result.final_state == State.ESCALATE_TO_USER
    assert "version" in result.summary.lower()
    mismatches = [e for e in event_log.internal_stream() if e.event_type.name == "SPEC_VERSION_MISMATCH"]
    assert len(mismatches) == 1


def test_reviewer_pinned_to_stale_spec_version_is_deterministically_rejected(workspace):
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []}],
        coder_responses=[{"status": "completed", "spec_version_label": "task-1-v1",
                           "summary": "s", "file_writes": []}],
        reviewer_responses=[{"spec_version_label": "task-1-v0", "decision": "APPROVE",
                              "requirements_met": True, "security_ok": True,
                              "validation_ok": True, "issues": []}],
    )
    orchestrator, _ = _build_orchestrator(workspace, model)
    result = orchestrator.run("task-1", "build an app")
    assert result.final_state == State.ESCALATE_TO_USER


def test_malformed_planner_output_retries_then_succeeds(workspace):
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec"}, {"kind": "spec", "goals": ["g"], "constraints": [],
                                                "acceptance_criteria": []}],
        coder_responses=[{"status": "completed", "spec_version_label": "task-1-v1", "summary": "s",
                           "file_writes": []}],
        reviewer_responses=[{"spec_version_label": "task-1-v1", "decision": "APPROVE",
                              "requirements_met": True, "security_ok": True,
                              "validation_ok": True, "issues": []}],
    )
    orchestrator, event_log = _build_orchestrator(workspace, model)
    result = orchestrator.run("task-1", "build an app")
    assert result.final_state == State.COMPLETE
    invalid_events = [e for e in event_log.internal_stream() if e.event_type.name == "MODEL_OUTPUT_INVALID"]
    assert len(invalid_events) == 1


def test_malformed_planner_output_exhausting_retries_escalates(workspace):
    model = FakeModelProvider(planner_responses=[{"kind": "spec"}] * 3)
    orchestrator, _ = _build_orchestrator(workspace, model, max_output_retries=3)
    result = orchestrator.run("task-1", "build an app")
    assert result.final_state == State.ESCALATE_TO_USER


def test_model_timeout_is_retried_then_can_succeed(workspace):
    from agent_platform.orchestrator.fake_model import TIMEOUT
    model = FakeModelProvider(
        planner_responses=[TIMEOUT, {"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []}],
        coder_responses=[{"status": "completed", "spec_version_label": "task-1-v1", "summary": "s",
                           "file_writes": []}],
        reviewer_responses=[{"spec_version_label": "task-1-v1", "decision": "APPROVE",
                              "requirements_met": True, "security_ok": True,
                              "validation_ok": True, "issues": []}],
    )
    orchestrator, _ = _build_orchestrator(workspace, model)
    result = orchestrator.run("task-1", "build an app")
    assert result.final_state == State.COMPLETE


def test_tool_failure_on_writing_outside_scope_escalates(workspace, tmp_path):
    outside = str(tmp_path / "Outside" / "evil.py")
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []}],
        coder_responses=[{"status": "completed", "spec_version_label": "task-1-v1", "summary": "s",
                           "file_writes": [{"path": outside, "content": "malicious"}]}],
        reviewer_responses=[],
    )
    orchestrator, _ = _build_orchestrator(workspace, model)
    result = orchestrator.run("task-1", "build an app")
    assert result.final_state == State.ESCALATE_TO_USER
    assert not (tmp_path / "Outside").exists()


def test_reviewer_rejection_then_fix_then_approve(workspace):
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []}],
        coder_responses=[
            {"status": "completed", "spec_version_label": "task-1-v1", "summary": "v1",
             "file_writes": [{"path": "app.py", "content": "bug"}]},
            {"status": "completed", "spec_version_label": "task-1-v1", "summary": "v2 fixed",
             "file_writes": [{"path": "app.py", "content": "fixed"}]},
        ],
        reviewer_responses=[
            {"spec_version_label": "task-1-v1", "decision": "REJECT", "requirements_met": False,
             "security_ok": True, "validation_ok": True,
             "issues": [{"severity": "high", "file": "app.py", "description": "bug",
                         "required_fix": "fix it"}]},
            {"spec_version_label": "task-1-v1", "decision": "APPROVE", "requirements_met": True,
             "security_ok": True, "validation_ok": True, "issues": []},
        ],
    )
    orchestrator, event_log = _build_orchestrator(workspace, model)
    result = orchestrator.run("task-1", "build an app")
    assert result.final_state == State.COMPLETE
    assert (workspace / "MyProj" / "app.py").read_text(encoding="utf-8") == "fixed"
    transitions = [e.payload["to"] for e in event_log.internal_stream() if e.event_type.name == "STATE_TRANSITION"]
    assert "FEEDBACK" in transitions and "IMPLEMENT_FIX" in transitions


def test_repeated_rejection_beyond_cap_escalates_to_stuck(workspace):
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []}],
        coder_responses=[
            {"status": "completed", "spec_version_label": "task-1-v1", "summary": f"attempt {i}",
             "file_writes": []} for i in range(1, 6)
        ],
        reviewer_responses=[
            {"spec_version_label": "task-1-v1", "decision": "REJECT", "requirements_met": False,
             "security_ok": True, "validation_ok": True,
             "issues": [{"severity": "high", "file": "app.py", "description": "still broken",
                         "required_fix": "fix it"}]} for _ in range(5)
        ],
    )
    orchestrator, _ = _build_orchestrator(workspace, model, max_fix_iterations=3)
    result = orchestrator.run("task-1", "build an app")
    assert result.final_state == State.ESCALATE_TO_USER


def test_amend_requirements_creates_new_spec_version_and_reimplements(workspace):
    model = FakeModelProvider(
        planner_responses=[
            {"kind": "spec", "goals": ["g1"], "constraints": [], "acceptance_criteria": []},
            {"kind": "spec", "goals": ["g1", "g2 - use sqlite"], "constraints": [], "acceptance_criteria": []},
        ],
        coder_responses=[
            {"status": "completed", "spec_version_label": "task-1-v1", "summary": "v1", "file_writes": []},
            {"status": "completed", "spec_version_label": "task-1-v2", "summary": "v2 with sqlite",
             "file_writes": []},
        ],
        reviewer_responses=[
            {"spec_version_label": "task-1-v1", "decision": "APPROVE", "requirements_met": True,
             "security_ok": True, "validation_ok": True, "issues": []},
            {"spec_version_label": "task-1-v2", "decision": "APPROVE", "requirements_met": True,
             "security_ok": True, "validation_ok": True, "issues": []},
        ],
    )
    orchestrator, event_log = _build_orchestrator(workspace, model)
    first = orchestrator.run("task-1", "build an app")
    assert first.final_state == State.COMPLETE
    second = orchestrator.amend_requirements("task-1", "actually use sqlite")
    assert second.final_state == State.COMPLETE
    version_events = [e.payload["version_label"] for e in event_log.internal_stream()
                       if e.event_type.name == "SPEC_VERSION_CREATED"]
    assert version_events == ["task-1-v1", "task-1-v2"]
    transitions = [e.payload["to"] for e in event_log.internal_stream() if e.event_type.name == "STATE_TRANSITION"]
    assert "AMEND_REQUIREMENTS" in transitions
