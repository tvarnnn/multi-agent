"""Attacks 32/33: orphan-process recovery and output-limit bypass were
proven at the run_process primitive level in Phase 3. This confirms both
hold end-to-end through the actual test.run tool and gateway, not just
the primitive in isolation.
"""
import subprocess
import time

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


def test_attack_32_orphan_process_from_a_malicious_test_is_killed_end_to_end(tmp_path):
    proj = _workspace(tmp_path)
    child_pid_file = proj / "child.pid"
    (proj / "test_spawns_orphan.py").write_text(
        "import subprocess, sys, time\n"
        "def test_spawns_orphan():\n"
        "    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"    with open(r'{child_pid_file}', 'w') as f:\n"
        "        f.write(str(child.pid))\n"
        "    time.sleep(60)\n",
        encoding="utf-8",
    )
    sandbox = FilesystemSandbox(proj.parent)
    evaluator = PermissionEvaluator(sandbox)
    gateway = ToolGateway(build_default_registry(), evaluator, EventLog())
    obs = gateway.invoke(role=Role.CODER, tool_name="test.run", arguments={"timeout_seconds": 3},
                          session_mode=SessionMode.AUTO, project_root=proj.resolve())
    assert obs.status == "ok"
    assert obs.result["timed_out"] is True
    assert child_pid_file.exists()
    child_pid = int(child_pid_file.read_text().strip())
    time.sleep(1)
    check = subprocess.run(["tasklist", "/FI", f"PID eq {child_pid}"], capture_output=True, text=True)
    assert str(child_pid) not in check.stdout


def test_attack_33_oversized_test_output_is_truncated_end_to_end(tmp_path):
    proj = _workspace(tmp_path)
    (proj / "test_bigout.py").write_text(
        "def test_bigout():\n"
        "    for _ in range(50000):\n"
        "        print('x' * 100)\n"
        "    assert False  # force pytest to emit the captured stdout instead of swallowing it\n",
        encoding="utf-8",
    )
    sandbox = FilesystemSandbox(proj.parent)
    evaluator = PermissionEvaluator(sandbox)
    gateway = ToolGateway(build_default_registry(), evaluator, EventLog())
    obs = gateway.invoke(role=Role.CODER, tool_name="test.run", arguments={"timeout_seconds": 20},
                          session_mode=SessionMode.AUTO, project_root=proj.resolve())
    assert obs.status == "ok"
    assert obs.result["stdout_truncated"] is True
    assert len(obs.result["stdout"].encode("utf-8")) <= 1_000_000
