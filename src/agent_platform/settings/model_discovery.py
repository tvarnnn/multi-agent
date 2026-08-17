"""Optional, injectable local-model discovery. The real default queries
Ollama's own /api/tags endpoint but never raises and never blocks
startup - any network failure (unreachable, timeout, malformed response)
degrades to "availability unknown", exactly like OllamaModelProvider's
own injectable http_post keeps the deterministic test suite network-free
by construction (tests always inject a fake query_fn, never touch the
network).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable, Optional

from .schema import ModelSettings

DEFAULT_OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"


def _default_query_installed_models(timeout: float = 2.0) -> tuple:
    try:
        with urllib.request.urlopen(DEFAULT_OLLAMA_TAGS_URL, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        return tuple(m["name"] for m in data.get("models", []) if isinstance(m, dict) and "name" in m)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError):
        return ()


def discover_installed_models(query_fn: Optional[Callable[[], tuple]] = None) -> tuple:
    fn = query_fn or _default_query_installed_models
    try:
        return tuple(fn())
    except Exception:
        return ()


def describe_configured_models(models: ModelSettings, installed: Optional[tuple] = None) -> dict:
    described = {}
    for role in ("planner", "coder", "reviewer"):
        model_id = getattr(models, role)
        if model_id is None or installed is None:
            available = None
        else:
            available = model_id in installed
        described[role] = {"model_id": model_id, "available": available}
    return described
