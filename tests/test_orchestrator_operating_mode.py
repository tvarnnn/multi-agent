import pytest

from agent_platform.events import EventLog
from agent_platform.orchestrator.core import Orchestrator, State
from agent_platform.orchestrator.fake_model import FakeModelProvider
from agent_platform.orchestrator.validation import AcceptanceCriteriaFileValidator
from agent_platform.security.enums import OperatingMode, SessionMode
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


def test_default_operating_mode_is_code_and_unchanged(workspace):
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []}],
        coder_responses=[{"status": "completed", "spec_version_label": "task-1-v1",
                           "summary": "s", "file_writes": [{"path": "app.py", "content": "x"}]}],
        reviewer_responses=[{"spec_version_label": "task-1-v1", "decision": "APPROVE",
                              "requirements_met": True, "security_ok": True,
                              "validation_ok": True, "issues": []}],
    )
    orchestrator, _ = _build_orchestrator(workspace, model)
    result = orchestrator.run("task-1", "build me an app")
    assert result.final_state == State.COMPLETE


def test_run_explicitly_propagates_non_default_operating_mode_to_gateway(workspace):
    # Coder is structurally denied in PLAN mode - if run() ever failed to
    # pass the session's operating_mode through to gateway.invoke, this
    # file write would silently succeed under an implicit CODE fallback.
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []}],
        coder_responses=[{"status": "completed", "spec_version_label": "task-1-v1",
                           "summary": "s", "file_writes": [{"path": "app.py", "content": "x"}]}],
    )
    orchestrator, _ = _build_orchestrator(workspace, model, operating_mode=OperatingMode.PLAN)
    result = orchestrator.run("task-1", "build me an app")
    assert result.final_state == State.ESCALATE_TO_USER
    assert "file write failed" in result.summary
    assert not (workspace / "MyProj" / "app.py").exists()
