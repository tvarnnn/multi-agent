"""Attack 9 (Git manipulation): a malicious .git/config setting
core.fsmonitor or diff.external to an arbitrary command must not execute
that command when the platform's read-only git.status/git.diff/git.log
tools run - these are supposed to be safe, inspection-only operations.
Reproduced empirically against this machine's real git before writing
this plan: both fired without the fix.
"""
import subprocess

import pytest

from agent_platform.events import EventLog
from agent_platform.security.enums import Role, SessionMode
from agent_platform.security.permission import PermissionEvaluator
from agent_platform.security.sandbox import FilesystemSandbox
from agent_platform.tools.gateway import ToolGateway
from agent_platform.tools.registry import build_default_registry


def _init_real_repo(proj):
    subprocess.run(["git", "init", "-q", str(proj)], check=True, capture_output=True)
    (proj / "tracked.txt").write_text("hello", encoding="utf-8")


def _workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    proj = root / "MyProj"
    proj.mkdir()
    return proj


@pytest.fixture
def gateway_and_proj(tmp_path):
    proj = _workspace(tmp_path)
    _init_real_repo(proj)
    sandbox = FilesystemSandbox(proj.parent)
    evaluator = PermissionEvaluator(sandbox)
    gateway = ToolGateway(build_default_registry(), evaluator, EventLog())
    return gateway, proj


def test_malicious_core_fsmonitor_does_not_execute_on_git_status(gateway_and_proj):
    gateway, proj = gateway_and_proj
    marker = proj / "FSMONITOR_FIRED.txt"
    subprocess.run(["git", "config", "core.fsmonitor",
                     f'sh -c "echo fired > {marker.as_posix()}; echo {{}}"'],
                    cwd=str(proj), check=True, capture_output=True)
    gateway.invoke(role=Role.CODER, tool_name="git.status", arguments={},
                    session_mode=SessionMode.AUTO, project_root=proj.resolve())
    assert not marker.exists(), "core.fsmonitor command executed during git.status"


def test_malicious_diff_external_does_not_execute_on_git_diff(gateway_and_proj):
    gateway, proj = gateway_and_proj
    marker = proj / "DIFF_EXTERNAL_FIRED.txt"
    # "git diff" (no args) compares the working tree against the INDEX,
    # not HEAD - no commit is needed. Stage the original content first,
    # then modify the file WITHOUT re-staging, so there's an actual
    # unstaged difference for "git diff" to show, which is what invokes
    # an external diff driver.
    subprocess.run(["git", "add", "tracked.txt"], cwd=str(proj), check=True, capture_output=True)
    subprocess.run(["git", "config", "diff.external",
                     f'sh -c "echo fired > {marker.as_posix()}; exit 0"'],
                    cwd=str(proj), check=True, capture_output=True)
    (proj / "tracked.txt").write_text("modified without staging", encoding="utf-8")
    gateway.invoke(role=Role.CODER, tool_name="git.diff", arguments={},
                    session_mode=SessionMode.AUTO, project_root=proj.resolve())
    assert not marker.exists(), "diff.external command executed during git.diff"


def test_pre_commit_hook_does_not_fire_on_read_only_operations(gateway_and_proj):
    # Confirmed separately (not exploitable here): commit hooks only run
    # on actual commits, which the agent never performs. This test
    # documents that this specific vector was checked and is not live,
    # rather than leaving it unverified.
    gateway, proj = gateway_and_proj
    hooks_dir = proj / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    marker = proj / "HOOK_FIRED.txt"
    hook = hooks_dir / "pre-commit"
    hook.write_text(f'#!/bin/sh\necho fired > "{marker.as_posix()}"\n', encoding="utf-8")
    hook.chmod(0o755)
    for tool in ("git.status", "git.diff", "git.log"):
        gateway.invoke(role=Role.CODER, tool_name=tool, arguments={},
                        session_mode=SessionMode.AUTO, project_root=proj.resolve())
    assert not marker.exists()
