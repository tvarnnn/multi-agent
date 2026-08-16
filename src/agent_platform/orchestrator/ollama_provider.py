"""Real ModelProvider backed by Ollama's HTTP API. Drop-in replacement
for FakeModelProvider - Orchestrator imports neither this module nor
fake_model.py, it only ever calls .plan/.code/.review on whatever it was
constructed with.

Kept replaceable for a future llama.cpp-direct provider: the transport
(default_http_post) is injectable, and everything above the transport
(prompt building, schema selection, retry, lifecycle, telemetry) is
Ollama-specific but structurally the same shape a llama.cpp provider
would need.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

from .fake_model import ModelTimeoutError
from .ollama_schemas import CODER_SCHEMA, PLANNER_SCHEMA, REVIEWER_SCHEMA
from .prompts import build_coder_prompt, build_planner_prompt, build_reviewer_prompt


class OllamaTransportError(Exception):
    pass


def default_http_post(url: str, payload: dict, timeout: float) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OllamaTransportError(str(exc)) from exc


@dataclass(frozen=True)
class OllamaCallResult:
    load_duration_ns: int
    eval_duration_ns: int
    total_duration_ns: int
    prompt_eval_count: int
    eval_count: int


class OllamaModelProvider:
    def __init__(self, *, planner_model: str, coder_model: str, reviewer_model: str,
                 base_url: str = "http://localhost:11434",
                 http_post: Callable[[str, dict, float], dict] = default_http_post,
                 timeout_seconds: float = 120.0, max_transport_retries: int = 2):
        self._planner_model = planner_model
        self._coder_model = coder_model
        self._reviewer_model = reviewer_model
        self._base_url = base_url
        self._http_post = http_post
        self._timeout_seconds = timeout_seconds
        self._max_transport_retries = max_transport_retries
        self._loaded_model: Optional[str] = None
        self.telemetry_log: list[OllamaCallResult] = []

    def plan(self, context: dict) -> dict:
        return self._invoke(self._planner_model, build_planner_prompt(context), PLANNER_SCHEMA)

    def code(self, context: dict) -> dict:
        return self._invoke(self._coder_model, build_coder_prompt(context), CODER_SCHEMA)

    def review(self, context: dict) -> dict:
        return self._invoke(self._reviewer_model, build_reviewer_prompt(context), REVIEWER_SCHEMA)

    def _ensure_loaded(self, model_name: str) -> None:
        """Explicitly unload a different previously-loaded model before
        switching, rather than trusting Ollama's automatic multi-model
        residency - two 14B-class models resident at once would leave
        near-zero VRAM headroom on a 12GB card. A failed unload is
        best-effort, not fatal - the new call still proceeds."""
        if self._loaded_model is not None and self._loaded_model != model_name:
            try:
                self._http_post(f"{self._base_url}/api/generate",
                                 {"model": self._loaded_model, "keep_alive": 0}, self._timeout_seconds)
            except OllamaTransportError:
                pass
        self._loaded_model = model_name

    def _invoke(self, model_name: str, prompt: str, schema: dict) -> dict:
        self._ensure_loaded(model_name)
        payload = {"model": model_name, "prompt": prompt, "format": schema, "stream": False}
        last_error: Optional[Exception] = None
        response = None
        for _ in range(self._max_transport_retries):
            try:
                response = self._http_post(f"{self._base_url}/api/generate", payload, self._timeout_seconds)
                break
            except OllamaTransportError as exc:
                last_error = exc
                continue
        if response is None:
            raise ModelTimeoutError(
                f"transport failed after {self._max_transport_retries} attempts: {last_error}"
            )

        self.telemetry_log.append(OllamaCallResult(
            load_duration_ns=response.get("load_duration", 0),
            eval_duration_ns=response.get("eval_duration", 0),
            total_duration_ns=response.get("total_duration", 0),
            prompt_eval_count=response.get("prompt_eval_count", 0),
            eval_count=response.get("eval_count", 0),
        ))

        text = response.get("response", "")
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return {"_malformed_raw_text": text}
