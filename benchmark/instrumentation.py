"""Non-invasive, benchmark-only measurement wrappers. Every class here
wraps a real, unmodified Phase 2/5/6 object and records timing/decisions
around it - none of them change behavior. Two TimingWrapper instances are
stacked around the real provider (inner, around raw OllamaModelProvider;
outer, around ContextAwareModelProvider) so that
outer_duration - inner_duration isolates context-retrieval time without
touching context_aware_provider.py or bundle_builder.py.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from agent_platform.orchestrator.gpu_telemetry import query_gpu_memory


@dataclass
class CallRecord:
    method: str  # "plan" / "code" / "review"
    duration_s: float
    context_keys: tuple  # sorted keys of the context dict passed in, for post-hoc inspection
    validation_passed: Optional[bool] = None  # only populated for "review" calls
    reviewer_decision: Optional[str] = None  # only populated for "review" calls, raw dict value


class TimingWrapper:
    def __init__(self, inner, label: str):
        self._inner = inner
        self.label = label
        self.calls: list[CallRecord] = []

    def plan(self, context: dict) -> dict:
        return self._timed("plan", context)

    def code(self, context: dict) -> dict:
        return self._timed("code", context)

    def review(self, context: dict) -> dict:
        t0 = time.monotonic()
        result = self._inner.review(context)
        duration = time.monotonic() - t0
        validation_result = context.get("validation_result")
        record = CallRecord(
            method="review", duration_s=duration, context_keys=tuple(sorted(context.keys())),
            validation_passed=(validation_result.passed if validation_result is not None else None),
            reviewer_decision=result.get("decision") if isinstance(result, dict) else None,
        )
        self.calls.append(record)
        return result

    def _timed(self, method: str, context: dict) -> dict:
        t0 = time.monotonic()
        result = getattr(self._inner, method)(context)
        duration = time.monotonic() - t0
        self.calls.append(CallRecord(method=method, duration_s=duration, context_keys=tuple(sorted(context.keys()))))
        return result


class VramSampler:
    """Samples nvidia-smi on a background thread every poll_interval_s
    while active. Records min/max/samples so a run's peak VRAM usage is
    captured even between model calls, not just at call boundaries."""

    def __init__(self, poll_interval_s: float = 0.5):
        self._poll_interval_s = poll_interval_s
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.samples: list[int] = []

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            reading = query_gpu_memory()
            if reading is not None:
                self.samples.append(reading["used_mib"])
            self._stop.wait(self._poll_interval_s)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    @property
    def peak_mib(self) -> Optional[int]:
        return max(self.samples) if self.samples else None

    @property
    def baseline_mib(self) -> Optional[int]:
        return min(self.samples) if self.samples else None
