"""A scriptable model provider for testing the orchestrator without a
GPU, an LLM, Ollama, or MCP. Each role's responses are a pre-configured
queue of raw dicts (standing in for parsed model JSON, including
deliberately malformed ones) popped in order. ModelExhaustedError means
the test script ran out of responses - a test bug, never a real
orchestrator scenario - and the orchestrator never catches it.
"""
from __future__ import annotations


class ModelTimeoutError(Exception):
    pass


class ModelExhaustedError(Exception):
    pass


class _TimeoutSentinel:
    def __repr__(self) -> str:
        return "TIMEOUT"


TIMEOUT = _TimeoutSentinel()


class FakeModelProvider:
    def __init__(self, *, planner_responses=(), coder_responses=(), reviewer_responses=()):
        self._planner = list(planner_responses)
        self._coder = list(coder_responses)
        self._reviewer = list(reviewer_responses)

    def plan(self, context) -> dict:
        return self._pop(self._planner, "planner")

    def code(self, context) -> dict:
        return self._pop(self._coder, "coder")

    def review(self, context) -> dict:
        return self._pop(self._reviewer, "reviewer")

    def _pop(self, queue: list, role_name: str) -> dict:
        if not queue:
            raise ModelExhaustedError(f"no more scripted {role_name} responses")
        item = queue.pop(0)
        if item is TIMEOUT:
            raise ModelTimeoutError(f"{role_name} call timed out")
        return item
