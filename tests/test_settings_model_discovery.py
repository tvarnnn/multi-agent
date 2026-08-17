import urllib.error

from agent_platform.settings import model_discovery
from agent_platform.settings.model_discovery import describe_configured_models, discover_installed_models
from agent_platform.settings.schema import ModelSettings


# ------------------------------------------------------- discover_installed_models

def test_uses_injected_query_fn():
    result = discover_installed_models(query_fn=lambda: ("qwen2.5-coder:14b", "phi4-reasoning:plus"))
    assert result == ("qwen2.5-coder:14b", "phi4-reasoning:plus")


def test_query_fn_raising_returns_empty_tuple_not_an_exception():
    def _boom():
        raise ConnectionError("ollama not reachable")
    assert discover_installed_models(query_fn=_boom) == ()


def test_default_query_fn_never_raises_when_ollama_unreachable(monkeypatch):
    """Exercises the real default's exception handling without touching the
    real network - this deterministic suite must stay network-free (the
    same invariant Phase 0 established and Phase 2's real-Ollama tests are
    deliberately excluded to preserve)."""
    def _raise_unreachable(*args, **kwargs):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr(model_discovery.urllib.request, "urlopen", _raise_unreachable)
    assert discover_installed_models() == ()


# ------------------------------------------------------- describe_configured_models

def test_describe_with_no_installed_list_reports_unknown_availability():
    models = ModelSettings(planner="phi4-reasoning:plus", coder="qwen2.5-coder:14b", reviewer=None)
    described = describe_configured_models(models, installed=None)
    assert described["planner"] == {"model_id": "phi4-reasoning:plus", "available": None}
    assert described["reviewer"] == {"model_id": None, "available": None}


def test_describe_with_installed_list_reports_availability():
    models = ModelSettings(planner="phi4-reasoning:plus", coder="not-installed:1b")
    described = describe_configured_models(models, installed=("phi4-reasoning:plus", "llama3.1:8b"))
    assert described["planner"]["available"] is True
    assert described["coder"]["available"] is False


def test_describe_covers_all_three_roles():
    described = describe_configured_models(ModelSettings(), installed=())
    assert set(described.keys()) == {"planner", "coder", "reviewer"}
