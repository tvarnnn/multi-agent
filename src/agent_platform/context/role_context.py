"""Role-specific context entry points. Each function reads only the
inputs its role is allowed to see: build_coder_context has no parameter
for raw user conversation at all - a structural guarantee, not a
filtering step - and build_reviewer_context reads only file_writes paths
from the Coder's output, never .summary (the Coder's own narrative). This
is the same "pass facts, not narrative" choice orchestrator/prompts.py
made for the model-prompt layer in Phase 2, made again here for context
retrieval.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..security.enums import OperatingMode, Role
from .bundle import ContextBundle
from .bundle_builder import build_context_bundle
from .limits import ContextLimits, DEFAULT_LIMITS
from .staleness import ContextCache


def build_planner_context(gateway, session_mode, project_root: Path, user_request: str,
                           limits: ContextLimits = DEFAULT_LIMITS,
                           cache: Optional[ContextCache] = None,
                           operating_mode: OperatingMode = OperatingMode.CODE) -> ContextBundle:
    return build_context_bundle(gateway=gateway, role=Role.PLANNER, session_mode=session_mode,
                                 project_root=project_root, reference_hints=(user_request,),
                                 include_git_changes=True, limits=limits, cache=cache,
                                 operating_mode=operating_mode)


def build_coder_context(gateway, session_mode, project_root: Path, spec, reviewer_feedback=None,
                         limits: ContextLimits = DEFAULT_LIMITS,
                         cache: Optional[ContextCache] = None,
                         operating_mode: OperatingMode = OperatingMode.CODE) -> ContextBundle:
    hints = list(spec.goals) + list(spec.constraints) + list(spec.acceptance_criteria)
    if reviewer_feedback is not None:
        hints += [issue.file for issue in reviewer_feedback.issues]
        hints += [issue.required_fix for issue in reviewer_feedback.issues]
    return build_context_bundle(gateway=gateway, role=Role.CODER, session_mode=session_mode,
                                 project_root=project_root, reference_hints=tuple(hints),
                                 include_git_changes=True, limits=limits, cache=cache,
                                 operating_mode=operating_mode)


def build_reviewer_context(gateway, session_mode, project_root: Path, spec, coder_output,
                            limits: ContextLimits = DEFAULT_LIMITS,
                            cache: Optional[ContextCache] = None,
                            operating_mode: OperatingMode = OperatingMode.CODE) -> ContextBundle:
    hints = list(spec.goals) + list(spec.constraints) + list(spec.acceptance_criteria)
    hints += [w.path for w in coder_output.file_writes]
    return build_context_bundle(gateway=gateway, role=Role.REVIEWER, session_mode=session_mode,
                                 project_root=project_root, reference_hints=tuple(hints),
                                 include_git_changes=True, limits=limits, cache=cache,
                                 operating_mode=operating_mode)
