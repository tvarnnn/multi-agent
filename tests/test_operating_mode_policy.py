from pathlib import Path

import pytest

from agent_platform.security.enums import OperatingMode, Role, SessionMode, ToolPermission
from agent_platform.security.mode_policy import MODE_POLICIES
from agent_platform.security.permission import PermissionEvaluator, ToolCall
from agent_platform.security.sandbox import FilesystemSandbox


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    project = root / "project"
    project.mkdir(parents=True)
    return project


@pytest.fixture
def evaluator(project: Path) -> PermissionEvaluator:
    return PermissionEvaluator(FilesystemSandbox(project.parent))


def test_all_operating_modes_have_an_immutable_policy():
    assert set(MODE_POLICIES) == set(OperatingMode)
    assert MODE_POLICIES[OperatingMode.CODE].allowed_roles is None
    assert MODE_POLICIES[OperatingMode.EDIT].allowed_tools is None


@pytest.mark.parametrize("mode", [OperatingMode.CODE, OperatingMode.EDIT])
def test_code_and_edit_preserve_existing_permission_behavior(evaluator, project, mode):
    call = ToolCall(Role.CODER, "filesystem.write", "app.py", project)
    implicit = evaluator.evaluate(call, SessionMode.AUTO)
    explicit = evaluator.evaluate(call, SessionMode.AUTO, operating_mode=mode)
    assert explicit == implicit


def test_plan_planner_can_write_only_under_plan_directory(evaluator, project):
    allowed = evaluator.evaluate(
        ToolCall(Role.PLANNER, "filesystem.write", ".agent/plans/draft.md", project),
        SessionMode.AUTO,
        operating_mode=OperatingMode.PLAN,
    )
    denied = evaluator.evaluate(
        ToolCall(Role.PLANNER, "filesystem.write", "src/escape.py", project),
        SessionMode.AUTO,
        operating_mode=OperatingMode.PLAN,
    )
    assert allowed.permission is ToolPermission.ALLOW
    assert denied.permission is ToolPermission.DENY
    assert "sandbox denial" in denied.reason


@pytest.mark.parametrize("tool", ["filesystem.write", "filesystem.create_directory"])
def test_plan_reviewer_cannot_write(evaluator, project, tool):
    decision = evaluator.evaluate(
        ToolCall(Role.REVIEWER, tool, ".agent/plans/draft.md", project),
        SessionMode.AUTO,
        operating_mode=OperatingMode.PLAN,
    )
    assert decision.permission is ToolPermission.DENY


@pytest.mark.parametrize("tool", ["filesystem.read", "filesystem.write", "test.run", "mcp.github.read"])
def test_plan_coder_is_denied_every_tool(evaluator, project, tool):
    decision = evaluator.evaluate(
        ToolCall(Role.CODER, tool, ".agent/plans/draft.md", project),
        SessionMode.AUTO,
        operating_mode=OperatingMode.PLAN,
    )
    assert decision.permission is ToolPermission.DENY
    assert "role not permitted" in decision.reason


@pytest.mark.parametrize(
    ("mode", "role", "tool", "expected"),
    [
        (OperatingMode.CHAT, Role.PLANNER, "filesystem.read", ToolPermission.ALLOW),
        (OperatingMode.CHAT, Role.PLANNER, "filesystem.write", ToolPermission.DENY),
        (OperatingMode.REVIEW, Role.REVIEWER, "filesystem.read", ToolPermission.ALLOW),
        (OperatingMode.REVIEW, Role.REVIEWER, "test.run", ToolPermission.DENY),
    ],
)
def test_read_only_modes_narrow_existing_permissions(evaluator, mode, role, tool, expected):
    decision = evaluator.evaluate(
        ToolCall(role, tool), SessionMode.AUTO, operating_mode=mode
    )
    assert decision.permission is expected

