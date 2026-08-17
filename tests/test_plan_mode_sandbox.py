import os
import subprocess
from pathlib import Path

import pytest

from agent_platform.security.enums import OperatingMode, Role, SessionMode, ToolPermission
from agent_platform.security.permission import PermissionEvaluator, ToolCall
from agent_platform.security.sandbox import FilesystemSandbox


@pytest.fixture
def plan_security(tmp_path: Path):
    workspace = tmp_path / "workspace"
    project = workspace / "project"
    (project / ".agent" / "plans").mkdir(parents=True)
    return project, PermissionEvaluator(FilesystemSandbox(workspace))


def decide(project, evaluator, path):
    return evaluator.evaluate(
        ToolCall(Role.PLANNER, "filesystem.write", path, project),
        SessionMode.AUTO,
        operating_mode=OperatingMode.PLAN,
    )


@pytest.mark.parametrize(
    "path",
    [
        ".agent/plans/../../escape.md",
        ".agent/plans-evil/escape.md",
        "C:relative.md",
        r"\rooted.md",
        r"\\server\share\escape.md",
        r"\\.\PhysicalDrive0",
        r"\\?\C:\escape.md",
        ".git/config",
        ".agent/plans/.git/config",
    ],
)
def test_plan_scope_rejects_escape_and_special_paths(plan_security, path):
    project, evaluator = plan_security
    assert decide(project, evaluator, path).permission is ToolPermission.DENY


def test_plan_scope_rejects_absolute_and_sibling_prefix_escape(plan_security, tmp_path):
    project, evaluator = plan_security
    outside = tmp_path / "outside.md"
    sibling = project / ".agent" / "plans-evil" / "escape.md"
    assert decide(project, evaluator, str(outside)).permission is ToolPermission.DENY
    assert decide(project, evaluator, str(sibling)).permission is ToolPermission.DENY


def test_plan_scope_rejects_junction_escape(plan_security, tmp_path):
    project, evaluator = plan_security
    outside = tmp_path / "outside"
    outside.mkdir()
    junction = project / ".agent" / "plans" / "escape"
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(outside)], capture_output=True)
    assert result.returncode == 0
    assert decide(project, evaluator, ".agent/plans/escape/file.md").permission is ToolPermission.DENY


def test_plan_scope_rejects_symlink_escape(plan_security, tmp_path):
    project, evaluator = plan_security
    outside = tmp_path / "outside-link"
    outside.mkdir()
    link = project / ".agent" / "plans" / "escape-link"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation requires Developer Mode")
    assert decide(project, evaluator, ".agent/plans/escape-link/file.md").permission is ToolPermission.DENY
