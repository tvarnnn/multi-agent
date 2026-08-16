"""The tool gateway is the only path from a model-requested tool call to
actual execution - for every role alike, no exceptions. Every invocation
passes through six steps, in order:

  1. schema validation    - is this a known tool, are arguments well-typed
  2. permission evaluation - role x session-mode x DENY-absolute x
     sandboxed path containment, via Phase 0's PermissionEvaluator (which
     is already path-aware, so this one call covers both the tool-level
     and path-level decision)
  3. argument/path preconditions - business-logic checks that aren't
     security-relevant but must hold before execution (e.g. a read
     target must actually exist) - by this point the path is already
     known-safe, so these are correctness checks, not security checks
  4. execute
  5. wrap as a structured ToolObservation
  6. log the event

No step is ever skipped, and no step behaves differently by role - the
Planner, Coder, and Reviewer all go through exactly this pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..events import EventLog, EventType
from ..security.enums import Role, SessionMode, ToolPermission
from ..security.permission import PermissionEvaluator, ToolCall
from .registry import ToolRegistry
from .schemas import ToolArgumentError, ToolExecutionContext, ToolPreconditionError


@dataclass(frozen=True)
class ToolObservation:
    status: str
    tool_name: str
    result: Optional[dict]
    error: Optional[str]


class ToolGateway:
    def __init__(self, registry: ToolRegistry, evaluator: PermissionEvaluator, event_log: EventLog):
        self._registry = registry
        self._evaluator = evaluator
        self.event_log = event_log

    def invoke(self, *, role: Role, tool_name: str, arguments: dict,
               session_mode: SessionMode, project_root: Path) -> ToolObservation:
        # 1. schema validation
        spec = self._registry.get(tool_name)
        if spec is None:
            return self._finish(role, tool_name, arguments, ToolObservation(
                status="unknown_tool", tool_name=tool_name, result=None,
                error=f"no such tool: {tool_name}"))
        try:
            validated_args = spec.validate_arguments(arguments)
        except ToolArgumentError as exc:
            return self._finish(role, tool_name, arguments, ToolObservation(
                status="invalid_schema", tool_name=tool_name, result=None, error=str(exc)))

        # 2. permission evaluation (role x session-mode x DENY-absolute x sandboxed path)
        path_argument = validated_args.get(spec.path_argument_key) if spec.path_argument_key else None
        call = ToolCall(role=role, tool_name=tool_name, path_argument=path_argument, scope_root=project_root)
        decision = self._evaluator.evaluate(call, session_mode)
        if decision.permission == ToolPermission.DENY:
            return self._finish(role, tool_name, arguments, ToolObservation(
                status="denied", tool_name=tool_name, result=None, error=decision.reason))
        if decision.permission == ToolPermission.CONFIRM:
            return self._finish(role, tool_name, arguments, ToolObservation(
                status="requires_confirmation", tool_name=tool_name, result=None, error=decision.reason))

        # 3. argument/path preconditions
        ctx = ToolExecutionContext(resolved_path=decision.resolved_path, project_root=project_root)
        try:
            spec.check_preconditions(validated_args, ctx)
        except ToolPreconditionError as exc:
            return self._finish(role, tool_name, arguments, ToolObservation(
                status="error", tool_name=tool_name, result=None, error=str(exc)))

        # 4-5. execute + wrap
        try:
            result = spec.execute(validated_args, ctx)
            obs = ToolObservation(status="ok", tool_name=tool_name, result=result, error=None)
        except Exception as exc:
            obs = ToolObservation(status="error", tool_name=tool_name, result=None, error=str(exc))

        # 6. log
        return self._finish(role, tool_name, arguments, obs)

    def _finish(self, role: Role, tool_name: str, arguments: dict, obs: ToolObservation) -> ToolObservation:
        event_type = EventType.TOOL_INVOKED if obs.status == "ok" else EventType.TOOL_DENIED
        self.event_log.emit(event_type, "internal", {
            "role": role.value, "tool": tool_name, "arguments": arguments,
            "status": obs.status, "error": obs.error,
        })
        return obs
