import pytest

from agent_platform.security.enums import Role, SessionMode, ToolPermission
from agent_platform.security.permission import (
    ABSOLUTE_DENY_TOOLS,
    PermissionEvaluator,
    ToolCall,
)
from agent_platform.security.sandbox import FilesystemSandbox


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    (root / "MyProj").mkdir()
    return root


@pytest.fixture
def evaluator(workspace):
    sandbox = FilesystemSandbox(workspace)
    return PermissionEvaluator(sandbox)


def test_coder_filesystem_write_allowed_in_auto_mode(evaluator, workspace):
    call = ToolCall(role=Role.CODER, tool_name="filesystem.write",
                     path_argument="MyProj/app.py", scope_root=(workspace / "MyProj").resolve())
    decision = evaluator.evaluate(call, SessionMode.AUTO)
    assert decision.permission == ToolPermission.ALLOW


def test_planner_filesystem_write_is_denied(evaluator, workspace):
    call = ToolCall(role=Role.PLANNER, tool_name="filesystem.write",
                     path_argument="MyProj/app.py", scope_root=(workspace / "MyProj").resolve())
    decision = evaluator.evaluate(call, SessionMode.AUTO)
    assert decision.permission == ToolPermission.DENY


def test_reviewer_filesystem_write_is_denied(evaluator, workspace):
    call = ToolCall(role=Role.REVIEWER, tool_name="filesystem.write",
                     path_argument="MyProj/app.py", scope_root=(workspace / "MyProj").resolve())
    decision = evaluator.evaluate(call, SessionMode.AUTO)
    assert decision.permission == ToolPermission.DENY


@pytest.mark.parametrize("role", list(Role))
def test_filesystem_read_allowed_for_every_role(evaluator, role):
    call = ToolCall(role=role, tool_name="filesystem.read", path_argument="MyProj/app.py")
    decision = evaluator.evaluate(call, SessionMode.AUTO)
    assert decision.permission == ToolPermission.ALLOW


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize("mode", list(SessionMode))
@pytest.mark.parametrize("tool", sorted(ABSOLUTE_DENY_TOOLS))
def test_absolute_deny_tools_are_always_denied(evaluator, role, mode, tool):
    call = ToolCall(role=role, tool_name=tool)
    decision = evaluator.evaluate(call, mode)
    assert decision.permission == ToolPermission.DENY


def test_unknown_tool_name_defaults_to_deny(evaluator):
    call = ToolCall(role=Role.CODER, tool_name="totally.made.up")
    decision = evaluator.evaluate(call, SessionMode.AUTO)
    assert decision.permission == ToolPermission.DENY


def test_allow_tool_with_denied_path_is_still_denied(evaluator, workspace, tmp_path):
    # Proves evaluation is NOT tool-name-only: filesystem.write is ALLOW
    # for CODER in principle, but a path escaping the project scope must
    # still deny the call.
    outside = tmp_path / "Outside" / "file.txt"
    call = ToolCall(role=Role.CODER, tool_name="filesystem.write",
                     path_argument=str(outside), scope_root=(workspace / "MyProj").resolve())
    decision = evaluator.evaluate(call, SessionMode.AUTO)
    assert decision.permission == ToolPermission.DENY


def test_confirmation_mode_downgrades_allow_to_confirm(evaluator, workspace):
    call = ToolCall(role=Role.CODER, tool_name="filesystem.write",
                     path_argument="MyProj/app.py", scope_root=(workspace / "MyProj").resolve())
    decision = evaluator.evaluate(call, SessionMode.CONFIRMATION)
    assert decision.permission == ToolPermission.CONFIRM


def test_manual_mode_downgrades_allow_to_confirm(evaluator, workspace):
    call = ToolCall(role=Role.CODER, tool_name="filesystem.write",
                     path_argument="MyProj/app.py", scope_root=(workspace / "MyProj").resolve())
    decision = evaluator.evaluate(call, SessionMode.MANUAL)
    assert decision.permission == ToolPermission.CONFIRM


@pytest.mark.parametrize("mode", list(SessionMode))
def test_deny_is_never_loosened_by_any_session_mode(evaluator, mode):
    call = ToolCall(role=Role.PLANNER, tool_name="filesystem.write", path_argument="MyProj/app.py")
    decision = evaluator.evaluate(call, mode)
    assert decision.permission == ToolPermission.DENY


def test_resolved_path_populated_on_allow(evaluator, workspace):
    call = ToolCall(role=Role.CODER, tool_name="filesystem.write",
                     path_argument="app.py", scope_root=(workspace / "MyProj").resolve())
    decision = evaluator.evaluate(call, SessionMode.AUTO)
    assert decision.resolved_path == (workspace / "MyProj" / "app.py").resolve()


def test_resolved_path_none_on_deny(evaluator, workspace):
    call = ToolCall(role=Role.PLANNER, tool_name="filesystem.write",
                     path_argument="MyProj/app.py", scope_root=(workspace / "MyProj").resolve())
    decision = evaluator.evaluate(call, SessionMode.AUTO)
    assert decision.resolved_path is None


@pytest.mark.parametrize("tool", ["test.run", "lint.run", "typecheck.run"])
def test_coder_and_reviewer_can_run_validation_tools(evaluator, workspace, tool):
    for role in (Role.CODER, Role.REVIEWER):
        call = ToolCall(role=role, tool_name=tool, scope_root=(workspace / "MyProj").resolve())
        decision = evaluator.evaluate(call, SessionMode.AUTO)
        assert decision.permission == ToolPermission.ALLOW


@pytest.mark.parametrize("tool", ["test.run", "lint.run", "typecheck.run"])
def test_planner_cannot_run_validation_tools(evaluator, workspace, tool):
    call = ToolCall(role=Role.PLANNER, tool_name=tool, scope_root=(workspace / "MyProj").resolve())
    decision = evaluator.evaluate(call, SessionMode.AUTO)
    assert decision.permission == ToolPermission.DENY


def test_auto_mode_does_not_loosen_below_static_table(workspace):
    # A custom table entry pinned to CONFIRM must never become ALLOW under
    # AUTO - AUTO's ceiling is ALLOW, meaning "no additional restriction,"
    # not "force everything open."
    sandbox = FilesystemSandbox(workspace)
    table = {(Role.CODER, "deps.install"): ToolPermission.CONFIRM}
    scoped_evaluator = PermissionEvaluator(sandbox, tool_table=table)
    call = ToolCall(role=Role.CODER, tool_name="deps.install")
    decision = scoped_evaluator.evaluate(call, SessionMode.AUTO)
    assert decision.permission == ToolPermission.CONFIRM
