import subprocess
import sys
import time

from agent_platform.tools.process_execution import run_process


def test_captures_normal_completion(tmp_path):
    script = tmp_path / "ok.py"
    script.write_text("print('hello stdout')\nimport sys\nprint('hello stderr', file=sys.stderr)\n")
    result = run_process([sys.executable, str(script)], cwd=tmp_path, timeout_seconds=10)
    assert result.exit_code == 0
    assert "hello stdout" in result.stdout
    assert "hello stderr" in result.stderr
    assert not result.timed_out


def test_captures_non_zero_exit_code(tmp_path):
    result = run_process([sys.executable, "-c", "import sys; sys.exit(3)"], cwd=tmp_path, timeout_seconds=10)
    assert result.exit_code == 3


def test_uses_minimal_environment_not_full_parent_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPER_SECRET_TOKEN", "should-not-leak")
    script = tmp_path / "envcheck.py"
    script.write_text(
        "import os\n"
        "print('TOKEN_PRESENT' if 'SUPER_SECRET_TOKEN' in os.environ else 'TOKEN_ABSENT')\n"
    )
    result = run_process([sys.executable, str(script)], cwd=tmp_path, timeout_seconds=10)
    assert "TOKEN_ABSENT" in result.stdout


def test_kills_full_process_tree_on_timeout_not_just_the_parent(tmp_path):
    child_pid_file = tmp_path / "child.pid"
    parent_script = tmp_path / "parent.py"
    parent_script.write_text(
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"with open(r'{child_pid_file}', 'w') as f:\n"
        "    f.write(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    result = run_process([sys.executable, str(parent_script)], cwd=tmp_path, timeout_seconds=3)
    assert result.timed_out
    assert child_pid_file.exists()
    child_pid = int(child_pid_file.read_text().strip())
    time.sleep(1)  # let taskkill finish tearing down the tree
    check = subprocess.run(["tasklist", "/FI", f"PID eq {child_pid}"], capture_output=True, text=True)
    assert str(child_pid) not in check.stdout  # child is gone too - not orphaned


def test_truncates_oversized_output_instead_of_buffering_unboundedly(tmp_path):
    script = tmp_path / "bigout.py"
    script.write_text("for _ in range(100000):\n    print('x' * 100)\n")
    result = run_process([sys.executable, str(script)], cwd=tmp_path, timeout_seconds=20, max_output_bytes=1000)
    assert result.stdout_truncated
    assert len(result.stdout.encode("utf-8")) <= 1000


def test_normal_short_output_is_not_marked_truncated(tmp_path):
    script = tmp_path / "small.py"
    script.write_text("print('short')\n")
    result = run_process([sys.executable, str(script)], cwd=tmp_path, timeout_seconds=10, max_output_bytes=1000)
    assert not result.stdout_truncated
    assert not result.stderr_truncated
