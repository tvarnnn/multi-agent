"""Phase 12 gap found while wiring the VS Code extension: build_server()/
run()/main() had no way to make the sandbox boundary (FilesystemSandbox's
root) anything other than project_root's parent - correct for the
existing Projects/MyProj test convention, but wrong for a VS Code
extension spawning the backend against exactly the folder the user
opened (that folder IS the project; its parent may contain sibling
projects the user never opened and shouldn't be sandboxed into). Smallest
additive fix: an optional workspace_root passthrough on build_server()/
run(), and a new --sandbox-root CLI flag on main() - the existing
--workspace-root flag (which actually sets project_root, an existing
naming quirk left untouched for backward compatibility) is unchanged.
"""
import pytest

from agent_platform.orchestrator.fake_model import FakeModelProvider
from agent_platform.server import build_server, build_services, main


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    proj = root / "MyProj"
    proj.mkdir()
    return proj


def test_build_services_defaults_sandbox_to_project_root_parent(workspace):
    services = build_services(workspace, FakeModelProvider())
    assert services.sandbox.workspace_root == workspace.parent.resolve()


def test_build_services_honors_explicit_workspace_root_equal_to_project_root(workspace):
    services = build_services(workspace, FakeModelProvider(), workspace_root=workspace)
    assert services.sandbox.workspace_root == workspace.resolve()


def test_build_services_explicit_workspace_root_narrows_new_project_creation_scope(workspace):
    """Ordinary tool calls (filesystem.read/write/...) always pass
    scope_root=project_root (tools/gateway.py), so they're identically
    constrained to the opened project regardless of the outer sandbox
    width - that's not what this fix changes. What DOES differ at the
    outer width is FilesystemSandbox.authorize_new_project(), which
    operates directly against workspace_root: with the default (widened)
    sandbox, "new project" creation would target a sibling of the opened
    folder; with an explicit workspace_root=project_root (what the VS
    Code extension passes), it targets a subdirectory of the opened
    folder instead - never a sibling the user didn't open in VS Code."""
    narrowed = build_services(workspace, FakeModelProvider(), workspace_root=workspace)
    narrowed_decision = narrowed.sandbox.authorize_new_project("NewThing")
    assert narrowed_decision.allowed
    assert narrowed_decision.resolved_path == (workspace / "NewThing").resolve()

    widened = build_services(workspace, FakeModelProvider())
    widened_decision = widened.sandbox.authorize_new_project("NewThing")
    assert widened_decision.allowed
    assert widened_decision.resolved_path == (workspace.parent / "NewThing").resolve()


def test_build_server_accepts_and_threads_through_workspace_root(workspace):
    server, sock, token = build_server(workspace, FakeModelProvider(), workspace_root=workspace, port=0)
    try:
        assert token
        assert sock.getsockname()[1] > 0
    finally:
        sock.close()


def test_main_accepts_sandbox_root_flag_without_error(monkeypatch, workspace):
    calls = []

    def _fake_run(project_root, *, port=0, model=None, workspace_root=None):
        calls.append({"project_root": project_root, "port": port, "workspace_root": workspace_root})

    monkeypatch.setattr("agent_platform.server.run", _fake_run)
    main(["--workspace-root", str(workspace), "--sandbox-root", str(workspace), "--port", "0"])
    assert len(calls) == 1
    assert calls[0]["workspace_root"] == str(workspace)


def test_main_sandbox_root_is_optional(monkeypatch, workspace):
    calls = []

    def _fake_run(project_root, *, port=0, model=None, workspace_root=None):
        calls.append({"workspace_root": workspace_root})

    monkeypatch.setattr("agent_platform.server.run", _fake_run)
    main(["--workspace-root", str(workspace), "--port", "0"])
    assert calls[0]["workspace_root"] is None
