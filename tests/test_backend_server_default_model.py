"""Phase 12 gap found while preparing the real live end-to-end test: the
CLI entrypoint (python -m agent_platform.server) never passed a `model`
to run()/build_server()/build_services() - `model` stayed None all the
way through, so ANY live session would crash the instant it reached
`None.chat(...)`/`None.plan(...)`. This wires build_services() to
construct a real OllamaModelProvider (Phase 2, unmodified) when model is
omitted, using Phase 11's already-built ModelSettings (falling back to
the same real model names already used by test_ollama_integration.py and
scripts/live_run.py). No new dependency - OllamaModelProvider already
existed; this only adds the missing "construct one by default" wiring.
"""
import pytest

from agent_platform.orchestrator.fake_model import FakeModelProvider
from agent_platform.orchestrator.ollama_provider import OllamaModelProvider
from agent_platform.server import DEFAULT_CODER_MODEL, DEFAULT_PLANNER_MODEL, DEFAULT_REVIEWER_MODEL, build_services


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    proj = root / "MyProj"
    proj.mkdir()
    return proj


def test_omitting_model_constructs_a_real_ollama_provider(workspace):
    services = build_services(workspace, None)
    assert isinstance(services.model, OllamaModelProvider)


def test_explicit_model_is_still_used_unchanged(workspace):
    fake = FakeModelProvider()
    services = build_services(workspace, fake)
    assert services.model is fake


def test_default_ollama_provider_uses_hardcoded_fallback_model_names(workspace):
    services = build_services(workspace, None)
    assert services.model._planner_model == DEFAULT_PLANNER_MODEL
    assert services.model._coder_model == DEFAULT_CODER_MODEL
    assert services.model._reviewer_model == DEFAULT_REVIEWER_MODEL


def test_settings_file_model_names_override_the_hardcoded_fallback(workspace):
    agent_dir = workspace / ".agent"
    agent_dir.mkdir()
    (agent_dir / "settings.yaml").write_text(
        "models:\n  coder: my-custom-coder-model:7b\n", encoding="utf-8",
    )
    services = build_services(workspace, None)
    assert services.model._coder_model == "my-custom-coder-model:7b"
    assert services.model._planner_model == DEFAULT_PLANNER_MODEL  # unset in settings -> fallback
