import pytest

from agent_platform.events import EventLog
from agent_platform.orchestrator.validation import (
    AcceptanceCriteriaFileValidator,
    CompositeValidator,
    TestRunValidator,
)
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


@pytest.fixture
def gateway(workspace):
    sandbox = FilesystemSandbox(workspace)
    evaluator = PermissionEvaluator(sandbox)
    return ToolGateway(build_default_registry(), evaluator, EventLog())


def _spec():
    return SpecStore().create("task-1", goals=["g"], constraints=[], acceptance_criteria=[])


def test_passes_when_the_real_test_suite_passes(gateway, workspace):
    proj = workspace / "MyProj"
    (proj / "test_sample.py").write_text("def test_ok():\n    assert 1 == 1\n")
    validator = TestRunValidator(gateway, Role.REVIEWER, SessionMode.AUTO)
    result = validator.validate(proj.resolve(), _spec())
    assert result.passed


def test_fails_when_the_real_test_suite_fails(gateway, workspace):
    proj = workspace / "MyProj"
    (proj / "test_sample.py").write_text("def test_fail():\n    assert False\n")
    validator = TestRunValidator(gateway, Role.REVIEWER, SessionMode.AUTO)
    result = validator.validate(proj.resolve(), _spec())
    assert not result.passed


def test_composite_validator_requires_all_to_pass(gateway, workspace):
    proj = workspace / "MyProj"
    (proj / "app.py").write_text("x = 1\n")
    (proj / "test_sample.py").write_text("def test_fail():\n    assert False\n")
    spec = SpecStore().create("task-2", goals=["g"], constraints=[], acceptance_criteria=["file:app.py"])
    composite = CompositeValidator((
        AcceptanceCriteriaFileValidator(),          # passes - app.py exists
        TestRunValidator(gateway, Role.REVIEWER, SessionMode.AUTO),  # fails - test_fail
    ))
    result = composite.validate(proj.resolve(), spec)
    assert not result.passed
    assert len(result.details) >= 2  # details from both validators are present
