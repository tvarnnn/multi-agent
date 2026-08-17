"""Formalizes the ModelProvider contract Orchestrator already relies on
via duck typing (see orchestrator/core.py's constructor, which accepts
any object with .plan/.code/.review). FakeModelProvider (Phase 1) and
OllamaModelProvider (Phase 2, and any future llama.cpp provider) all
satisfy this without inheriting from it - it exists so provider
implementations and their tests have one shared, explicit contract to
type against.
"""
from __future__ import annotations

from typing import Protocol


class ModelProvider(Protocol):
    def plan(self, context: dict) -> dict: ...
    def code(self, context: dict) -> dict: ...
    def review(self, context: dict) -> dict: ...
    # Planning Mode (Phase 9) - Coder is structurally absent from this
    # protocol's Plan/Chat/Review-mode surface; nothing here can reach
    # .code().
    def plan_mode(self, context: dict) -> dict: ...
    def review_plan(self, context: dict) -> dict: ...
    def chat(self, context: dict) -> dict: ...
    def review_session(self, context: dict) -> dict: ...
