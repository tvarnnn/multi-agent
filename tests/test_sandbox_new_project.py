import subprocess

import pytest

from agent_platform.security.sandbox import FilesystemSandbox


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    return root


@pytest.fixture
def sandbox(workspace):
    return FilesystemSandbox(workspace)


def test_new_project_with_clean_name_is_allowed(sandbox, workspace):
    decision = sandbox.authorize_new_project("MarketView")
    assert decision.allowed
    assert decision.resolved_path == (workspace / "MarketView").resolve()


def test_new_project_over_existing_directory_is_denied(sandbox, workspace):
    (workspace / "MarketView").mkdir()
    decision = sandbox.authorize_new_project("MarketView")
    assert not decision.allowed


def test_new_project_over_existing_junction_is_denied(sandbox, workspace, tmp_path):
    target = tmp_path / "SomewhereElse"
    target.mkdir()
    trap = workspace / "MarketView"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(trap), str(target)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"mklink failed: {result.stderr}"
    decision = sandbox.authorize_new_project("MarketView")
    assert not decision.allowed
    assert "symlink" in decision.reason.lower() or "junction" in decision.reason.lower() or "reparse" in decision.reason.lower()


@pytest.mark.parametrize("name", ["", "   ", "..", ".", "a/b", "a\\b", "a:b", "a*b", "a?b", "a<b>", "a|b", 'a"b'])
def test_invalid_project_names_are_denied(sandbox, name):
    decision = sandbox.authorize_new_project(name)
    assert not decision.allowed


@pytest.mark.parametrize("name", ["CON", "NUL", "com1", "LPT9"])
def test_reserved_device_names_as_project_names_are_denied(sandbox, name):
    decision = sandbox.authorize_new_project(name)
    assert not decision.allowed
