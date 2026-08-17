from pathlib import Path

import pytest

from agent_platform.tools.registry import ToolExecutionContext, build_default_registry
from agent_platform.tools.schemas import ToolArgumentError, ToolPreconditionError


@pytest.fixture
def registry():
    return build_default_registry()


def test_all_expected_tools_are_registered(registry):
    assert registry.names() == (
        "filesystem.create_directory", "filesystem.list", "filesystem.read",
        "filesystem.write", "git.branch", "git.diff", "git.log", "git.status",
        "lint.run", "test.run", "typecheck.run",
    )


def test_unregistered_tool_returns_none(registry):
    assert registry.get("git.commit") is None
    assert registry.get("shell.run") is None


def test_filesystem_read_validate_arguments_requires_path(registry):
    spec = registry.get("filesystem.read")
    with pytest.raises(ToolArgumentError):
        spec.validate_arguments({})
    with pytest.raises(ToolArgumentError):
        spec.validate_arguments({"path": ""})
    assert spec.validate_arguments({"path": "app.py"}) == {"path": "app.py"}


def test_filesystem_write_validate_arguments_requires_path_and_content(registry):
    spec = registry.get("filesystem.write")
    with pytest.raises(ToolArgumentError):
        spec.validate_arguments({"path": "app.py"})
    assert spec.validate_arguments({"path": "app.py", "content": "x"}) == {
        "path": "app.py", "content": "x"
    }


def test_git_tools_validate_arguments_ignores_extra_and_requires_nothing(registry):
    spec = registry.get("git.status")
    assert spec.validate_arguments({}) == {}
    assert spec.validate_arguments({"anything": "ignored"}) == {}


def test_filesystem_read_precondition_requires_existing_file(tmp_path, registry):
    spec = registry.get("filesystem.read")
    missing = tmp_path / "missing.py"
    ctx = ToolExecutionContext(resolved_path=missing, project_root=tmp_path)
    with pytest.raises(ToolPreconditionError):
        spec.check_preconditions({"path": "missing.py"}, ctx)


def test_filesystem_read_executes_and_returns_content(tmp_path, registry):
    target = tmp_path / "app.py"
    target.write_text("print('hi')", encoding="utf-8")
    spec = registry.get("filesystem.read")
    ctx = ToolExecutionContext(resolved_path=target, project_root=tmp_path)
    result = spec.execute({"path": "app.py"}, ctx)
    assert result == {"content": "print('hi')"}


def test_filesystem_write_creates_parent_dirs_and_writes(tmp_path, registry):
    target = tmp_path / "sub" / "app.py"
    spec = registry.get("filesystem.write")
    ctx = ToolExecutionContext(resolved_path=target, project_root=tmp_path)
    result = spec.execute({"path": "sub/app.py", "content": "x = 1"}, ctx)
    assert target.read_text(encoding="utf-8") == "x = 1"
    assert result == {"written": str(target)}


def test_filesystem_create_directory_executes(tmp_path, registry):
    target = tmp_path / "newdir"
    spec = registry.get("filesystem.create_directory")
    ctx = ToolExecutionContext(resolved_path=target, project_root=tmp_path)
    spec.execute({"path": "newdir"}, ctx)
    assert target.is_dir()


def test_filesystem_list_precondition_requires_existing_directory(tmp_path, registry):
    spec = registry.get("filesystem.list")
    missing = tmp_path / "missing_dir"
    ctx = ToolExecutionContext(resolved_path=missing, project_root=tmp_path)
    with pytest.raises(ToolPreconditionError):
        spec.check_preconditions({"path": "missing_dir"}, ctx)


def test_filesystem_list_executes_and_returns_sorted_entries(tmp_path, registry):
    (tmp_path / "b.py").write_text("", encoding="utf-8")
    (tmp_path / "a.py").write_text("", encoding="utf-8")
    spec = registry.get("filesystem.list")
    ctx = ToolExecutionContext(resolved_path=tmp_path, project_root=tmp_path)
    result = spec.execute({"path": "."}, ctx)
    assert result == {"entries": ["a.py", "b.py"]}


def test_git_status_reports_unscoped_outside_a_repo(tmp_path, registry):
    spec = registry.get("git.status")
    ctx = ToolExecutionContext(resolved_path=None, project_root=tmp_path)
    result = spec.execute({}, ctx)
    assert result["scoped"] is False


def test_validation_tool_rejects_unexpected_argument_keys(registry):
    spec = registry.get("test.run")
    with pytest.raises(ToolArgumentError):
        spec.validate_arguments({"executable": "cmd.exe"})
    with pytest.raises(ToolArgumentError):
        spec.validate_arguments({"command": ["del", "/f", "/s", "/q", "C:\\"]})
    with pytest.raises(ToolArgumentError):
        spec.validate_arguments({"args": ["--anything"]})


def test_validation_tool_accepts_no_target_and_default_timeout(registry):
    spec = registry.get("test.run")
    validated = spec.validate_arguments({})
    assert validated["target"] is None
    assert validated["timeout_seconds"] == pytest.approx(60.0)


def test_validation_tool_rejects_non_positive_or_oversized_timeout(registry):
    spec = registry.get("test.run")
    with pytest.raises(ToolArgumentError):
        spec.validate_arguments({"timeout_seconds": 0})
    with pytest.raises(ToolArgumentError):
        spec.validate_arguments({"timeout_seconds": -5})
    with pytest.raises(ToolArgumentError):
        spec.validate_arguments({"timeout_seconds": 10_000})


def test_validation_tool_execute_runs_a_real_passing_script(tmp_path, registry):
    (tmp_path / "test_ok.py").write_text("def test_x():\n    assert 1 == 1\n")
    spec = registry.get("test.run")
    ctx = ToolExecutionContext(resolved_path=tmp_path / "test_ok.py", project_root=tmp_path)
    result = spec.execute({"target": "test_ok.py", "timeout_seconds": 30.0}, ctx)
    assert result["passed"] is True
    assert result["exit_code"] == 0


def test_validation_tool_execute_reports_a_real_failing_script(tmp_path, registry):
    (tmp_path / "test_fail.py").write_text("def test_x():\n    assert False\n")
    spec = registry.get("test.run")
    ctx = ToolExecutionContext(resolved_path=tmp_path / "test_fail.py", project_root=tmp_path)
    result = spec.execute({"target": "test_fail.py", "timeout_seconds": 30.0}, ctx)
    assert result["passed"] is False
    assert result["exit_code"] != 0
