"""Typed-tool building blocks: the exceptions and dataclasses ToolSpec
implementations (registry.py) and the gateway (gateway.py) share. Kept
separate from registry.py so the vocabulary (what an argument error vs a
precondition error means) is easy to find without wading through every
tool's concrete implementation.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional


class ToolArgumentError(Exception):
    """Raised when a tool call's arguments don't match its schema - wrong
    type, missing required field. Caught by the gateway before permission
    is ever evaluated (there's nothing safe to check permission against
    yet)."""


class ToolPreconditionError(Exception):
    """Raised when arguments are well-typed and the path is sandbox-
    authorized, but a business-logic precondition still fails - e.g.
    reading a file that doesn't exist. Distinct from ToolArgumentError:
    this is caught *after* permission evaluation, never before."""


@dataclass(frozen=True)
class ToolExecutionContext:
    resolved_path: Optional[Path]
    project_root: Path


@dataclass(frozen=True)
class ToolSpec:
    name: str
    validate_arguments: Callable[[dict], dict]
    path_argument_key: Optional[str]
    check_preconditions: Callable[[dict, ToolExecutionContext], None]
    execute: Callable[[dict, ToolExecutionContext], Any]
