"""Typed tool registry: filesystem.read/write/create_directory/list,
read-only git.status/diff/log/branch, and test.run/lint.run/typecheck.run.
No shell.run, no git write operations, no arbitrary executable - those
simply have no ToolSpec here (git writes), or (validation tools) accept
no argument that could select an executable or command at all - see
process_execution.py for what that execution boundary does and doesn't
guarantee. A lookup for an unregistered tool returns None and the gateway
reports "unknown_tool" before permission is even evaluated. (Permission
evaluation would deny git writes too, per Phase 0's ABSOLUTE_DENY_TOOLS -
not having a handler is defense in depth, not the only defense.)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

from .process_execution import run_process
from .schemas import ToolArgumentError, ToolExecutionContext, ToolPreconditionError, ToolSpec


def _no_precondition(args: dict, ctx: ToolExecutionContext) -> None:
    return None


def _validate_path_only(args: dict) -> dict:
    if not isinstance(args, dict):
        raise ToolArgumentError("arguments must be an object")
    path = args.get("path")
    if not isinstance(path, str) or not path.strip():
        raise ToolArgumentError("missing or invalid required field: path")
    return {"path": path}


def _validate_write_args(args: dict) -> dict:
    validated = _validate_path_only(args)
    content = args.get("content")
    if not isinstance(content, str):
        raise ToolArgumentError("missing or invalid required field: content")
    validated["content"] = content
    return validated


def _validate_no_args(args: dict) -> dict:
    if not isinstance(args, dict):
        raise ToolArgumentError("arguments must be an object")
    return {}


def _require_existing_file(args: dict, ctx: ToolExecutionContext) -> None:
    if ctx.resolved_path is None or not ctx.resolved_path.is_file():
        raise ToolPreconditionError(f"file does not exist: {args.get('path')}")


def _require_existing_directory(args: dict, ctx: ToolExecutionContext) -> None:
    if ctx.resolved_path is None or not ctx.resolved_path.is_dir():
        raise ToolPreconditionError(f"directory does not exist: {args.get('path')}")


def _execute_filesystem_read(args: dict, ctx: ToolExecutionContext) -> dict:
    return {"content": ctx.resolved_path.read_text(encoding="utf-8")}


def _execute_filesystem_write(args: dict, ctx: ToolExecutionContext) -> dict:
    ctx.resolved_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.resolved_path.write_text(args["content"], encoding="utf-8")
    return {"written": str(ctx.resolved_path)}


def _execute_filesystem_create_directory(args: dict, ctx: ToolExecutionContext) -> dict:
    ctx.resolved_path.mkdir(parents=True, exist_ok=True)
    return {"created": str(ctx.resolved_path)}


def _execute_filesystem_list(args: dict, ctx: ToolExecutionContext) -> dict:
    return {"entries": sorted(p.name for p in ctx.resolved_path.iterdir())}


# Neutralizes two confirmed config-driven code-execution vectors on
# otherwise-read-only git operations: a malicious .git/config can set
# core.fsmonitor or diff.external to an arbitrary command, which git
# will execute during plain `status`/`diff` calls. --no-pager is
# standard hardening for any scripted/non-interactive git invocation.
# Verified: a pre-commit hook does NOT fire on these read-only commands,
# so it is not included here - only confirmed-exploitable vectors are
# neutralized, not a speculative list.
_GIT_SAFETY_FLAGS = ["--no-pager", "-c", "core.fsmonitor=", "-c", "diff.external="]


def _git_toplevel(cwd: Path) -> Optional[Path]:
    try:
        result = subprocess.run(
            ["git", *_GIT_SAFETY_FLAGS, "rev-parse", "--show-toplevel"],
            cwd=str(cwd), capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def _git_scoped_root(ctx: ToolExecutionContext) -> Optional[Path]:
    """Returns the project root only if git's own toplevel for that
    directory matches it exactly - never an enclosing repo. See the
    stray-outer-repo hazard documented in architecture-review-v4."""
    toplevel = _git_toplevel(ctx.project_root)
    if toplevel is None or toplevel != ctx.project_root.resolve():
        return None
    return toplevel


def _run_git_readonly(args: list[str], cwd: Path) -> str:
    result = subprocess.run(["git", *_GIT_SAFETY_FLAGS, *args], cwd=str(cwd),
                             capture_output=True, text=True, timeout=10)
    return result.stdout


def _execute_git_status(args: dict, ctx: ToolExecutionContext) -> dict:
    scoped = _git_scoped_root(ctx)
    if scoped is None:
        return {"scoped": False, "message": "no git repository scoped to this project"}
    return {"scoped": True, "output": _run_git_readonly(["status", "--porcelain"], scoped)}


def _execute_git_diff(args: dict, ctx: ToolExecutionContext) -> dict:
    scoped = _git_scoped_root(ctx)
    if scoped is None:
        return {"scoped": False, "message": "no git repository scoped to this project"}
    return {"scoped": True, "output": _run_git_readonly(["diff"], scoped)}


def _execute_git_log(args: dict, ctx: ToolExecutionContext) -> dict:
    scoped = _git_scoped_root(ctx)
    if scoped is None:
        return {"scoped": False, "message": "no git repository scoped to this project"}
    return {"scoped": True, "output": _run_git_readonly(["log", "--oneline"], scoped)}


def _execute_git_branch(args: dict, ctx: ToolExecutionContext) -> dict:
    scoped = _git_scoped_root(ctx)
    if scoped is None:
        return {"scoped": False, "message": "no git repository scoped to this project"}
    return {"scoped": True, "output": _run_git_readonly(["branch", "--show-current"], scoped).strip()}


_VALIDATION_TOOL_COMMANDS: dict[str, list[str]] = {
    # -P (isolated mode, Python 3.11+): does NOT prepend the current
    # working directory to sys.path. Without it, "python -m pytest" run
    # with cwd set to the sandboxed (Coder-controlled) project directory
    # will import a same-named pytest.py FROM THAT PROJECT instead of the
    # real installed package - verified exploitable on this machine
    # before this fix, verified closed after it (see
    # test_security_executable_substitution.py).
    "test.run": [sys.executable, "-P", "-m", "pytest"],
    "lint.run": [sys.executable, "-P", "-m", "ruff", "check"],
    "typecheck.run": [sys.executable, "-P", "-m", "mypy"],
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
    if (not isinstance(timeout, (int, float)) or isinstance(timeout, bool)
            or not (0 < timeout <= _MAX_VALIDATION_TIMEOUT_SECONDS)):
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


class ToolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._specs[spec.name] = spec

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._specs.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs.keys()))


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ToolSpec(
        name="filesystem.read", validate_arguments=_validate_path_only,
        path_argument_key="path", check_preconditions=_require_existing_file,
        execute=_execute_filesystem_read,
    ))
    registry.register(ToolSpec(
        name="filesystem.write", validate_arguments=_validate_write_args,
        path_argument_key="path", check_preconditions=_no_precondition,
        execute=_execute_filesystem_write,
    ))
    registry.register(ToolSpec(
        name="filesystem.create_directory", validate_arguments=_validate_path_only,
        path_argument_key="path", check_preconditions=_no_precondition,
        execute=_execute_filesystem_create_directory,
    ))
    registry.register(ToolSpec(
        name="filesystem.list", validate_arguments=_validate_path_only,
        path_argument_key="path", check_preconditions=_require_existing_directory,
        execute=_execute_filesystem_list,
    ))
    for name, handler in (
        ("git.status", _execute_git_status), ("git.diff", _execute_git_diff),
        ("git.log", _execute_git_log), ("git.branch", _execute_git_branch),
    ):
        registry.register(ToolSpec(
            name=name, validate_arguments=_validate_no_args,
            path_argument_key=None, check_preconditions=_no_precondition,
            execute=handler,
        ))
    for tool_name, base_argv in _VALIDATION_TOOL_COMMANDS.items():
        registry.register(ToolSpec(
            name=tool_name, validate_arguments=_validate_validation_args,
            path_argument_key="target", check_preconditions=_no_precondition,
            execute=_make_validation_executor(base_argv),
        ))
    return registry
