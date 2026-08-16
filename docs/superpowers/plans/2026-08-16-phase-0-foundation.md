> **STATUS: COMPLETE 2026-08-16.** All 9 tasks implemented, 451/451 tests
> passing, 0 skipped. See `../../../PHASE0_REPORT.md` at the project root
> for full results, security invariants tested, and unresolved concerns.
> Per the standing instruction, Phase 1 was not started.

# Phase 0 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and test the deterministic security and foundation layer
(filesystem sandbox, permission evaluator, configuration, spec versioning)
before any real autonomous agent behavior exists.

**Architecture:** Pure, dependency-free Python 3.12 modules under
`src/agent_platform/`. Every filesystem access request passes through a
`FilesystemSandbox` that resolves paths safely (following reparse points via
the OS, then re-checking for reparse points on the *pre-resolution* chain so
in-workspace junctions are caught even when they resolve back inside the
workspace) before any I/O is attempted. A `PermissionEvaluator` composes that
sandbox result with a static role/tool table and the session-mode ceiling
(`DENY < CONFIRM < ALLOW`, always taking the more restrictive of the two,
never the looser). Nothing here calls an LLM, Ollama, MCP, or the network —
Phase 0 is deterministic top to bottom, by design, so it's testable and
auditable before any non-deterministic behavior is introduced in a later
phase.

**Tech Stack:** Python 3.12.5 (native Windows install, confirmed present),
`pytest` 8.4.2 (already installed, no new install needed), Python standard
library only (`os`, `pathlib`, `stat`, `dataclasses`, `subprocess` for test
fixtures that create real junctions). No `hypothesis` — see the note under
Task 4 for why adversarial-path coverage is done via a large deterministic
parametrized matrix instead of a randomized property-testing library.

**Spec:** `architecture-review-v2.md`, `architecture-review-v3-agent-
interaction.md`, `architecture-review-v4-human-controlled-git.md` (all in
the session scratchpad from this project's earlier design review). This
plan implements the "Phase 0" scope from those documents: workspace
configuration, Windows filesystem sandbox (V2 §1.3/§8), permission evaluator
(V2 §1.6/§5, updated by V4 §3), security data structures, configuration
validation, and requirement/spec versioning primitives (V3 §7's structured
spec, formalized as an immutable data model).

## Global Constraints

- Workspace root is `C:\Users\tvllo\Projects` — confirmed to exist on this
  machine. Never `tvlloyd` or any other username; the sandbox rejects a
  nonexistent workspace root at construction time rather than silently
  accepting it.
- All code is Windows-aware; this plan assumes Python is invoked as native
  Windows Python (`C:\Users\tvllo\AppData\Local\Programs\Python\Python312\
  python.exe`), not WSL/MSYS Python, since reparse-point detection depends on
  native Win32 stat semantics (`os.stat(..., follow_symlinks=False)
  .st_file_attributes`, confirmed available on this interpreter).
- No new third-party dependencies. `pytest` is already installed; nothing
  else needed. Tests must run with zero network access and zero LLM/Ollama/
  MCP dependency (per Phase 0's own testing requirement) — a new pip install
  would be a network dependency at setup time even if tests don't call out
  at run time, so this plan avoids that entirely.
- Deny-by-default everywhere: any resolution failure, unrecognized path
  form, or absent permission-table entry results in denial, never a
  best-effort allow.
- This session does not create git commits. `git init` for this new project
  is a normal one-time developer-setup action (not the runtime agent's own
  behavior, which V4 restricts to read-only forever) and is done once in
  Task 1; nothing in this plan stages or commits — the user reviews and
  commits at their own discretion. Tasks end with "verify tests pass," not
  "commit."
- Phase 1 (deterministic orchestrator, tool registry, real git read-only
  wrapper, fake model provider) is explicitly out of scope for this plan.
  The permission table below includes entries for git tool *names* (e.g.
  `git.status`, `git.commit`) because the evaluator needs to know their
  permission tier regardless of phase, but no code that actually shells out
  to `git` is written here — that's Phase 1's `git.*` tool implementation.

---

### Task 1: Project scaffolding + smoke test

**Files:**
- Create: `pyproject.toml`
- Create: `src/agent_platform/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/test_smoke.py`
- Create: `.gitignore`

**Interfaces:**
- Consumes: nothing (first task)
- Produces: an importable `agent_platform` package on `sys.path` via
  editable install; a working `pytest` invocation from the project root

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "agent-platform"
version = "0.1.0"
description = "Local-first autonomous software engineering platform"
requires-python = ">=3.12"

[tool.pytest.ini_options]
testpaths = ["tests"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Create `.gitignore`**

```
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
.venv/
```

- [ ] **Step 3: Create empty package markers**

`src/agent_platform/__init__.py`:
```python
```

`tests/__init__.py`:
```python
```

- [ ] **Step 4: Write the smoke test**

`tests/test_smoke.py`:
```python
import agent_platform


def test_package_imports():
    assert agent_platform is not None
```

- [x] **Step 5: Install the package in editable mode and run the smoke test**

Run: `cd "C:\Users\tvllo\Projects\agent-platform" && python -m pip install -e . --no-deps && python -m pytest tests/test_smoke.py -v`

Expected: `python -m pip install -e .` succeeds without hitting the network for
anything beyond the local build backend (already installed with the
interpreter's base tooling); `test_package_imports` PASSES.

RESULT: PASS (1/1). Confirmed 2026-08-16.

- [ ] **Step 6: Initialize git for the new project (one-time developer setup, not an agent runtime action)**

SKIPPED per explicit user instruction during execution: no git commands
(including `git init`) run by the assistant this session — git setup is
left entirely to the user, matching V4's human-controlled-git philosophy
even for this development session, not just the runtime agent.

---

### Task 2: Security enums

**Files:**
- Create: `src/agent_platform/security/__init__.py`
- Create: `src/agent_platform/security/enums.py`
- Create: `tests/test_enums.py`

**Interfaces:**
- Consumes: nothing
- Produces: `Role` (PLANNER, CODER, REVIEWER), `SessionMode` (AUTO,
  CONFIRMATION, MANUAL), `ToolPermission` (ALLOW, CONFIRM, DENY) — all
  standard `enum.Enum`, imported downstream as
  `from agent_platform.security.enums import Role, SessionMode, ToolPermission`

- [ ] **Step 1: Write the failing test**

`tests/test_enums.py`:
```python
from agent_platform.security.enums import Role, SessionMode, ToolPermission


def test_role_members():
    assert {r.name for r in Role} == {"PLANNER", "CODER", "REVIEWER"}


def test_session_mode_members():
    assert {m.name for m in SessionMode} == {"AUTO", "CONFIRMATION", "MANUAL"}


def test_tool_permission_members():
    assert {p.name for p in ToolPermission} == {"ALLOW", "CONFIRM", "DENY"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_enums.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_platform.security'`

- [ ] **Step 3: Write the implementation**

`src/agent_platform/security/__init__.py`:
```python
```

`src/agent_platform/security/enums.py`:
```python
"""Core security enums. LLMs never make security decisions - these three
enums are the entire vocabulary the deterministic evaluator uses, and no
model output is ever parsed into one of these values."""
from __future__ import annotations

from enum import Enum


class Role(Enum):
    PLANNER = "PLANNER"
    CODER = "CODER"
    REVIEWER = "REVIEWER"


class SessionMode(Enum):
    AUTO = "AUTO"
    CONFIRMATION = "CONFIRMATION"
    MANUAL = "MANUAL"


class ToolPermission(Enum):
    ALLOW = "ALLOW"
    CONFIRM = "CONFIRM"
    DENY = "DENY"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_enums.py -v`
Expected: PASS (3 tests)

---

### Task 3: Filesystem sandbox core

**Files:**
- Create: `src/agent_platform/security/sandbox.py`
- Create: `tests/test_sandbox.py`

**Interfaces:**
- Consumes: `Role` not needed here; no dependency on Task 2 beyond the
  package existing
- Produces:
  - `class PathDecision` with fields `allowed: bool`, `resolved_path:
    Optional[Path]`, `reason: str`, and static constructors
    `PathDecision.allow(path, reason="authorized")` /
    `PathDecision.deny(reason)`
  - `class SandboxConfigurationError(Exception)`
  - `class FilesystemSandbox` with constructor
    `FilesystemSandbox(workspace_root: Path)` (raises
    `SandboxConfigurationError` if `workspace_root` doesn't exist or is
    itself a reparse point) and method
    `authorize(self, requested: str, *, scope_root: Optional[Path] = None) -> PathDecision`
  - These are the exact names Task 5 (`authorize_new_project`) and Task 6
    (`PermissionEvaluator`) import and call.

- [ ] **Step 1: Write the failing tests**

`tests/test_sandbox.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sandbox.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_platform.security.sandbox'`

- [ ] **Step 3: Write the implementation**

`src/agent_platform/security/sandbox.py`:
```python
"""Windows-aware filesystem sandbox.

Every path a tool wants to touch is authorized here before any I/O
happens. Deny-by-default: any ambiguity, resolution failure, or detected
reparse point anywhere in the path chain results in denial, never a
best-effort continuation. This module never does naive string-prefix
containment - see test_sibling_prefix_attack_is_denied for exactly why.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Optional

FILE_ATTRIBUTE_REPARSE_POINT = 0x400

_RESERVED_DEVICE_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class SandboxConfigurationError(Exception):
    """Raised when the sandbox itself cannot be safely constructed - e.g.
    the configured workspace root doesn't exist or is a reparse point."""


@dataclass(frozen=True)
class PathDecision:
    allowed: bool
    resolved_path: Optional[Path]
    reason: str

    @staticmethod
    def deny(reason: str) -> "PathDecision":
        return PathDecision(allowed=False, resolved_path=None, reason=reason)

    @staticmethod
    def allow(path: Path, reason: str = "authorized") -> "PathDecision":
        return PathDecision(allowed=True, resolved_path=path, reason=reason)


def _has_reserved_device_name(raw: str) -> bool:
    for part in PureWindowsPath(raw).parts:
        stem = part.split(".")[0].rstrip(" ").upper()
        if stem in _RESERVED_DEVICE_NAMES:
            return True
    return False


def _is_ambiguous_relative(raw: str) -> bool:
    """True for 'C:foo' (drive-relative) or '\\foo' (root-relative, no
    drive) - Windows resolves either using process state (current
    directory on that drive) this sandbox has no visibility into, so both
    are rejected rather than guessed at."""
    p = PureWindowsPath(raw)
    has_drive = p.drive != ""
    has_root = p.root != ""
    return has_drive != has_root


def _is_unc_or_device_path(raw: str) -> bool:
    stripped = raw.replace("/", "\\")
    return stripped.startswith("\\\\")


def _contains_reparse_point(path: Path, stop_at: Path) -> Optional[Path]:
    """Walk existing ancestors of `path` (checked *before* OS-level
    resolution has erased any reparse points from the chain) up to and
    including `stop_at`, and return the first one found to be a reparse
    point, or None. Deliberately does not follow symlinks when stat-ing -
    a reparse point must be visible as itself, not as its target."""
    current = path
    while True:
        try:
            st = os.stat(current, follow_symlinks=False)
        except (FileNotFoundError, OSError):
            pass
        else:
            if getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
                return current
        if current == stop_at:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


class FilesystemSandbox:
    def __init__(self, workspace_root: Path):
        try:
            resolved_root = Path(workspace_root).resolve(strict=True)
        except OSError as exc:
            raise SandboxConfigurationError(
                f"workspace_root does not exist or cannot be resolved: {workspace_root}"
            ) from exc
        if not resolved_root.is_dir():
            raise SandboxConfigurationError(f"workspace_root is not a directory: {resolved_root}")
        reparse_hit = _contains_reparse_point(resolved_root, stop_at=resolved_root)
        if reparse_hit is not None:
            raise SandboxConfigurationError(
                f"workspace root itself is a reparse point: {reparse_hit}"
            )
        self.workspace_root = resolved_root

    def authorize(self, requested: str, *, scope_root: Optional[Path] = None) -> PathDecision:
        if not requested or not requested.strip() or "\x00" in requested:
            return PathDecision.deny("empty or malformed path")

        if _is_unc_or_device_path(requested):
            return PathDecision.deny("UNC or device-namespace path rejected")

        if _is_ambiguous_relative(requested):
            return PathDecision.deny("drive-relative or root-relative path rejected (ambiguous)")

        if _has_reserved_device_name(requested):
            return PathDecision.deny("reserved Windows device name in path")

        base = scope_root if scope_root is not None else self.workspace_root
        try:
            base = Path(base).resolve(strict=False)
        except OSError:
            return PathDecision.deny("failed to resolve scope root")

        candidate = PureWindowsPath(requested)
        joined = Path(requested) if candidate.is_absolute() else base / requested

        reparse_hit = _contains_reparse_point(joined, stop_at=self.workspace_root)
        if reparse_hit is not None:
            return PathDecision.deny(f"reparse point detected at {reparse_hit}")

        try:
            resolved = joined.resolve(strict=False)
        except OSError:
            return PathDecision.deny("path resolution failed")

        try:
            relative_to_workspace = resolved.relative_to(self.workspace_root)
        except ValueError:
            return PathDecision.deny("path escapes workspace root")

        if scope_root is not None:
            try:
                resolved.relative_to(base)
            except ValueError:
                return PathDecision.deny("path escapes active project scope")

        if ".git" in {part.lower() for part in relative_to_workspace.parts}:
            return PathDecision.deny("direct access to .git internals is not permitted")

        return PathDecision.allow(resolved)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_sandbox.py -v`
Expected: PASS for all tests except possibly
`test_symlink_in_path_is_denied`, which SKIPS (not fails) if this Windows
account lacks the privilege/Developer Mode setting required to create
symlinks. A skip here is expected and acceptable — junction-based tests
cover the same reparse-point-detection code path without needing elevated
privilege, so coverage doesn't depend on this test running. Record whether
it ran or skipped for the Phase 0 report (Task 9).

---

### Task 4: Adversarial path matrix

**Files:**
- Create: `tests/test_sandbox_adversarial.py`

**Interfaces:**
- Consumes: `FilesystemSandbox` from Task 3 (no new production code in this
  task — it only adds test coverage against the existing implementation)
- Produces: nothing new for later tasks to consume

**Note on approach:** the brief asks for property-based testing "where
practical." `hypothesis` isn't installed and adding it means a new pip
install, which is a network dependency at setup time even though test
*execution* wouldn't hit the network — and `hypothesis`'s randomized
generation isn't fully deterministic run-to-run without pinning a seed,
which conflicts with the explicit "tests must be deterministic" requirement.
Instead, this task achieves the same goal — proving a *property* holds
across a wide adversarial input space, not just a few hand-picked examples —
using large, deterministically-generated `pytest.mark.parametrize` tables.
Every case is a concrete, reproducible input.

- [ ] **Step 1: Write the adversarial test matrix**

`tests/test_sandbox_adversarial.py`:
```python
import pytest

from agent_platform.security.sandbox import FilesystemSandbox


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    (root / "MyProj").mkdir()
    return root


@pytest.fixture
def sandbox(workspace):
    return FilesystemSandbox(workspace)


# Property: any number of "../" segments sufficient to reach above the
# workspace root must be denied, regardless of how deep the legitimate
# prefix looks.
@pytest.mark.parametrize("depth", list(range(1, 21)))
def test_traversal_depth_matrix_is_always_denied(sandbox, depth):
    traversal = "../" * depth + "outside.txt"
    decision = sandbox.authorize(f"MyProj/{traversal}")
    assert not decision.allowed


# Property: mixing slash styles doesn't change the outcome.
@pytest.mark.parametrize("traversal", [
    "..\\..\\outside.txt",
    "../..\\outside.txt",
    "..\\../outside.txt",
    "MyProj/../..\\outside.txt",
])
def test_traversal_with_mixed_separators_is_denied(sandbox, traversal):
    decision = sandbox.authorize(traversal)
    assert not decision.allowed


# Property: every reserved device name is denied regardless of case,
# extension, or position in a longer path.
_RESERVED = ["CON", "PRN", "AUX", "NUL"] + [f"COM{i}" for i in range(1, 10)] + [f"LPT{i}" for i in range(1, 10)]


@pytest.mark.parametrize("name", _RESERVED)
@pytest.mark.parametrize("case_fn", [str.upper, str.lower, str.title])
@pytest.mark.parametrize("suffix", ["", ".txt", ".py", "."])
def test_reserved_device_name_matrix(sandbox, name, case_fn, suffix):
    decision = sandbox.authorize(f"MyProj/{case_fn(name)}{suffix}")
    assert not decision.allowed


# Property: trailing dots/spaces on a component (a well-known Windows
# quirk where CreateFile strips them) must not create a bypass - a
# request that would otherwise be denied stays denied with these appended.
@pytest.mark.parametrize("mutator", [
    lambda s: s + ".",
    lambda s: s + " ",
    lambda s: s + "..",
    lambda s: s + "  ",
])
def test_traversal_with_trailing_dot_or_space_is_still_denied(sandbox, mutator):
    decision = sandbox.authorize(mutator("MyProj/../../outside.txt"))
    assert not decision.allowed


# Property: absolute escape attempts at varying depth outside the
# workspace are all denied.
@pytest.mark.parametrize("suffix", [
    "Outside",
    "Outside/deeper",
    "Outside/deeper/still",
])
def test_absolute_escape_depth_matrix(sandbox, workspace, suffix):
    outside_root = workspace.parent / "NotProjects"
    decision = sandbox.authorize(str(outside_root / suffix))
    assert not decision.allowed


# Property: near-miss sibling directory names (prefix or suffix overlap
# with the real workspace name) are all denied - guards the relative_to
# containment approach across more than one concrete sibling name.
@pytest.mark.parametrize("sibling_name", [
    "ProjectsEvil", "ProjectsX", "XProjects", "Project", "Projects2",
    "Projects.evil", "Projects-backup",
])
def test_sibling_name_matrix_is_denied(sandbox, workspace, sibling_name):
    sibling = workspace.parent / sibling_name / "file.txt"
    decision = sandbox.authorize(str(sibling))
    assert not decision.allowed


# Property: malformed / empty-ish inputs are all denied, never raise.
@pytest.mark.parametrize("raw", ["", " ", "\t", "\n", "\x00", "a\x00b", "   \x00   "])
def test_malformed_input_matrix_is_denied_not_raised(sandbox, raw):
    decision = sandbox.authorize(raw)
    assert not decision.allowed
```

- [ ] **Step 2: Run the matrix**

Run: `python -m pytest tests/test_sandbox_adversarial.py -v`
Expected: PASS for every generated case (this task adds no new production
code — if anything fails here, it means Task 3's implementation has a real
gap and must be fixed before moving on; do not proceed to Task 5 with a
failing case in this file).

---

### Task 5: Safe new-project creation

**Files:**
- Modify: `src/agent_platform/security/sandbox.py` (add
  `authorize_new_project` method to `FilesystemSandbox`)
- Create: `tests/test_sandbox_new_project.py`

**Interfaces:**
- Consumes: `FilesystemSandbox`, `PathDecision` from Task 3
- Produces: `FilesystemSandbox.authorize_new_project(self, project_name: str) -> PathDecision`,
  used directly by Phase 1's project-creation tool (not built in this plan)

- [ ] **Step 1: Write the failing tests**

`tests/test_sandbox_new_project.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sandbox_new_project.py -v`
Expected: FAIL with `AttributeError: 'FilesystemSandbox' object has no attribute 'authorize_new_project'`

- [ ] **Step 3: Add the method**

Add to `src/agent_platform/security/sandbox.py`, inside the
`FilesystemSandbox` class (after `authorize`):

```python
    def authorize_new_project(self, project_name: str) -> PathDecision:
        """Authorize creation of a brand-new project directly under the
        workspace root. Refuses if the name is unsafe, or if something
        already exists at that path - including as a reparse point, even
        one that would otherwise resolve back inside the workspace."""
        if not project_name or not project_name.strip():
            return PathDecision.deny("invalid project name")
        if any(c in project_name for c in '<>:"/\\|?*') or "\x00" in project_name:
            return PathDecision.deny("invalid project name")
        if project_name in (".", ".."):
            return PathDecision.deny("invalid project name")
        if _has_reserved_device_name(project_name):
            return PathDecision.deny("reserved Windows device name as project name")

        target = self.workspace_root / project_name
        try:
            st = os.stat(target, follow_symlinks=False)
        except FileNotFoundError:
            return PathDecision.allow(target)
        except OSError:
            return PathDecision.deny("failed to stat target project path")

        attrs = getattr(st, "st_file_attributes", 0)
        if attrs & FILE_ATTRIBUTE_REPARSE_POINT:
            return PathDecision.deny(
                "refusing to create project over an existing symlink/junction"
            )
        return PathDecision.deny("project already exists")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_sandbox_new_project.py -v`
Expected: PASS (all cases)

---

### Task 6: Permission evaluator

**Files:**
- Create: `src/agent_platform/security/permission.py`
- Create: `tests/test_permission.py`

**Interfaces:**
- Consumes: `Role`, `SessionMode`, `ToolPermission` (Task 2);
  `FilesystemSandbox`, `PathDecision` (Task 3)
- Produces:
  - `class ToolCall` (frozen dataclass): `role: Role`, `tool_name: str`,
    `path_argument: Optional[str] = None`, `scope_root: Optional[Path] = None`
  - `class PermissionDecision` (frozen dataclass): `permission:
    ToolPermission`, `reason: str`, property `is_denied`
  - `class PermissionEvaluator` with constructor
    `PermissionEvaluator(sandbox: FilesystemSandbox, tool_table: Optional[dict] = None)`
    and method
    `evaluate(self, call: ToolCall, session_mode: SessionMode) -> PermissionDecision`
  - `ABSOLUTE_DENY_TOOLS: frozenset[str]` — the git write operations and
    `shell.run`, exported for Phase 1's tool registry to cross-check against

- [ ] **Step 1: Write the failing tests**

`tests/test_permission.py`:
```python
import pytest

from agent_platform.security.enums import Role, SessionMode, ToolPermission
from agent_platform.security.permission import (
    ABSOLUTE_DENY_TOOLS,
    PermissionEvaluator,
    ToolCall,
)
from agent_platform.security.sandbox import FilesystemSandbox


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    (root / "MyProj").mkdir()
    return root


@pytest.fixture
def evaluator(workspace):
    sandbox = FilesystemSandbox(workspace)
    return PermissionEvaluator(sandbox)


def test_coder_filesystem_write_allowed_in_auto_mode(evaluator, workspace):
    call = ToolCall(role=Role.CODER, tool_name="filesystem.write",
                     path_argument="MyProj/app.py", scope_root=(workspace / "MyProj").resolve())
    decision = evaluator.evaluate(call, SessionMode.AUTO)
    assert decision.permission == ToolPermission.ALLOW


def test_planner_filesystem_write_is_denied(evaluator, workspace):
    call = ToolCall(role=Role.PLANNER, tool_name="filesystem.write",
                     path_argument="MyProj/app.py", scope_root=(workspace / "MyProj").resolve())
    decision = evaluator.evaluate(call, SessionMode.AUTO)
    assert decision.permission == ToolPermission.DENY


def test_reviewer_filesystem_write_is_denied(evaluator, workspace):
    call = ToolCall(role=Role.REVIEWER, tool_name="filesystem.write",
                     path_argument="MyProj/app.py", scope_root=(workspace / "MyProj").resolve())
    decision = evaluator.evaluate(call, SessionMode.AUTO)
    assert decision.permission == ToolPermission.DENY


@pytest.mark.parametrize("role", list(Role))
def test_filesystem_read_allowed_for_every_role(evaluator, role):
    call = ToolCall(role=role, tool_name="filesystem.read", path_argument="MyProj/app.py")
    decision = evaluator.evaluate(call, SessionMode.AUTO)
    assert decision.permission == ToolPermission.ALLOW


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize("mode", list(SessionMode))
@pytest.mark.parametrize("tool", sorted(ABSOLUTE_DENY_TOOLS))
def test_absolute_deny_tools_are_always_denied(evaluator, role, mode, tool):
    call = ToolCall(role=role, tool_name=tool)
    decision = evaluator.evaluate(call, mode)
    assert decision.permission == ToolPermission.DENY


def test_unknown_tool_name_defaults_to_deny(evaluator):
    call = ToolCall(role=Role.CODER, tool_name="totally.made.up")
    decision = evaluator.evaluate(call, SessionMode.AUTO)
    assert decision.permission == ToolPermission.DENY


def test_allow_tool_with_denied_path_is_still_denied(evaluator, workspace, tmp_path):
    # Proves evaluation is NOT tool-name-only: filesystem.write is ALLOW
    # for CODER in principle, but a path escaping the project scope must
    # still deny the call.
    outside = tmp_path / "Outside" / "file.txt"
    call = ToolCall(role=Role.CODER, tool_name="filesystem.write",
                     path_argument=str(outside), scope_root=(workspace / "MyProj").resolve())
    decision = evaluator.evaluate(call, SessionMode.AUTO)
    assert decision.permission == ToolPermission.DENY


def test_confirmation_mode_downgrades_allow_to_confirm(evaluator, workspace):
    call = ToolCall(role=Role.CODER, tool_name="filesystem.write",
                     path_argument="MyProj/app.py", scope_root=(workspace / "MyProj").resolve())
    decision = evaluator.evaluate(call, SessionMode.CONFIRMATION)
    assert decision.permission == ToolPermission.CONFIRM


def test_manual_mode_downgrades_allow_to_confirm(evaluator, workspace):
    call = ToolCall(role=Role.CODER, tool_name="filesystem.write",
                     path_argument="MyProj/app.py", scope_root=(workspace / "MyProj").resolve())
    decision = evaluator.evaluate(call, SessionMode.MANUAL)
    assert decision.permission == ToolPermission.CONFIRM


@pytest.mark.parametrize("mode", list(SessionMode))
def test_deny_is_never_loosened_by_any_session_mode(evaluator, mode):
    call = ToolCall(role=Role.PLANNER, tool_name="filesystem.write", path_argument="MyProj/app.py")
    decision = evaluator.evaluate(call, mode)
    assert decision.permission == ToolPermission.DENY


def test_auto_mode_does_not_loosen_below_static_table():
    # A custom table entry pinned to CONFIRM must never become ALLOW under
    # AUTO - AUTO's ceiling is ALLOW, meaning "no additional restriction,"
    # not "force everything open."
    from agent_platform.security.permission import PermissionEvaluator, ToolCall
    from agent_platform.security.enums import Role, SessionMode, ToolPermission
    from agent_platform.security.sandbox import FilesystemSandbox
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        from pathlib import Path
        sandbox = FilesystemSandbox(Path(td))
        table = {(Role.CODER, "deps.install"): ToolPermission.CONFIRM}
        evaluator = PermissionEvaluator(sandbox, tool_table=table)
        call = ToolCall(role=Role.CODER, tool_name="deps.install")
        decision = evaluator.evaluate(call, SessionMode.AUTO)
        assert decision.permission == ToolPermission.CONFIRM
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_permission.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_platform.security.permission'`

- [ ] **Step 3: Write the implementation**

`src/agent_platform/security/permission.py`:
```python
"""Deterministic permission evaluation: role x session mode x tool x
concrete arguments x active project x filesystem path -> decision.

LLMs never make security decisions and prompts are not security controls -
this evaluator is the only thing that decides whether a tool call
proceeds, and it never consults model output to do so. Permission is
evaluated per invocation with concrete arguments, never by tool name
alone - see test_allow_tool_with_denied_path_is_still_denied.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .enums import Role, SessionMode, ToolPermission
from .sandbox import FilesystemSandbox

_TIER = {ToolPermission.DENY: 0, ToolPermission.CONFIRM: 1, ToolPermission.ALLOW: 2}
_TIER_TO_PERMISSION = {v: k for k, v in _TIER.items()}

_SESSION_CEILING = {
    SessionMode.AUTO: ToolPermission.ALLOW,
    SessionMode.CONFIRMATION: ToolPermission.CONFIRM,
    SessionMode.MANUAL: ToolPermission.CONFIRM,
}

# Absolute denies: no role, no session mode, no table entry can ever grant
# these. Git write operations are here because git is human-controlled -
# the agent never commits, never inits, never pushes. shell.run is here
# because Phase 0/1 ship with typed tools only, no unrestricted shell.
ABSOLUTE_DENY_TOOLS: frozenset[str] = frozenset({
    "git.init", "git.add", "git.commit", "git.push",
    "git.reset", "git.rebase", "shell.run",
})

ToolTable = dict[tuple[Role, str], ToolPermission]


def _default_tool_table() -> ToolTable:
    table: ToolTable = {}
    read_tools = [
        "filesystem.read", "filesystem.list",
        "git.status", "git.diff", "git.log", "git.branch",
    ]
    for role in Role:
        for tool in read_tools:
            table[(role, tool)] = ToolPermission.ALLOW
    table[(Role.CODER, "filesystem.write")] = ToolPermission.ALLOW
    table[(Role.CODER, "filesystem.create_directory")] = ToolPermission.ALLOW
    return table


@dataclass(frozen=True)
class ToolCall:
    role: Role
    tool_name: str
    path_argument: Optional[str] = None
    scope_root: Optional[Path] = None


@dataclass(frozen=True)
class PermissionDecision:
    permission: ToolPermission
    reason: str

    @property
    def is_denied(self) -> bool:
        return self.permission == ToolPermission.DENY


class PermissionEvaluator:
    def __init__(self, sandbox: FilesystemSandbox, tool_table: Optional[ToolTable] = None):
        self._sandbox = sandbox
        self._table: ToolTable = dict(_default_tool_table())
        if tool_table is not None:
            self._table.update(tool_table)

    def evaluate(self, call: ToolCall, session_mode: SessionMode) -> PermissionDecision:
        if call.tool_name in ABSOLUTE_DENY_TOOLS:
            return PermissionDecision(
                ToolPermission.DENY, f"{call.tool_name} is an absolute deny, no exceptions"
            )

        static_permission = self._table.get((call.role, call.tool_name), ToolPermission.DENY)
        if static_permission == ToolPermission.DENY:
            return PermissionDecision(
                ToolPermission.DENY,
                f"no ALLOW/CONFIRM grant for {call.role.value}:{call.tool_name}",
            )

        if call.path_argument is not None:
            path_decision = self._sandbox.authorize(call.path_argument, scope_root=call.scope_root)
            if not path_decision.allowed:
                return PermissionDecision(ToolPermission.DENY, f"sandbox denial: {path_decision.reason}")

        ceiling = _SESSION_CEILING[session_mode]
        effective_tier = min(_TIER[static_permission], _TIER[ceiling])
        effective = _TIER_TO_PERMISSION[effective_tier]
        return PermissionDecision(
            effective, f"{static_permission.value} capped by {session_mode.value} ceiling"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_permission.py -v`
Expected: PASS (all cases, including the full `Role` x `SessionMode` x
`ABSOLUTE_DENY_TOOLS` cross-product)

---

### Task 7: Configuration loading and validation

**Files:**
- Create: `src/agent_platform/config.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (standalone module)
- Produces: `class ConfigurationError(Exception)`, `class PlatformConfig`
  (frozen dataclass, field `workspace_root: Path`) with static method
  `PlatformConfig.load(workspace_root: str) -> PlatformConfig`. Phase 1's
  orchestrator constructs its `FilesystemSandbox` from
  `PlatformConfig.load(...).workspace_root` — this is the one place a
  workspace root string becomes trusted configuration, and it never reads
  that string from model output.

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:
```python
import pytest

from agent_platform.config import ConfigurationError, PlatformConfig


def test_valid_absolute_existing_directory_loads(tmp_path):
    config = PlatformConfig.load(str(tmp_path))
    assert config.workspace_root == tmp_path.resolve()


def test_relative_path_is_rejected():
    with pytest.raises(ConfigurationError):
        PlatformConfig.load("Projects")


def test_nonexistent_path_is_rejected(tmp_path):
    missing = tmp_path / "DoesNotExist"
    with pytest.raises(ConfigurationError):
        PlatformConfig.load(str(missing))


def test_file_instead_of_directory_is_rejected(tmp_path):
    f = tmp_path / "not_a_dir.txt"
    f.write_text("x")
    with pytest.raises(ConfigurationError):
        PlatformConfig.load(str(f))


def test_platform_config_is_immutable(tmp_path):
    config = PlatformConfig.load(str(tmp_path))
    with pytest.raises(Exception):
        config.workspace_root = tmp_path
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_platform.config'`

- [ ] **Step 3: Write the implementation**

`src/agent_platform/config.py`:
```python
"""Trusted configuration loading. The workspace root is read from here
only - never from LLM output, never inferred at runtime from something a
model said. `PlatformConfig.load` is the single place a plain string
becomes a validated, resolved Path the rest of the system trusts."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(Exception):
    pass


@dataclass(frozen=True)
class PlatformConfig:
    workspace_root: Path

    @staticmethod
    def load(workspace_root: str) -> "PlatformConfig":
        root = Path(workspace_root)
        if not root.is_absolute():
            raise ConfigurationError(f"workspace_root must be an absolute path, got: {workspace_root}")
        if not root.exists():
            raise ConfigurationError(f"workspace_root does not exist: {root}")
        if not root.is_dir():
            raise ConfigurationError(f"workspace_root is not a directory: {root}")
        return PlatformConfig(workspace_root=root.resolve(strict=True))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (all cases)

---

### Task 8: Specification versioning primitives

**Files:**
- Create: `src/agent_platform/spec/__init__.py`
- Create: `src/agent_platform/spec/versioning.py`
- Create: `tests/test_versioning.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces:
  - `class SpecVersion` (frozen dataclass): `spec_id: str`, `version:
    int`, `goals: tuple[str, ...]`, `constraints: tuple[str, ...]`,
    `acceptance_criteria: tuple[str, ...]`, `created_at: float`, property
    `version_label` (e.g. `"task-42-v1"`)
  - `class SpecVersionMismatchError(Exception)` with attributes `expected:
    str`, `actual: str`
  - `class SpecStore` with methods `create(spec_id, *, goals, constraints,
    acceptance_criteria) -> SpecVersion`, `latest(spec_id) -> SpecVersion`,
    `get(spec_id, version) -> SpecVersion`, `assert_current(spec_id,
    version_label) -> SpecVersion`
  - Phase 1's Coder/Reviewer invocation wrapper calls `assert_current`
    before ever constructing a model prompt, per the "every invocation
    identifies the specification version, mismatch is deterministically
    rejected" requirement.

- [ ] **Step 1: Write the failing tests**

`tests/test_versioning.py`:
```python
import dataclasses

import pytest

from agent_platform.spec.versioning import SpecStore, SpecVersionMismatchError


def test_create_first_version_is_v1():
    store = SpecStore()
    spec = store.create("task-1", goals=["build a thing"], constraints=[], acceptance_criteria=["tests pass"])
    assert spec.version == 1
    assert spec.version_label == "task-1-v1"


def test_create_second_version_increments():
    store = SpecStore()
    store.create("task-1", goals=["v1 goal"], constraints=[], acceptance_criteria=[])
    v2 = store.create("task-1", goals=["v2 goal"], constraints=[], acceptance_criteria=[])
    assert v2.version == 2
    assert v2.version_label == "task-1-v2"


def test_creating_a_new_version_does_not_mutate_the_previous_one():
    store = SpecStore()
    v1 = store.create("task-1", goals=["v1 goal"], constraints=[], acceptance_criteria=[])
    store.create("task-1", goals=["v2 goal"], constraints=[], acceptance_criteria=[])
    fetched_v1 = store.get("task-1", 1)
    assert fetched_v1.goals == ("v1 goal",)
    assert v1.goals == ("v1 goal",)


def test_latest_returns_the_most_recent_version():
    store = SpecStore()
    store.create("task-1", goals=["v1"], constraints=[], acceptance_criteria=[])
    v2 = store.create("task-1", goals=["v2"], constraints=[], acceptance_criteria=[])
    assert store.latest("task-1") == v2


def test_latest_on_unknown_spec_id_raises_key_error():
    store = SpecStore()
    with pytest.raises(KeyError):
        store.latest("does-not-exist")


def test_get_unknown_version_raises_key_error():
    store = SpecStore()
    store.create("task-1", goals=["v1"], constraints=[], acceptance_criteria=[])
    with pytest.raises(KeyError):
        store.get("task-1", 99)


def test_assert_current_passes_for_the_latest_version():
    store = SpecStore()
    store.create("task-1", goals=["v1"], constraints=[], acceptance_criteria=[])
    result = store.assert_current("task-1", "task-1-v1")
    assert result.version == 1


def test_assert_current_rejects_a_stale_version_after_amendment():
    store = SpecStore()
    store.create("task-1", goals=["v1"], constraints=[], acceptance_criteria=[])
    store.create("task-1", goals=["v2"], constraints=[], acceptance_criteria=[])
    with pytest.raises(SpecVersionMismatchError) as exc_info:
        store.assert_current("task-1", "task-1-v1")
    assert exc_info.value.expected == "task-1-v2"
    assert exc_info.value.actual == "task-1-v1"


def test_spec_version_is_immutable():
    store = SpecStore()
    spec = store.create("task-1", goals=["v1"], constraints=[], acceptance_criteria=[])
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.goals = ("tampered",)


def test_spec_version_fields_are_tuples_not_lists():
    store = SpecStore()
    spec = store.create("task-1", goals=["v1"], constraints=["c1"], acceptance_criteria=["a1"])
    assert isinstance(spec.goals, tuple)
    assert isinstance(spec.constraints, tuple)
    assert isinstance(spec.acceptance_criteria, tuple)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_versioning.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_platform.spec'`

- [ ] **Step 3: Write the implementation**

`src/agent_platform/spec/__init__.py`:
```python
```

`src/agent_platform/spec/versioning.py`:
```python
"""Immutable specification versioning primitives.

A task's requirements live in a SpecVersion. Amending requirements
creates a new SpecVersion; existing versions are never mutated - this is
enforced structurally (frozen dataclass, append-only store), not by
convention. Every Coder and Reviewer invocation is pinned to an exact
spec_id + version; SpecStore.assert_current deterministically rejects a
stale reference rather than silently operating against outdated
requirements.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SpecVersion:
    spec_id: str
    version: int
    goals: tuple[str, ...]
    constraints: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    created_at: float = field(default_factory=time.time)

    @property
    def version_label(self) -> str:
        return f"{self.spec_id}-v{self.version}"


class SpecVersionMismatchError(Exception):
    def __init__(self, expected: str, actual: str):
        super().__init__(
            f"specification version mismatch: expected {expected}, invocation pinned to {actual}"
        )
        self.expected = expected
        self.actual = actual


class SpecStore:
    """Append-only store of specification versions. Never mutates an
    existing version - amending requirements always creates version N+1."""

    def __init__(self) -> None:
        self._versions: dict[str, list[SpecVersion]] = {}

    def create(self, spec_id: str, *, goals, constraints, acceptance_criteria) -> SpecVersion:
        existing = self._versions.setdefault(spec_id, [])
        next_version = len(existing) + 1
        spec = SpecVersion(
            spec_id=spec_id,
            version=next_version,
            goals=tuple(goals),
            constraints=tuple(constraints),
            acceptance_criteria=tuple(acceptance_criteria),
        )
        existing.append(spec)
        return spec

    def latest(self, spec_id: str) -> SpecVersion:
        versions = self._versions.get(spec_id)
        if not versions:
            raise KeyError(f"no specification versions for {spec_id}")
        return versions[-1]

    def get(self, spec_id: str, version: int) -> SpecVersion:
        for v in self._versions.get(spec_id, []):
            if v.version == version:
                return v
        raise KeyError(f"{spec_id}-v{version} does not exist")

    def assert_current(self, spec_id: str, version_label: str) -> SpecVersion:
        current = self.latest(spec_id)
        if current.version_label != version_label:
            raise SpecVersionMismatchError(expected=current.version_label, actual=version_label)
        return current
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_versioning.py -v`
Expected: PASS (all cases)

---

### Task 9: Full suite run and Phase 0 report

**Files:**
- Create: `PHASE0_REPORT.md`

**Interfaces:**
- Consumes: all tasks above
- Produces: a written record of test results, implemented components,
  enforced security invariants, and any Windows-specific behavior that
  couldn't be verified in this environment — the artifact the user asked
  Phase 0 to end with.

- [ ] **Step 1: Run the complete test suite with verbose output**

Run: `python -m pytest tests/ -v --tb=short`

Record: total tests run, passed, failed, skipped (and which ones skipped
and why — expected skip candidate is
`test_symlink_in_path_is_denied` if this account lacks symlink privilege).

- [ ] **Step 2: Confirm no test required network, Ollama, or an LLM**

Run: `python -m pytest tests/ -v --tb=short -p no:cacheprovider` with no
network connection assumed available — all fixtures use `tmp_path` and real
local filesystem/subprocess (`mklink`) calls only. Confirm by inspection
that no test file imports `requests`, `httpx`, `ollama`, or anything
network-facing.

- [ ] **Step 3: Write `PHASE0_REPORT.md`**

```markdown
# Phase 0 Report

## Implemented
- Windows-aware filesystem sandbox (`security/sandbox.py`): path
  containment via `relative_to` (not string-prefix), traversal/absolute/
  drive-relative/root-relative/UNC/device-path rejection, reserved device
  name rejection, reparse-point detection on the pre-resolution path chain
  (catches junctions/symlinks even when they resolve back inside the
  workspace), `.git` protection, safe new-project creation refusing to
  overwrite an existing directory or reparse point.
- Deterministic permission evaluator (`security/permission.py`): role x
  tool x session-mode x concrete-path evaluation, DENY-absolute tools
  (all git writes, `shell.run`) unconditionally denied regardless of
  table or session mode, `DENY < CONFIRM < ALLOW` composition where
  session mode only ever tightens, never loosens.
- Trusted configuration loading (`config.py`): workspace root validated
  once at startup from a plain string, never from model output.
- Immutable specification versioning (`spec/versioning.py`): append-only
  `SpecStore`, frozen `SpecVersion`, deterministic rejection of a stale
  version reference via `SpecVersionMismatchError`.

## Test results
[fill in actual counts from Step 1's run: N passed, N failed, N skipped]

## Security invariants enforced and tested
- DENY overrides ALLOW and CONFIRM in every session mode (Task 6).
- Containment uses path-segment comparison, not string prefix - the
  sibling-prefix attack is explicitly tested against the naive check it
  avoids (Task 3).
- Reparse points (junctions confirmed via real `mklink /J`; symlinks
  attempted, see below) are denied even when their target resolves back
  inside the workspace, not just when they escape it (Task 3).
- `.git` is unreachable through generic filesystem authorization from
  anywhere in a project (Task 3).
- New project creation refuses to overwrite an existing directory or
  reparse point at the target path (Task 5).
- Permission evaluation is per-invocation with concrete arguments, not
  tool-name-only - proven by the ALLOW-tool-with-denied-path test (Task
  6).
- Specification versions are immutable and append-only; a stale version
  reference is deterministically rejected, not silently honored (Task 8).

## Windows-specific behavior not fully verified in this environment
- [fill in: did the symlink test run or skip? If it skipped, symlink-path
  denial is only proven via the junction tests' shared code path, not via
  an actual symlink on this machine - note this explicitly rather than
  claiming full coverage.]
- 8.3 short-name aliasing (e.g. `PROGRA~1`) was not tested - noted as an
  open concern in the original architecture review, not covered by this
  phase's test matrix.
- Unicode confusable/normalization tricks beyond trailing dot/space were
  not exhaustively tested.

## Remaining concerns
[fill in anything observed during the actual run - e.g. any test that
was flaky, any environment-specific quirk noticed]
```

Fill in the bracketed sections with the real output from Steps 1-2 before
treating this file as final.

- [ ] **Step 4: Do not proceed to Phase 1**

Per the standing instruction, stop here and report back to the user:
what was implemented, the real test pass/fail/skip counts, the security
invariants enforced, and the unresolved Windows-specific concerns from
`PHASE0_REPORT.md`. Wait for explicit direction before starting Phase 1.
