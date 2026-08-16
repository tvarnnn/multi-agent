import pytest

from agent_platform.orchestrator.fake_model import ModelTimeoutError
from agent_platform.orchestrator.ollama_provider import OllamaModelProvider, OllamaTransportError
from agent_platform.spec.versioning import SpecStore


def _spec():
    return SpecStore().create("task-1", goals=["g"], constraints=[], acceptance_criteria=["file:app.py"])


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


def _ok_response(body: dict, **timing):
    return {
        "response": __import__("json").dumps(body),
        "load_duration": timing.get("load_duration", 100),
        "eval_duration": timing.get("eval_duration", 200),
        "total_duration": timing.get("total_duration", 300),
        "prompt_eval_count": timing.get("prompt_eval_count", 10),
        "eval_count": timing.get("eval_count", 20),
    }


def test_plan_calls_the_configured_planner_model():
    transport, calls = make_fake_transport([_ok_response({"kind": "needs_user_input", "question": "q?"})])
    provider = OllamaModelProvider(planner_model="phi4-reasoning:plus", coder_model="qwen2.5-coder:14b",
                                    reviewer_model="phi4-reasoning:plus", http_post=transport)
    result = provider.plan({"request": "build something"})
    assert result == {"kind": "needs_user_input", "question": "q?"}
    assert calls[0]["payload"]["model"] == "phi4-reasoning:plus"


def test_code_calls_the_configured_coder_model():
    transport, calls = make_fake_transport([_ok_response({"status": "blocked", "spec_version_label": "task-1-v1",
                                                            "reason": "r", "attempted": "a",
                                                            "blocking_questions": ["q?"]})])
    provider = OllamaModelProvider(planner_model="phi4-reasoning:plus", coder_model="qwen2.5-coder:14b",
                                    reviewer_model="phi4-reasoning:plus", http_post=transport)
    provider.code({"spec": _spec(), "reviewer_feedback": None})
    assert calls[0]["payload"]["model"] == "qwen2.5-coder:14b"


def test_request_includes_the_json_schema_format_and_is_stateless():
    transport, calls = make_fake_transport([_ok_response({"kind": "spec", "goals": [], "constraints": [],
                                                            "acceptance_criteria": []})])
    provider = OllamaModelProvider(planner_model="phi4-reasoning:plus", coder_model="qwen2.5-coder:14b",
                                    reviewer_model="phi4-reasoning:plus", http_post=transport)
    provider.plan({"request": "x"})
    assert calls[0]["payload"]["format"]["type"] == "object"
    assert calls[0]["payload"]["stream"] is False
    assert "messages" not in calls[0]["payload"]  # single-shot generate, no chat history


def test_malformed_json_response_returns_sentinel_dict_not_raise():
    transport, _ = make_fake_transport([{"response": "not valid json{{{", "load_duration": 0,
                                          "eval_duration": 0, "total_duration": 0,
                                          "prompt_eval_count": 0, "eval_count": 0}])
    provider = OllamaModelProvider(planner_model="phi4-reasoning:plus", coder_model="qwen2.5-coder:14b",
                                    reviewer_model="phi4-reasoning:plus", http_post=transport)
    result = provider.plan({"request": "x"})
    assert "_malformed_raw_text" in result


def test_transport_error_retries_then_succeeds():
    transport, calls = make_fake_transport([
        OllamaTransportError("connection reset"),
        _ok_response({"kind": "spec", "goals": [], "constraints": [], "acceptance_criteria": []}),
    ])
    provider = OllamaModelProvider(planner_model="phi4-reasoning:plus", coder_model="qwen2.5-coder:14b",
                                    reviewer_model="phi4-reasoning:plus", http_post=transport,
                                    max_transport_retries=2)
    result = provider.plan({"request": "x"})
    assert result["kind"] == "spec"
    assert len(calls) == 2


def test_transport_error_exhausting_retries_raises_model_timeout_error():
    transport, _ = make_fake_transport([
        OllamaTransportError("e1"), OllamaTransportError("e2"),
    ])
    provider = OllamaModelProvider(planner_model="phi4-reasoning:plus", coder_model="qwen2.5-coder:14b",
                                    reviewer_model="phi4-reasoning:plus", http_post=transport,
                                    max_transport_retries=2)
    with pytest.raises(ModelTimeoutError):
        provider.plan({"request": "x"})


def test_telemetry_log_records_durations_and_counts():
    transport, _ = make_fake_transport([_ok_response(
        {"kind": "spec", "goals": [], "constraints": [], "acceptance_criteria": []},
        load_duration=555, eval_duration=777, total_duration=1332, prompt_eval_count=42, eval_count=99)])
    provider = OllamaModelProvider(planner_model="phi4-reasoning:plus", coder_model="qwen2.5-coder:14b",
                                    reviewer_model="phi4-reasoning:plus", http_post=transport)
    provider.plan({"request": "x"})
    assert len(provider.telemetry_log) == 1
    entry = provider.telemetry_log[0]
    assert entry.load_duration_ns == 555
    assert entry.eval_duration_ns == 777
    assert entry.total_duration_ns == 1332
    assert entry.prompt_eval_count == 42
    assert entry.eval_count == 99


def test_switching_to_a_different_model_sends_an_unload_call_first():
    transport, calls = make_fake_transport([
        _ok_response({"kind": "spec", "goals": [], "constraints": [], "acceptance_criteria": []}),
        {"response": "", "done": True},  # ack for the intervening unload call
        _ok_response({"status": "blocked", "spec_version_label": "task-1-v1", "reason": "r",
                      "attempted": "a", "blocking_questions": ["q?"]}),
    ])
    provider = OllamaModelProvider(planner_model="phi4-reasoning:plus", coder_model="qwen2.5-coder:14b",
                                    reviewer_model="phi4-reasoning:plus", http_post=transport)
    provider.plan({"request": "x"})
    provider.code({"spec": _spec(), "reviewer_feedback": None})
    # call 1: plan (loads phi4-reasoning:plus). call 2: unload phi4-reasoning:plus
    # (keep_alive: 0). call 3: code (loads qwen2.5-coder:14b).
    assert len(calls) == 3
    assert calls[1]["payload"] == {"model": "phi4-reasoning:plus", "keep_alive": 0}
    assert calls[2]["payload"]["model"] == "qwen2.5-coder:14b"


def test_reusing_the_same_shared_model_does_not_trigger_an_unload():
    # Planner and Reviewer share phi4-reasoning:plus per architecture-review-v2
    # section 7 - calling plan() then review() back to back must not unload
    # in between, since it's the same underlying model both times.
    transport, calls = make_fake_transport([
        _ok_response({"kind": "spec", "goals": [], "constraints": [], "acceptance_criteria": []}),
        _ok_response({"spec_version_label": "task-1-v1", "decision": "APPROVE",
                      "requirements_met": True, "security_ok": True, "validation_ok": True, "issues": []}),
    ])
    provider = OllamaModelProvider(planner_model="phi4-reasoning:plus", coder_model="qwen2.5-coder:14b",
                                    reviewer_model="phi4-reasoning:plus", http_post=transport)
    provider.plan({"request": "x"})
    from agent_platform.orchestrator.validation import ValidationResult
    from agent_platform.orchestrator.model_schemas import CoderCompleted
    provider.review({"spec": _spec(),
                      "coder_output": CoderCompleted(spec_version_label="task-1-v1", summary="s", file_writes=()),
                      "validation_result": ValidationResult(passed=True, details=())})
    assert len(calls) == 2  # no unload call in between


def test_a_failed_unload_does_not_block_the_next_call():
    transport, calls = make_fake_transport([
        _ok_response({"kind": "spec", "goals": [], "constraints": [], "acceptance_criteria": []}),
        OllamaTransportError("unload endpoint hiccup"),
        _ok_response({"status": "blocked", "spec_version_label": "task-1-v1", "reason": "r",
                      "attempted": "a", "blocking_questions": ["q?"]}),
    ])
    provider = OllamaModelProvider(planner_model="phi4-reasoning:plus", coder_model="qwen2.5-coder:14b",
                                    reviewer_model="phi4-reasoning:plus", http_post=transport)
    provider.plan({"request": "x"})
    result = provider.code({"spec": _spec(), "reviewer_feedback": None})
    assert result["status"] == "blocked"
