"""Secure subprocess execution primitive for validation tools
(test.run/lint.run/typecheck.run). This is a LAUNCH-CONTROL boundary,
not a containment boundary - see PHASE3_REPORT.md's "Actual Security
Boundary" section for the full statement of what that does and doesn't
mean.

What this module enforces:
- argv-list execution only, shell=False always - no shell metacharacter
  interpretation is structurally possible, regardless of what a target
  string contains.
- a fixed, minimal environment - never the orchestrator process's full
  environment, which could carry credentials/tokens the child has no
  business seeing.
- a hard wall-clock timeout, with the FULL PROCESS TREE killed on
  timeout via `taskkill /F /T`, not just the immediate child - a plain
  Popen.kill() only kills the direct child and would leak orphaned
  grandchildren (e.g. a test that itself launches a server process).
- a hard cap on captured output, enforced by actively truncating and
  stopping the process rather than buffering unboundedly and cutting the
  string afterward.

What this module does NOT enforce:
- any restriction on what the launched process can DO once running. It
  executes with the same Windows user account and privileges as the
  orchestrator itself. A malicious test file can still read/write any
  file that account can access, make network calls, or spawn further
  processes for its own timeout window. This module controls how the
  process is launched and how it's stopped, never what it does while
  alive.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_MINIMAL_ENV_KEYS = {"PATH", "SYSTEMROOT", "TEMP", "TMP", "PATHEXT", "COMSPEC"}


def _minimal_environment() -> dict:
    env: dict = {}
    for key, value in os.environ.items():
        if key.upper() in _MINIMAL_ENV_KEYS:
            env[key] = value
    return env


def _kill_process_tree(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                        capture_output=True, timeout=10)
    else:
        import signal
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except ProcessLookupError:
            pass


@dataclass(frozen=True)
class ProcessResult:
    exit_code: Optional[int]
    stdout: str
    stderr: str
    timed_out: bool
    stdout_truncated: bool
    stderr_truncated: bool


def run_process(argv: list[str], *, cwd: Path, timeout_seconds: float,
                 max_output_bytes: int = 1_000_000) -> ProcessResult:
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        argv, cwd=str(cwd), env=_minimal_environment(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
        creationflags=creationflags,
    )

    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    truncated = {"stdout": False, "stderr": False}
    total_bytes = {"count": 0}
    lock = threading.Lock()
    overflow_event = threading.Event()

    def reader(pipe, chunks: list, key: str) -> None:
        try:
            while True:
                chunk = pipe.read(4096)
                if not chunk:
                    break
                with lock:
                    remaining = max_output_bytes - total_bytes["count"]
                    if remaining <= 0:
                        truncated[key] = True
                        overflow_event.set()
                        break
                    if len(chunk) > remaining:
                        chunks.append(chunk[:remaining])
                        total_bytes["count"] += remaining
                        truncated[key] = True
                        overflow_event.set()
                        break
                    chunks.append(chunk)
                    total_bytes["count"] += len(chunk)
        finally:
            try:
                pipe.close()
            except OSError:
                pass

    threads = [
        threading.Thread(target=reader, args=(proc.stdout, stdout_chunks, "stdout"), daemon=True),
        threading.Thread(target=reader, args=(proc.stderr, stderr_chunks, "stderr"), daemon=True),
    ]
    for t in threads:
        t.start()

    deadline = time.monotonic() + timeout_seconds
    timed_out = False
    while True:
        if proc.poll() is not None:
            break
        if overflow_event.is_set():
            break
        if time.monotonic() >= deadline:
            timed_out = True
            break
        time.sleep(0.05)

    if timed_out or overflow_event.is_set():
        _kill_process_tree(proc.pid)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    for t in threads:
        t.join(timeout=5)

    return ProcessResult(
        exit_code=proc.returncode,
        stdout=b"".join(stdout_chunks).decode("utf-8", errors="replace"),
        stderr=b"".join(stderr_chunks).decode("utf-8", errors="replace"),
        timed_out=timed_out,
        stdout_truncated=truncated["stdout"],
        stderr_truncated=truncated["stderr"],
    )
