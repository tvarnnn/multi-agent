"""Wraps any ModelProvider, enriching each role's context dict with a
real, bounded bundle from Phase 5's retrieval engine before delegating.
Orchestrator (Phase 1) is never touched: this is a drop-in ModelProvider,
constructed once and passed to Orchestrator exactly like FakeModelProvider
or OllamaModelProvider would be - the "Planner -> context retrieval" step
in the architecture diagram is this wrapper's plan()/code()/review()
gathering a bundle before ever calling the inner provider.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..context.bundle_builder import build_context_bundle
from ..context.limits import ContextLimits, DEFAULT_LIMITS
from ..context.role_context import build_coder_context, build_planner_context, build_reviewer_context
from ..context.staleness import ContextCache
from ..security.enums import Role, SessionMode
from ..tools.gateway import ToolGateway


class ContextAwareModelProvider:
    def __init__(self, inner, *, gateway: ToolGateway, session_mode: SessionMode,
                 project_root: Path, limits: ContextLimits = DEFAULT_LIMITS,
                 cache: Optional[ContextCache] = None):
        self._inner = inner
        self._gateway = gateway
        self._session_mode = session_mode
        self._project_root = project_root
        self._limits = limits
        self._cache = cache if cache is not None else ContextCache()

    def plan(self, context: dict) -> dict:
        enriched = dict(context)
        if "blocking_questions" in context:
            bundle = build_context_bundle(
                gateway=self._gateway, role=Role.PLANNER, session_mode=self._session_mode,
                project_root=self._project_root, reference_hints=tuple(context["blocking_questions"]),
                limits=self._limits, cache=self._cache,
            )
        else:
            bundle = build_planner_context(self._gateway, self._session_mode, self._project_root,
                                            context["request"], limits=self._limits, cache=self._cache)
        enriched["context_bundle"] = bundle
        return self._inner.plan(enriched)

    def code(self, context: dict) -> dict:
        enriched = dict(context)
        bundle = build_coder_context(self._gateway, self._session_mode, self._project_root,
                                      context["spec"], context.get("reviewer_feedback"),
                                      limits=self._limits, cache=self._cache)
        enriched["context_bundle"] = bundle
        return self._inner.code(enriched)

    def review(self, context: dict) -> dict:
        enriched = dict(context)
        bundle = build_reviewer_context(self._gateway, self._session_mode, self._project_root,
                                         context["spec"], context["coder_output"],
                                         limits=self._limits, cache=self._cache)
        enriched["context_bundle"] = bundle
        return self._inner.review(enriched)
