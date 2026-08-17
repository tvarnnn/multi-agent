# Phase 3 Validation & Controlled Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `test.run`/`lint.run`/`typecheck.run` as typed, gateway-
mediated tools that execute real project code under hard security
constraints, and wire real test execution into deterministic validation
so that `COMPLETE` genuinely requires passing tests, not just reviewer
approval.

**Architecture:** A new process-execution primitive
(`tools/process_execution.py`) is the only thing in this codebase that
calls `subprocess.Popen` for validation purposes. It never uses
`shell=True`, never accepts a model-controllable executable, enforces a
hard wall-clock timeout with real **process-tree** termination (not just
the immediate child — a plain `.kill()` would leak orphans), and caps
captured output by actively truncating rather than buffering unboundedly.
Three new `ToolSpec`s reuse this primitive with a *fixed* base command
per tool and the *same* sandbox-authorized `target` argument pattern
Phase 1's filesystem tools already use — there is no argument that lets a
caller choose the executable or inject shell syntax, structurally, not
just by convention. A new `TestRunValidator` (Protocol-conforming, per
Phase 1's `Validator`) lets the orchestrator gate `COMPLETE` on a real
`test.run` result without any change to `orchestrator/core.py` — Phase
1's `_final_validation` already ANDs the validator's `passed` with
reviewer approval; this phase makes that boolean come from real pytest
output instead of only a file-existence check.

**Tech Stack:** Python 3.12.5 standard library only
(`subprocess`, `threading`, `time` — no new dependency). Windows process-
tree termination via `taskkill /F /T /PID <pid>` (a system utility
invoked with a fixed argv, not a new dependency). Real, local subprocess
execution in tests (no network) — consistent with how Phase 0 tested real
symlinks/junctions rather than mocking OS behavior.

**Spec:** `architecture-review-v2.md` §1.4 (typed-tools-only, subprocess
hardening), `architecture-review-v4-human-controlled-git.md`, Phase 0
(`security/sandbox.py`, `security/permission.py`), Phase 1
(`tools/registry.py`, `tools/gateway.py`, `orchestrator/validation.py`,
`orchestrator/core.py`), `PHASE0_REPORT.md`, `PHASE1_REPORT.md`.

## Global Constraints

- No `shell.run`, no arbitrary executable, no arbitrary command strings.
  Each of `test.run`/`lint.run`/`typecheck.run` has a *fixed* base
  argv (`sys.executable -m pytest` / `-m ruff check` / `-m mypy`); the
  only caller-supplied input is an optional `target` (a path *within the
  active project*, validated by Phase 0's real `FilesystemSandbox` via
  the exact same `path_argument_key` mechanism Phase 1's filesystem tools
  already use) and a bounded `timeout_seconds`. No `executable`,
  `command`, or `args` key is ever accepted — proven by a test, not just
  asserted.
- Phase 0's `sandbox.py` and Phase 1's `orchestrator/core.py` are not
  redesigned. `permission.py` and `tools/registry.py` get small, additive
  edits (new table entries, new tool registrations) — each verified by
  re-running the full prior suite before moving on, same discipline as
  Phase 2's Task 0.
- `ruff` and `mypy` are **not installed** in this environment (confirmed:
  only `pytest` is). `lint.run`/`typecheck.run` are still implemented and
  registered — a generated project's own dev-dependencies are what would
  actually provide these tools, and "module not found" must be a clean
  `passed: False` result, not a crash. This is verified for real in Task
  4, not assumed.
- Git remains exactly as restrictive as Phase 0/1/4 already made it — no
  new git capability, no git commands run in this session.
- **This module is a launch-control boundary, not a containment
  boundary**, and that distinction is documented explicitly rather than
  glossed over (see Task 6). Executed test/lint/typecheck code runs with
  the same Windows user privileges as the orchestrator itself; nothing in
  this phase prevents it from reading/writing files or making network
  calls within that account's normal permissions once it's running. A
  stronger isolation mechanism (restricted token, Job Object resource
  limits, container/VM) is **not implemented** here and is named as an
  explicit gap in the report, per the standing instruction not to claim
  complete isolation.

---

### Task 1: Secure process execution primitive

**Files:**
- Create: `src/agent_platform/tools/process_execution.py`
- Create: `tests/test_process_execution.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) class ProcessResult(exit_code:
  Optional[int], stdout: str, stderr: str, timed_out: bool,
  stdout_truncated: bool, stderr_truncated: bool)`; `run_process(argv:
  list[str], *, cwd: Path, timeout_seconds: float, max_output_bytes: int
  = 1_000_000) -> ProcessResult`. Task 2's validation tools call exactly
  this function with a fixed `argv` and the active project as `cwd` —
  nothing else in this codebase spawns a subprocess for validation
  purposes.

- [ ] **Step 1: Write the failing tests**

`tests/test_process_execution.py`:
```python
import subprocess
import sys
import time

import pytest

from agent_platform.tools.process_execution import run_process


def test_captures_normal_completion(tmp_path):
    script = tmp_path / "ok.py"
    script.write_text("print('hello stdout')\nimport sys\nprint('hello stderr', file=sys.stderr)\n")
    result = run_process([sys.executable, str(script)], cwd=tmp_path, timeout_seconds=10)
    assert result.exit_code == 0
    assert "hello stdout" in result.stdout
    assert "hello stderr" in result.stderr
    assert not result.timed_out


def test_captures_non_zero_exit_code():
    result = run_process([sys.executable, "-c", "import sys; sys.exit(3)"],
                          cwd=None if False else __import__("pathlib").Path("."), timeout_seconds=10)
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_process_execution.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/agent_platform/tools/process_execution.py`:
```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_process_execution.py -v`
Expected: PASS (6 tests). The timeout/orphan test is the slowest (waits
out a real 3-second timeout plus a 1-second settle) — that's expected,
not a hang.

---

### Task 2: Validation tool schemas and registry entries

**Files:**
- Modify: `src/agent_platform/tools/registry.py` (add three
  `ToolSpec` registrations to `build_default_registry()` - do not
  restructure the existing filesystem/git registrations)
- Modify: `tests/test_tools_registry.py` (the existing
  `test_all_expected_tools_are_registered` assertion must be updated to
  include the three new names, in sorted order - this is expected
  maintenance of a test that intentionally pins the full registry
  contents, not a sign something is wrong)

**Interfaces:**
- Consumes: `run_process`, `ProcessResult` (Task 1); `ToolSpec`,
  `ToolExecutionContext`, `ToolArgumentError` (Phase 1's `tools/schemas.py`,
  unchanged)
- Produces: `test.run`/`lint.run`/`typecheck.run` registered with
  `path_argument_key="target"` (reusing Phase 1's existing
  sandbox-authorization wiring in the gateway verbatim - no new plumbing).
  `execute` returns `{"exit_code": int|None, "passed": bool, "stdout":
  str, "stderr": str, "timed_out": bool, "stdout_truncated": bool,
  "stderr_truncated": bool}`.

- [ ] **Step 1: Update the existing registry test and add new ones**

In `tests/test_tools_registry.py`, replace:
```python
def test_all_expected_tools_are_registered(registry):
    assert registry.names() == (
        "filesystem.create_directory", "filesystem.list", "filesystem.read",
        "filesystem.write", "git.branch", "git.diff", "git.log", "git.status",
    )
```
with:
```python
def test_all_expected_tools_are_registered(registry):
    assert registry.names() == (
        "filesystem.create_directory", "filesystem.list", "filesystem.read",
        "filesystem.write", "git.branch", "git.diff", "git.log", "git.status",
        "lint.run", "test.run", "typecheck.run",
    )
```

Then append to the same file:
```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_tools_registry.py -v`
Expected: the updated `test_all_expected_tools_are_registered` FAILS
(current registry doesn't have the new names yet), and the new tests FAIL
with `AttributeError: 'NoneType' object has no attribute 'validate_arguments'`
(`registry.get("test.run")` returns `None`).

- [ ] **Step 3: Implement**

Add to `src/agent_platform/tools/registry.py`, near the top (after the
existing imports):
```python
import sys

from .process_execution import run_process
```

Add these module-level constants and functions (after the existing
`_execute_git_branch` function, before `class ToolRegistry`):
```python
_VALIDATION_TOOL_COMMANDS: dict[str, list[str]] = {
    "test.run": [sys.executable, "-m", "pytest"],
    "lint.run": [sys.executable, "-m", "ruff", "check"],
    "typecheck.run": [sys.executable, "-m", "mypy"],
}
_DEFAULT_VALIDATION_TIMEOUT_SECONDS = 60.0
_MAX_VALIDATION_TIMEOUT_SECONDS = 300.0


def _validate_validation_args(args: dict) -> dict:
    if not isinstance(args, dict):
        raise ToolArgumentError("arguments must be an object")
    allowed_keys = {"target", "timeout_seconds"}
    unexpected = set(args) - allowed_keys
    if unexpected:
        raise ToolArgumentError(
            f"unexpected argument(s): {sorted(unexpected)} - only 'target' and "
            "'timeout_seconds' are accepted; the executable and command are fixed "
            "per tool and cannot be overridden"
        )
    target = args.get("target")
    if target is not None and (not isinstance(target, str) or not target.strip()):
        raise ToolArgumentError("target, if given, must be a non-empty string")
    timeout = args.get("timeout_seconds", _DEFAULT_VALIDATION_TIMEOUT_SECONDS)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not (0 < timeout <= _MAX_VALIDATION_TIMEOUT_SECONDS):
        raise ToolArgumentError(
            f"timeout_seconds must be a positive number no greater than {_MAX_VALIDATION_TIMEOUT_SECONDS}"
        )
    return {"target": target, "timeout_seconds": float(timeout)}


def _make_validation_executor(base_argv: list[str]):
    def execute(args: dict, ctx: ToolExecutionContext) -> dict:
        argv = list(base_argv)
        if ctx.resolved_path is not None:
            argv.append(str(ctx.resolved_path))
        result = run_process(argv, cwd=ctx.project_root, timeout_seconds=args["timeout_seconds"])
        return {
            "exit_code": result.exit_code,
            "passed": (result.exit_code == 0) and not result.timed_out,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "timed_out": result.timed_out,
            "stdout_truncated": result.stdout_truncated,
            "stderr_truncated": result.stderr_truncated,
        }
    return execute
```

Add to `build_default_registry()`, just before `return registry`:
```python
    for tool_name, base_argv in _VALIDATION_TOOL_COMMANDS.items():
        registry.register(ToolSpec(
            name=tool_name, validate_arguments=_validate_validation_args,
            path_argument_key="target", check_preconditions=_no_precondition,
            execute=_make_validation_executor(base_argv),
        ))
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_tools_registry.py -v`
Expected: PASS (17 total: 12 existing + 5 new). The two "real script"
tests genuinely spawn `python -m pytest` as a subprocess - expect a few
seconds, not milliseconds, for those two.

---

### Task 3: Permission table wiring

**Files:**
- Modify: `src/agent_platform/security/permission.py` (`_default_tool_table`
  only - do not touch `PermissionEvaluator.evaluate` or `ABSOLUTE_DENY_TOOLS`)
- Modify: `tests/test_permission.py` (add coverage for the new grants)

**Interfaces:**
- Consumes: nothing new
- Produces: `(Role.CODER, "test.run"/"lint.run"/"typecheck.run")` and
  `(Role.REVIEWER, "test.run"/"lint.run"/"typecheck.run")` all map to
  `ToolPermission.ALLOW`. Planner gets no entry (defaults to DENY via the
  existing deny-by-default lookup) - matching `architecture-review-v2.md`
  §5's permission matrix, where the reviewer independently re-runs
  validation rather than trusting cached results, and the planner never
  executes anything.

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_permission.py`:
```python
@pytest.mark.parametrize("tool", ["test.run", "lint.run", "typecheck.run"])
def test_coder_and_reviewer_can_run_validation_tools(evaluator, workspace, tool):
    for role in (Role.CODER, Role.REVIEWER):
        call = ToolCall(role=role, tool_name=tool, scope_root=(workspace / "MyProj").resolve())
        decision = evaluator.evaluate(call, SessionMode.AUTO)
        assert decision.permission == ToolPermission.ALLOW


@pytest.mark.parametrize("tool", ["test.run", "lint.run", "typecheck.run"])
def test_planner_cannot_run_validation_tools(evaluator, workspace, tool):
    call = ToolCall(role=Role.PLANNER, tool_name=tool, scope_root=(workspace / "MyProj").resolve())
    decision = evaluator.evaluate(call, SessionMode.AUTO)
    assert decision.permission == ToolPermission.DENY
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_permission.py -v`
Expected: the Coder/Reviewer parametrized cases FAIL (currently DENY, no
table entry yet); the Planner cases already PASS (deny-by-default already
holds).

- [ ] **Step 3: Implement**

In `src/agent_platform/security/permission.py`, add to `_default_tool_table()`,
just before `return table`:
```python
    for tool in ("test.run", "lint.run", "typecheck.run"):
        table[(Role.CODER, tool)] = ToolPermission.ALLOW
        table[(Role.REVIEWER, tool)] = ToolPermission.ALLOW
```

- [ ] **Step 4: Run to verify pass, then re-run the full prior suite**

Run: `python -m pytest tests/test_permission.py -v`
Expected: PASS (85 total: 79 existing + 6 new).

Run: `python -m pytest tests/ --ignore=tests/test_ollama_integration.py -q`
Expected: every test built through Phase 2 (570) still passes unchanged -
this additive table change must not regress anything.

---

### Task 4: Gateway-level end-to-end coverage

**Files:**
- Create: `tests/test_validation_tools_gateway.py`

**Interfaces:**
- Consumes: `ToolGateway`, `build_default_registry` (now including the
  three new tools), `PermissionEvaluator`, `FilesystemSandbox` - no new
  production code, this task proves the tools work correctly through the
  *same* 6-step pipeline every other tool goes through.

- [ ] **Step 1: Write the tests**

`tests/test_validation_tools_gateway.py`:
```python
import pytest

from agent_platform.events import EventLog
from agent_platform.security.enums import Role, SessionMode
from agent_platform.security.permission import PermissionEvaluator
from agent_platform.security.sandbox import FilesystemSandbox
from agent_platform.tools.gateway import ToolGateway
from agent_platform.tools.registry import build_default_registry


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    (root / "MyProj").mkdir()
    return root


@pytest.fixture
def gateway(workspace):
    sandbox = FilesystemSandbox(workspace)
    evaluator = PermissionEvaluator(sandbox)
    return ToolGateway(build_default_registry(), evaluator, EventLog())


def test_planner_cannot_run_tests_through_the_gateway(gateway, workspace):
    obs = gateway.invoke(role=Role.PLANNER, tool_name="test.run", arguments={},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "denied"


def test_coder_runs_a_real_passing_test_end_to_end(gateway, workspace):
    proj = workspace / "MyProj"
    (proj / "test_sample.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n")
    obs = gateway.invoke(role=Role.CODER, tool_name="test.run", arguments={"target": "test_sample.py"},
                          session_mode=SessionMode.AUTO, project_root=proj.resolve())
    assert obs.status == "ok"
    assert obs.result["passed"] is True
    assert obs.result["exit_code"] == 0


def test_reviewer_can_independently_rerun_the_same_test(gateway, workspace):
    proj = workspace / "MyProj"
    (proj / "test_sample.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n")
    obs = gateway.invoke(role=Role.REVIEWER, tool_name="test.run", arguments={"target": "test_sample.py"},
                          session_mode=SessionMode.AUTO, project_root=proj.resolve())
    assert obs.status == "ok"
    assert obs.result["passed"] is True


def test_failed_test_is_reported_as_not_passed_not_a_tool_error(gateway, workspace):
    proj = workspace / "MyProj"
    (proj / "test_sample.py").write_text("def test_fail():\n    assert False\n")
    obs = gateway.invoke(role=Role.CODER, tool_name="test.run", arguments={"target": "test_sample.py"},
                          session_mode=SessionMode.AUTO, project_root=proj.resolve())
    assert obs.status == "ok"  # the tool ran to completion successfully
    assert obs.result["passed"] is False  # the test itself failed
    assert obs.result["exit_code"] != 0


def test_target_escaping_the_project_is_denied_not_executed(gateway, workspace, tmp_path):
    outside = tmp_path / "Outside"
    outside.mkdir()
    (outside / "evil.py").write_text("def test_x():\n    assert 1 == 1\n")
    obs = gateway.invoke(role=Role.CODER, tool_name="test.run", arguments={"target": str(outside / "evil.py")},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "denied"


def test_unexpected_executable_argument_is_rejected_before_permission_check(gateway, workspace):
    obs = gateway.invoke(role=Role.CODER, tool_name="test.run",
                          arguments={"executable": "cmd.exe", "args": ["/c", "echo pwned"]},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "invalid_schema"


def test_confirmation_mode_blocks_execution_without_running_anything(gateway, workspace):
    proj = workspace / "MyProj"
    (proj / "test_sample.py").write_text("def test_ok():\n    assert 1 == 1\n")
    obs = gateway.invoke(role=Role.CODER, tool_name="test.run", arguments={"target": "test_sample.py"},
                          session_mode=SessionMode.CONFIRMATION, project_root=proj.resolve())
    assert obs.status == "requires_confirmation"


def test_lint_and_typecheck_report_missing_module_as_a_clean_failure_not_a_crash(gateway, workspace):
    # ruff and mypy are not installed in this environment - this is also
    # exactly what a generated project without those dev-dependencies
    # installed would hit for real. Must degrade to passed: False, never
    # raise or hang.
    for tool in ("lint.run", "typecheck.run"):
        obs = gateway.invoke(role=Role.CODER, tool_name=tool, arguments={},
                              session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
        assert obs.status == "ok"
        assert obs.result["passed"] is False


def test_all_git_write_tools_still_denied_alongside_the_new_tools(gateway, workspace):
    for tool in ["git.init", "git.add", "git.commit", "git.push", "git.reset", "git.rebase"]:
        obs = gateway.invoke(role=Role.CODER, tool_name=tool, arguments={},
                              session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
        assert obs.status != "ok"
```

- [ ] **Step 2: Run and fix anything unexpected**

Run: `python -m pytest tests/test_validation_tools_gateway.py -v`
Expected: PASS (9 tests). If
`test_lint_and_typecheck_report_missing_module_as_a_clean_failure_not_a_crash`
fails, inspect the actual stderr from a manual `python -m ruff` /
`python -m mypy` invocation on this machine - Python's exact "no module
named X" exit behavior can vary slightly by version, and this test is the
one place that real-world variance would surface. Fix `_make_validation_executor`
if needed (it should already handle this correctly, since a non-zero
exit code from *any* cause maps to `passed: False`), not the test.

---

### Task 5: `TestRunValidator` — real deterministic validation

**Files:**
- Modify: `src/agent_platform/orchestrator/validation.py` (add two new
  classes; do not change `AcceptanceCriteriaFileValidator`)
- Create: `tests/test_test_run_validator.py`
- Create: `tests/test_orchestrator_real_validation.py`

**Interfaces:**
- Consumes: `ToolGateway`, `Role`, `SessionMode` (Phase 1);
  `Validator`, `ValidationResult` (Phase 1's `validation.py`, unchanged)
- Produces: `class TestRunValidator` with constructor
  `TestRunValidator(gateway: ToolGateway, role: Role, session_mode:
  SessionMode)` and `validate(project_root, spec) -> ValidationResult`
  (Protocol-conforming); `class CompositeValidator` with constructor
  `CompositeValidator(validators: tuple[Validator, ...])` ANDing multiple
  validators' `passed` and concatenating their `details`. Both are usable
  directly as the `validator=` argument `Orchestrator.__init__` already
  accepts - no change to `orchestrator/core.py`.

- [ ] **Step 1: Write `TestRunValidator`/`CompositeValidator` tests**

`tests/test_test_run_validator.py`:
```python
import pytest

from agent_platform.events import EventLog
from agent_platform.orchestrator.validation import (
    AcceptanceCriteriaFileValidator,
    CompositeValidator,
    TestRunValidator,
)
from agent_platform.security.enums import Role, SessionMode
from agent_platform.security.permission import PermissionEvaluator
from agent_platform.security.sandbox import FilesystemSandbox
from agent_platform.spec.versioning import SpecStore
from agent_platform.tools.gateway import ToolGateway
from agent_platform.tools.registry import build_default_registry


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    (root / "MyProj").mkdir()
    return root


@pytest.fixture
def gateway(workspace):
    sandbox = FilesystemSandbox(workspace)
    evaluator = PermissionEvaluator(sandbox)
    return ToolGateway(build_default_registry(), evaluator, EventLog())


def _spec():
    return SpecStore().create("task-1", goals=["g"], constraints=[], acceptance_criteria=[])


def test_passes_when_the_real_test_suite_passes(gateway, workspace):
    proj = workspace / "MyProj"
    (proj / "test_sample.py").write_text("def test_ok():\n    assert 1 == 1\n")
    validator = TestRunValidator(gateway, Role.REVIEWER, SessionMode.AUTO)
    result = validator.validate(proj.resolve(), _spec())
    assert result.passed


def test_fails_when_the_real_test_suite_fails(gateway, workspace):
    proj = workspace / "MyProj"
    (proj / "test_sample.py").write_text("def test_fail():\n    assert False\n")
    validator = TestRunValidator(gateway, Role.REVIEWER, SessionMode.AUTO)
    result = validator.validate(proj.resolve(), _spec())
    assert not result.passed


def test_composite_validator_requires_all_to_pass(gateway, workspace):
    proj = workspace / "MyProj"
    (proj / "app.py").write_text("x = 1\n")
    (proj / "test_sample.py").write_text("def test_fail():\n    assert False\n")
    spec = SpecStore().create("task-2", goals=["g"], constraints=[], acceptance_criteria=["file:app.py"])
    composite = CompositeValidator((
        AcceptanceCriteriaFileValidator(),          # passes - app.py exists
        TestRunValidator(gateway, Role.REVIEWER, SessionMode.AUTO),  # fails - test_fail
    ))
    result = composite.validate(proj.resolve(), spec)
    assert not result.passed
    assert len(result.details) >= 2  # details from both validators are present
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_test_run_validator.py -v`
Expected: FAIL - `TestRunValidator`/`CompositeValidator` don't exist yet.

- [ ] **Step 3: Implement**

Add to `src/agent_platform/orchestrator/validation.py` (after the
existing `AcceptanceCriteriaFileValidator` class - do not modify it):
```python
class TestRunValidator:
    """Deterministic validator that actually runs the project's tests
    via the test.run typed tool, instead of only checking that files
    exist. This is what makes COMPLETE actually require passing tests -
    Orchestrator._final_validation ANDs this result with reviewer
    approval, unchanged since Phase 1, so a reviewer APPROVE can never
    override a real test failure here.
    """

    def __init__(self, gateway, role, session_mode) -> None:
        self._gateway = gateway
        self._role = role
        self._session_mode = session_mode

    def validate(self, project_root: Path, spec: SpecVersion) -> ValidationResult:
        obs = self._gateway.invoke(
            role=self._role, tool_name="test.run", arguments={},
            session_mode=self._session_mode, project_root=project_root,
        )
        if obs.status != "ok":
            return ValidationResult(
                passed=False,
                details=(f"test.run could not execute: {obs.status} - {obs.error}",),
            )
        result = obs.result
        detail = f"test.run exit_code={result['exit_code']} passed={result['passed']}"
        if result.get("timed_out"):
            detail += " (TIMED OUT)"
        return ValidationResult(passed=result["passed"], details=(detail,))


class CompositeValidator:
    """ANDs multiple validators together - COMPLETE requires every one
    of them to pass, not just the last one checked."""

    def __init__(self, validators: tuple) -> None:
        self._validators = validators

    def validate(self, project_root: Path, spec: SpecVersion) -> ValidationResult:
        all_details: list = []
        all_passed = True
        for validator in self._validators:
            result = validator.validate(project_root, spec)
            all_details.extend(result.details)
            all_passed = all_passed and result.passed
        return ValidationResult(passed=all_passed, details=tuple(all_details))
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_test_run_validator.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Prove reviewer approval cannot override a real test failure, at the orchestrator level**

`tests/test_orchestrator_real_validation.py`:
```python
import pytest

from agent_platform.events import EventLog
from agent_platform.orchestrator.core import Orchestrator, State
from agent_platform.orchestrator.fake_model import FakeModelProvider
from agent_platform.orchestrator.validation import TestRunValidator
from agent_platform.security.enums import Role, SessionMode
from agent_platform.security.permission import PermissionEvaluator
from agent_platform.security.sandbox import FilesystemSandbox
from agent_platform.spec.versioning import SpecStore
from agent_platform.tools.gateway import ToolGateway
from agent_platform.tools.registry import build_default_registry


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    (root / "MyProj").mkdir()
    return root


def test_reviewer_approval_does_not_override_a_real_failing_test(workspace):
    sandbox = FilesystemSandbox(workspace)
    evaluator = PermissionEvaluator(sandbox)
    event_log = EventLog()
    gateway = ToolGateway(build_default_registry(), evaluator, event_log)
    # The model is scripted to APPROVE every time - a maximally
    # permissive reviewer. Real test.run must still gate completion.
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["g"], "constraints": [],
                             "acceptance_criteria": []}],
        coder_responses=[
            {"status": "completed", "spec_version_label": "task-1-v1", "summary": "s",
             "file_writes": [{"path": "test_sample.py",
                               "content": "def test_fail():\n    assert False\n"}]}
            for _ in range(3)
        ],
        reviewer_responses=[
            {"spec_version_label": "task-1-v1", "decision": "APPROVE", "requirements_met": True,
             "security_ok": True, "validation_ok": True, "issues": []}
            for _ in range(3)
        ],
    )
    orchestrator = Orchestrator(
        gateway=gateway, model=model, spec_store=SpecStore(), event_log=event_log,
        session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve(),
        validator=TestRunValidator(gateway, Role.REVIEWER, SessionMode.AUTO),
        max_fix_iterations=2,
    )
    result = orchestrator.run("task-1", "build something with a failing test")
    # Reviewer approved every single time; the real test never passed;
    # the orchestrator must NOT reach COMPLETE.
    assert result.final_state == State.ESCALATE_TO_USER
```

- [ ] **Step 6: Run to verify pass**

Run: `python -m pytest tests/test_orchestrator_real_validation.py -v`
Expected: PASS (1 test). This is the concrete proof of "do not allow a
reviewer approval to override failed deterministic validation" - with a
real subprocess test run, a maximally agreeable fake reviewer, and zero
changes to `orchestrator/core.py`.

---

### Task 6: Full suite re-run and Phase 3 report

**Files:**
- Create: `PHASE3_REPORT.md`

- [ ] **Step 1: Run everything**

Run: `python -m pytest tests/ --ignore=tests/test_ollama_integration.py -v --tb=short`
Expected: all prior tests plus every test from this phase pass together.
Record the exact count. (`test_ollama_integration.py` is Phase 2's
real-network file, excluded here exactly as it was in Phase 2's own
Task 6, not part of this phase's scope.)

- [ ] **Step 2: Write `PHASE3_REPORT.md`**

Structure like the prior reports: Implemented, Test results, then two
sections that must not be softened:

**"Actual Security Boundary" (required, verbatim in spirit):**
State plainly what `run_process`/the three validation tools DO enforce
(argv-only execution, fixed executable per tool, sandbox-validated
target, minimal environment, hard timeout, real process-tree kill via
`taskkill /F /T` - proven against a real orphan-spawning script in Task
1, hard output cap enforced by truncation not post-hoc slicing) and what
they explicitly do NOT enforce: the launched process runs with the same
Windows user privileges as the orchestrator; nothing in this phase stops
a running test/lint/typecheck invocation from reading/writing files or
making network calls within that account's permissions, or from being
slow/resource-hungry short of the timeout. State explicitly that a
stronger isolation mechanism (a restricted access token, a Windows Job
Object with CPU/memory limits, or container/VM-level isolation) is not
implemented in this phase, and that Job Object limits specifically could
be added via `ctypes` without a new dependency if this becomes a hard
requirement in a future phase - name it as a concrete next step, not a
vague "future work" gesture.

**Security/determinism invariants confirmed:**
- Command injection is structurally impossible, not merely rejected by a
  validator - `shell=False` argv-list execution means there is no shell
  to inject into, and this was proven the same way process-tree killing
  was: with a real subprocess, not a mock.
- No parameter accepts a caller-chosen executable or raw command string
  - proven by a test that such keys are rejected before permission is
    even evaluated.
- Reviewer approval was proven, end-to-end with a real subprocess test
  run and zero orchestrator changes, to never override a real
  deterministic validation failure (Task 5's
  `test_reviewer_approval_does_not_override_a_real_failing_test`).
- Git remains exactly as restrictive as Phase 0/1/2 left it - no new
  capability, confirmed alongside the new tools in the same gateway test
  file (Task 4).

**Scope decisions:** `ruff`/`mypy` not installed in this environment -
`lint.run`/`typecheck.run` are fully implemented and registered, and
"module not available" was proven to degrade cleanly to `passed: False`
rather than crash, which is also the real behavior a generated project
missing its own dev-dependencies would hit.

- [ ] **Step 3: Stop**

Per the standing instruction, do not proceed to any further phase.
Report back: what was implemented, test counts, and the security
boundary statement above in full - this is the part of the report the
user explicitly asked not to be softened or omitted.
