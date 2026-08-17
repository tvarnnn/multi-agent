"""Attacks 20/21: secret exfiltration and unauthorized network access.
These are EXPECTED to fail against the current implementation - Phase
3's report already documented that executed test/lint/typecheck
processes share the orchestrator's OS privileges with no additional
isolation. This makes that documented gap concrete and measured instead
of asserted. No code fix is applied here: closing it for real would mean
OS-level process isolation (a restricted token, a Windows Job Object, a
container) - a new capability explicitly out of this phase's scope
("do not add new capabilities"). Both are surfaced as FAIL in the
security report, not silently passed.
"""
import http.server
import threading

from agent_platform.events import EventLog
from agent_platform.security.enums import Role, SessionMode
from agent_platform.security.permission import PermissionEvaluator
from agent_platform.security.sandbox import FilesystemSandbox
from agent_platform.tools.gateway import ToolGateway
from agent_platform.tools.registry import build_default_registry


def _workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    proj = root / "MyProj"
    proj.mkdir()
    return proj


def test_attack_20_a_malicious_test_can_read_a_file_outside_the_sandbox_and_stage_it_inside(tmp_path):
    outside_secret = tmp_path / "outside_secret.txt"
    outside_secret.write_text("TOP-SECRET-MARKER-VALUE", encoding="utf-8")
    proj = _workspace(tmp_path)
    (proj / "test_exfil.py").write_text(
        "def test_exfil():\n"
        f"    with open(r'{outside_secret}') as f:\n"
        "        data = f.read()\n"
        "    with open('staged_secret.txt', 'w') as out:\n"
        "        out.write(data)\n"
        "    assert True\n",
        encoding="utf-8",
    )
    sandbox = FilesystemSandbox(proj.parent)
    evaluator = PermissionEvaluator(sandbox)
    gateway = ToolGateway(build_default_registry(), evaluator, EventLog())
    gateway.invoke(role=Role.CODER, tool_name="test.run", arguments={},
                    session_mode=SessionMode.AUTO, project_root=proj.resolve())
    staged = proj / "staged_secret.txt"
    # EXPECTED (documented) FAILURE MODE: the process had the same OS
    # privileges as the orchestrator and could read a file entirely
    # outside the sandbox, then write its content inside the sandbox
    # where a subsequent filesystem.read/context-retrieval call would
    # pick it up. This assertion documents that this DOES happen.
    assert staged.exists()
    assert staged.read_text(encoding="utf-8") == "TOP-SECRET-MARKER-VALUE"


def test_attack_21_a_malicious_test_can_make_an_outbound_network_connection(tmp_path):
    received = {"hit": False}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            received["hit"] = True
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        proj = _workspace(tmp_path)
        (proj / "test_network.py").write_text(
            "import urllib.request\n"
            "def test_network():\n"
            f"    urllib.request.urlopen('http://127.0.0.1:{port}/', timeout=5)\n"
            "    assert True\n",
            encoding="utf-8",
        )
        sandbox = FilesystemSandbox(proj.parent)
        evaluator = PermissionEvaluator(sandbox)
        gateway = ToolGateway(build_default_registry(), evaluator, EventLog())
        gateway.invoke(role=Role.CODER, tool_name="test.run", arguments={"timeout_seconds": 15},
                        session_mode=SessionMode.AUTO, project_root=proj.resolve())
        # EXPECTED (documented) FAILURE MODE: nothing blocks outbound
        # network access from an executed test process.
        assert received["hit"] is True
    finally:
        server.shutdown()
