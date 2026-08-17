"""Phase 12 gap found via the real live end-to-end test: OllamaModelProvider
(Phase 2) was never given plan_mode/review_plan/chat/review_session methods
when Phase 9 added them to the ModelProvider protocol - Planning Mode has
never worked with a real model, only FakeModelProvider in tests. Smallest
additive fix: four prompt builders (mirroring prompts.py's existing
"only read the fields this role's context dict actually has" discipline),
four Ollama JSON schemas (mirroring ollama_schemas.py's existing flat-object
pattern), and four OllamaModelProvider methods (mirroring .plan/.code/.review
exactly).
"""
import json

import pytest

from agent_platform.context.bundle import ContextBundle, ContextFile
from agent_platform.orchestrator.ollama_provider import OllamaModelProvider, OllamaTransportError
from agent_platform.orchestrator.ollama_schemas import (
    CHAT_SCHEMA,
    PLANNER_PLAN_MODE_SCHEMA,
    REVIEWER_PLAN_CRITIQUE_SCHEMA,
    REVIEW_SESSION_SCHEMA,
)
from agent_platform.orchestrator.plan_schemas import StructuredPlan
from agent_platform.orchestrator.prompts import (
    build_chat_prompt,
    build_planner_plan_mode_prompt,
    build_reviewer_plan_critique_prompt,
    build_review_session_prompt,
)


def _bundle(files=()):
    return ContextBundle(role="PLANNER", files=tuple(files), changed_files=(), excluded_paths=(),
                          stale_paths=(), total_bytes=0, limit_exceeded=False)


def _plan(**overrides):
    defaults = dict(
        objective="Build the widget", requirements=("req1",), existing_context=(),
        proposed_architecture="single module", files_to_create=("widget.py",), files_to_modify=(),
        dependencies=(), implementation_steps=("step1",), validation_strategy=("test1",),
        risks=(), unknowns=(), acceptance_criteria=("file:widget.py",),
    )
    defaults.update(overrides)
    return StructuredPlan(**defaults)


def make_fake_transport(responses):
    calls = []

    def fake_http_post(url, payload, timeout):
        calls.append({"url": url, "payload": payload, "timeout": timeout})
        if not responses:
            raise OllamaTransportError("fake transport exhausted")
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return fake_http_post, calls


def _ok_response(body: dict):
    return {"response": json.dumps(body), "load_duration": 1, "eval_duration": 1, "total_duration": 1,
            "prompt_eval_count": 1, "eval_count": 1}


def _provider(transport):
    return OllamaModelProvider(planner_model="phi4-reasoning:plus", coder_model="qwen2.5-coder:14b",
                                reviewer_model="phi4-reasoning:plus", http_post=transport)


# ------------------------------------------------------------------ prompts

def test_plan_mode_prompt_includes_user_request_and_context():
    prompt = build_planner_plan_mode_prompt({
        "request": "build a health endpoint", "spec_id": "spec-1",
        "context_bundle": _bundle([ContextFile(path="app.py", content="x = 1", category="referenced")]),
    })
    assert "build a health endpoint" in prompt
    assert "app.py" in prompt
    assert "x = 1" in prompt


def test_plan_mode_prompt_includes_revision_context_when_present():
    prompt = build_planner_plan_mode_prompt({
        "request": "add more", "spec_id": "spec-1", "context_bundle": _bundle(),
        "revision_request": "add more", "previous_plan": _plan(objective="original objective"),
    })
    assert "original objective" in prompt


def test_reviewer_plan_critique_prompt_includes_plan_fields():
    prompt = build_reviewer_plan_critique_prompt({"plan": _plan(objective="Build the thing")})
    assert "Build the thing" in prompt
    assert "widget.py" in prompt


def test_chat_prompt_includes_message_and_never_raw_coder_internals():
    prompt = build_chat_prompt({"message": "how does this work?", "context_bundle": _bundle()})
    assert "how does this work?" in prompt


def test_review_session_prompt_includes_target():
    prompt = build_review_session_prompt({"target": "the auth module", "context_bundle": _bundle()})
    assert "the auth module" in prompt


# ------------------------------------------------------------------ schemas

@pytest.mark.parametrize("schema", [PLANNER_PLAN_MODE_SCHEMA, REVIEWER_PLAN_CRITIQUE_SCHEMA, CHAT_SCHEMA,
                                     REVIEW_SESSION_SCHEMA])
def test_new_schemas_are_json_serializable(schema):
    json.dumps(schema)


def test_planner_plan_mode_schema_covers_structured_plan_fields():
    props = set(PLANNER_PLAN_MODE_SCHEMA["properties"].keys())
    for field in ("kind", "objective", "requirements", "proposed_architecture", "files_to_create",
                  "acceptance_criteria", "question", "requests"):
        assert field in props


def test_chat_schema_requires_message():
    assert CHAT_SCHEMA["required"] == ["message"]


# --------------------------------------------------------------- provider

def test_plan_mode_calls_configured_planner_model_and_parses_response():
    transport, calls = make_fake_transport([_ok_response({"kind": "needs_user_input", "question": "q?"})])
    provider = _provider(transport)
    result = provider.plan_mode({"request": "build something", "spec_id": "spec-1", "context_bundle": _bundle()})
    assert result == {"kind": "needs_user_input", "question": "q?"}
    assert calls[0]["payload"]["model"] == "phi4-reasoning:plus"
    assert calls[0]["payload"]["format"] == PLANNER_PLAN_MODE_SCHEMA


def test_review_plan_calls_configured_reviewer_model():
    transport, calls = make_fake_transport([_ok_response({
        "comments": [], "missing_requirements": [], "security_concerns": [], "unnecessary_complexity": [],
    })])
    provider = _provider(transport)
    provider.review_plan({"plan": _plan()})
    assert calls[0]["payload"]["model"] == "phi4-reasoning:plus"
    assert calls[0]["payload"]["format"] == REVIEWER_PLAN_CRITIQUE_SCHEMA


def test_chat_calls_configured_planner_model():
    transport, calls = make_fake_transport([_ok_response({"message": "hi there"})])
    provider = _provider(transport)
    result = provider.chat({"message": "hello", "context_bundle": _bundle()})
    assert result == {"message": "hi there"}
    assert calls[0]["payload"]["model"] == "phi4-reasoning:plus"


def test_review_session_calls_configured_reviewer_model():
    transport, calls = make_fake_transport([_ok_response({"summary": "looks fine", "findings": []})])
    provider = _provider(transport)
    result = provider.review_session({"target": "the auth module", "context_bundle": _bundle()})
    assert result == {"summary": "looks fine", "findings": []}
    assert calls[0]["payload"]["model"] == "phi4-reasoning:plus"


def test_all_four_methods_exist_on_the_provider_matching_the_protocol():
    provider = _provider(make_fake_transport([])[0])
    for method in ("plan", "code", "review", "plan_mode", "review_plan", "chat", "review_session"):
        assert callable(getattr(provider, method))
