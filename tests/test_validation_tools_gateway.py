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


def test_planner_cannot_run_tests_through_the_gateway(gateway, workspace):
    obs = gateway.invoke(role=Role.PLANNER, tool_name="test.run", arguments={},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "denied"


def test_coder_runs_a_real_passing_test_end_to_end(gateway, workspace):
    proj = workspace / "MyProj"
    (proj / "test_sample.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n")
    obs = gateway.invoke(role=Role.CODER, tool_name="test.run", arguments={"target": "test_sample.py"},
                          session_mode=SessionMode.AUTO, project_root=proj.resolve())
    assert obs.status == "ok"
    assert obs.result["passed"] is True
    assert obs.result["exit_code"] == 0


def test_reviewer_can_independently_rerun_the_same_test(gateway, workspace):
    proj = workspace / "MyProj"
    (proj / "test_sample.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n")
    obs = gateway.invoke(role=Role.REVIEWER, tool_name="test.run", arguments={"target": "test_sample.py"},
                          session_mode=SessionMode.AUTO, project_root=proj.resolve())
    assert obs.status == "ok"
    assert obs.result["passed"] is True


def test_failed_test_is_reported_as_not_passed_not_a_tool_error(gateway, workspace):
    proj = workspace / "MyProj"
    (proj / "test_sample.py").write_text("def test_fail():\n    assert False\n")
    obs = gateway.invoke(role=Role.CODER, tool_name="test.run", arguments={"target": "test_sample.py"},
                          session_mode=SessionMode.AUTO, project_root=proj.resolve())
    assert obs.status == "ok"  # the tool ran to completion successfully
    assert obs.result["passed"] is False  # the test itself failed
    assert obs.result["exit_code"] != 0


def test_target_escaping_the_project_is_denied_not_executed(gateway, workspace, tmp_path):
    outside = tmp_path / "Outside"
    outside.mkdir()
    (outside / "evil.py").write_text("def test_x():\n    assert 1 == 1\n")
    obs = gateway.invoke(role=Role.CODER, tool_name="test.run", arguments={"target": str(outside / "evil.py")},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "denied"


def test_unexpected_executable_argument_is_rejected_before_permission_check(gateway, workspace):
    obs = gateway.invoke(role=Role.CODER, tool_name="test.run",
                          arguments={"executable": "cmd.exe", "args": ["/c", "echo pwned"]},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "invalid_schema"


def test_confirmation_mode_blocks_execution_without_running_anything(gateway, workspace):
    proj = workspace / "MyProj"
    (proj / "test_sample.py").write_text("def test_ok():\n    assert 1 == 1\n")
    obs = gateway.invoke(role=Role.CODER, tool_name="test.run", arguments={"target": "test_sample.py"},
                          session_mode=SessionMode.CONFIRMATION, project_root=proj.resolve())
    assert obs.status == "requires_confirmation"


def test_lint_and_typecheck_report_missing_module_as_a_clean_failure_not_a_crash(gateway, workspace):
    # ruff and mypy are not installed in this environment - this is also
    # exactly what a generated project without those dev-dependencies
    # installed would hit for real. Must degrade to passed: False, never
    # raise or hang.
    for tool in ("lint.run", "typecheck.run"):
        obs = gateway.invoke(role=Role.CODER, tool_name=tool, arguments={},
                              session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
        assert obs.status == "ok"
        assert obs.result["passed"] is False


def test_all_git_write_tools_still_denied_alongside_the_new_tools(gateway, workspace):
    for tool in ["git.init", "git.add", "git.commit", "git.push", "git.reset", "git.rebase"]:
        obs = gateway.invoke(role=Role.CODER, tool_name=tool, arguments={},
                              session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
        assert obs.status != "ok"
