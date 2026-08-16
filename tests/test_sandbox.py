import os
import subprocess
from pathlib import Path

import pytest

from agent_platform.security.sandbox import FilesystemSandbox, SandboxConfigurationError


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    (root / "MyProj").mkdir()
    return root


@pytest.fixture
def sandbox(workspace):
    return FilesystemSandbox(workspace)


def test_normal_relative_path_inside_project_is_allowed(sandbox, workspace):
    decision = sandbox.authorize("MyProj/app.py")
    assert decision.allowed
    assert decision.resolved_path == (workspace / "MyProj" / "app.py").resolve()


def test_normal_absolute_path_inside_workspace_is_allowed(sandbox, workspace):
    target = str(workspace / "MyProj" / "app.py")
    decision = sandbox.authorize(target)
    assert decision.allowed


def test_parent_traversal_is_denied(sandbox):
    decision = sandbox.authorize("MyProj/../../outside.txt")
    assert not decision.allowed
    assert decision.resolved_path is None


def test_absolute_escape_is_denied(sandbox, tmp_path):
    outside = tmp_path / "Elsewhere" / "secret.txt"
    decision = sandbox.authorize(str(outside))
    assert not decision.allowed


def test_sibling_prefix_attack_is_denied(sandbox, workspace):
    # A naive `str(path).startswith(str(workspace))` check would wrongly
    # allow this, since "ProjectsEvil" starts with "Projects". relative_to
    # compares path *segments*, not raw strings, so it correctly denies it.
    sibling = workspace.parent / (workspace.name + "Evil") / "file.txt"
    naive_check_would_wrongly_allow = str(sibling).startswith(str(workspace))
    assert naive_check_would_wrongly_allow  # documents the trap being avoided
    decision = sandbox.authorize(str(sibling))
    assert not decision.allowed


def test_drive_relative_path_is_denied(sandbox):
    decision = sandbox.authorize("C:MyProj/app.py")
    assert not decision.allowed


def test_root_relative_path_is_denied(sandbox):
    decision = sandbox.authorize("\\MyProj\\app.py")
    assert not decision.allowed


def test_unc_path_is_denied(sandbox):
    decision = sandbox.authorize(r"\\server\share\file.txt")
    assert not decision.allowed


def test_extended_length_prefix_is_denied(sandbox, workspace):
    decision = sandbox.authorize(r"\\?\C:" + str(workspace / "MyProj" / "app.py")[2:])
    assert not decision.allowed


def test_device_namespace_path_is_denied(sandbox):
    decision = sandbox.authorize(r"\\.\PhysicalDrive0")
    assert not decision.allowed


@pytest.mark.parametrize("name", ["CON", "con.txt", "NUL", "nul.py", "COM1", "LPT9"])
def test_reserved_device_names_are_denied(sandbox, name):
    decision = sandbox.authorize(f"MyProj/{name}")
    assert not decision.allowed


def test_empty_and_whitespace_paths_are_denied(sandbox):
    assert not sandbox.authorize("").allowed
    assert not sandbox.authorize("   ").allowed


def test_null_byte_path_is_denied(sandbox):
    assert not sandbox.authorize("MyProj/app\x00.py").allowed


def test_dotgit_access_is_denied(sandbox, workspace):
    (workspace / "MyProj" / ".git").mkdir()
    decision = sandbox.authorize("MyProj/.git/hooks/pre-commit")
    assert not decision.allowed
    assert "git" in decision.reason.lower()


def test_junction_in_path_is_denied_even_if_target_is_inside_workspace(sandbox, workspace):
    real_dir = workspace / "RealTarget"
    real_dir.mkdir()
    junction = workspace / "MyProj" / "linked"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(real_dir)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"mklink failed: {result.stderr}"
    decision = sandbox.authorize("MyProj/linked/file.txt")
    assert not decision.allowed
    assert "reparse" in decision.reason.lower()


def test_junction_escaping_workspace_is_denied(sandbox, workspace, tmp_path):
    outside = tmp_path / "Outside"
    outside.mkdir()
    junction = workspace / "MyProj" / "escape"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"mklink failed: {result.stderr}"
    decision = sandbox.authorize("MyProj/escape/file.txt")
    assert not decision.allowed


def test_symlink_in_path_is_denied(sandbox, workspace, tmp_path):
    outside = tmp_path / "Outside2"
    outside.mkdir()
    link = workspace / "MyProj" / "symlinked"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation requires elevated privilege or Developer Mode on this machine")
    decision = sandbox.authorize("MyProj/symlinked/file.txt")
    assert not decision.allowed


def test_scope_root_narrows_authorization_to_active_project(sandbox, workspace):
    (workspace / "OtherProj").mkdir()
    scope = (workspace / "MyProj").resolve()
    decision = sandbox.authorize("../OtherProj/file.txt", scope_root=scope)
    assert not decision.allowed


def test_scope_root_allows_paths_within_the_active_project(sandbox, workspace):
    scope = (workspace / "MyProj").resolve()
    decision = sandbox.authorize("app.py", scope_root=scope)
    assert decision.allowed


def test_resolution_failure_denies_rather_than_raises(sandbox):
    # A path with an embedded null is invalid at the OS level; the sandbox
    # must translate that into a deny, never propagate the OSError.
    decision = sandbox.authorize("MyProj/\x00bad")
    assert not decision.allowed


def test_nonexistent_workspace_root_raises_at_construction(tmp_path):
    missing = tmp_path / "DoesNotExist"
    with pytest.raises(SandboxConfigurationError):
        FilesystemSandbox(missing)


def test_workspace_root_itself_as_reparse_point_is_rejected(tmp_path):
    real = tmp_path / "RealRoot"
    real.mkdir()
    linked_root = tmp_path / "LinkedRoot"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(linked_root), str(real)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"mklink failed: {result.stderr}"
    with pytest.raises(SandboxConfigurationError):
        FilesystemSandbox(linked_root)
