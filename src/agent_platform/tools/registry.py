"""Typed tool registry: filesystem.read/write/create_directory/list and
read-only git.status/diff/log/branch. No shell.run, no git write
operations - those simply have no ToolSpec here, so a lookup for them
returns None and the gateway reports "unknown_tool" before permission is
even evaluated. (Permission evaluation would deny them too, per Phase 0's
ABSOLUTE_DENY_TOOLS - not having a handler is defense in depth, not the
only defense.)
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

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


def _git_toplevel(cwd: Path) -> Optional[Path]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
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
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=10)
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
    return registry
