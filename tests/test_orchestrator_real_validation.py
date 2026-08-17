import pytest

from agent_platform.events import EventLog
from agent_platform.orchestrator.core import Orchestrator, State
from agent_platform.orchestrator.fake_model import FakeModelProvider
from agent_platform.orchestrator.validation import TestRunValidator
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


def test_reviewer_approval_does_not_override_a_real_failing_test(workspace):
    sandbox = FilesystemSandbox(workspace)
    evaluator = PermissionEvaluator(sandbox)
    event_log = EventLog()
    gateway = ToolGateway(build_default_registry(), evaluator, event_log)
    # The model is scripted to APPROVE every time - a maximally
    # permissive reviewer. Real test.run must still gate completion.
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["g"], "constraints": [],
                             "acceptance_criteria": []}],
        coder_responses=[
            {"status": "completed", "spec_version_label": "task-1-v1", "summary": "s",
             "file_writes": [{"path": "test_sample.py",
                               "content": "def test_fail():\n    assert False\n"}]}
            for _ in range(3)
        ],
        reviewer_responses=[
            {"spec_version_label": "task-1-v1", "decision": "APPROVE", "requirements_met": True,
             "security_ok": True, "validation_ok": True, "issues": []}
            for _ in range(3)
        ],
    )
    orchestrator = Orchestrator(
        gateway=gateway, model=model, spec_store=SpecStore(), event_log=event_log,
        session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve(),
        validator=TestRunValidator(gateway, Role.REVIEWER, SessionMode.AUTO),
        max_fix_iterations=2,
    )
    result = orchestrator.run("task-1", "build something with a failing test")
    # Reviewer approved every single time; the real test never passed;
    # the orchestrator must NOT reach COMPLETE.
    assert result.final_state == State.ESCALATE_TO_USER
