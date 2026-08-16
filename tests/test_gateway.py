import pytest

from agent_platform.events import EventLog
from agent_platform.security.enums import Role, SessionMode
from agent_platform.security.permission import PermissionEvaluator
from agent_platform.security.sandbox import FilesystemSandbox
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


def test_unknown_tool_is_reported_and_never_reaches_permission(gateway, workspace):
    obs = gateway.invoke(role=Role.CODER, tool_name="shell.run", arguments={},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "unknown_tool"


def test_invalid_schema_is_reported_before_execution(gateway, workspace):
    obs = gateway.invoke(role=Role.CODER, tool_name="filesystem.write", arguments={"path": "app.py"},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "invalid_schema"


def test_denied_by_role_is_reported(gateway, workspace):
    obs = gateway.invoke(role=Role.PLANNER, tool_name="filesystem.write",
                          arguments={"path": "app.py", "content": "x"},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "denied"


def test_denied_by_sandbox_path_escape_is_reported(gateway, workspace, tmp_path):
    outside = str(tmp_path / "Outside" / "evil.py")
    obs = gateway.invoke(role=Role.CODER, tool_name="filesystem.write",
                          arguments={"path": outside, "content": "x"},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "denied"


def test_confirmation_mode_reports_requires_confirmation_not_ok(gateway, workspace):
    obs = gateway.invoke(role=Role.CODER, tool_name="filesystem.write",
                          arguments={"path": "app.py", "content": "x"},
                          session_mode=SessionMode.CONFIRMATION, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "requires_confirmation"
    assert not (workspace / "MyProj" / "app.py").exists()


def test_successful_write_executes_and_returns_ok(gateway, workspace):
    obs = gateway.invoke(role=Role.CODER, tool_name="filesystem.write",
                          arguments={"path": "app.py", "content": "x = 1"},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "ok"
    assert (workspace / "MyProj" / "app.py").read_text(encoding="utf-8") == "x = 1"


def test_precondition_failure_is_reported_as_error_not_a_crash(gateway, workspace):
    obs = gateway.invoke(role=Role.CODER, tool_name="filesystem.read", arguments={"path": "missing.py"},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "error"


def test_all_git_write_tools_are_denied_regardless_of_registration(gateway, workspace):
    for tool in ["git.init", "git.add", "git.commit", "git.push", "git.reset", "git.rebase"]:
        obs = gateway.invoke(role=Role.CODER, tool_name=tool, arguments={},
                              session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
        assert obs.status in ("unknown_tool", "denied"), f"{tool} was not rejected: {obs.status}"
        assert obs.status != "ok"


def test_shell_run_is_denied_regardless_of_registration(gateway, workspace):
    obs = gateway.invoke(role=Role.CODER, tool_name="shell.run", arguments={"command": "echo hi"},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status != "ok"


def test_every_invocation_is_logged(gateway, workspace):
    gateway.invoke(role=Role.CODER, tool_name="filesystem.write",
                    arguments={"path": "app.py", "content": "x"},
                    session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert len(gateway.event_log.internal_stream()) >= 1
