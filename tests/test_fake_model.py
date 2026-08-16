import pytest

from agent_platform.orchestrator.fake_model import (
    TIMEOUT,
    FakeModelProvider,
    ModelExhaustedError,
    ModelTimeoutError,
)


def test_plan_returns_scripted_responses_in_order():
    provider = FakeModelProvider(planner_responses=[{"kind": "spec"}, {"kind": "needs_user_input"}])
    assert provider.plan({}) == {"kind": "spec"}
    assert provider.plan({}) == {"kind": "needs_user_input"}


def test_code_and_review_are_independent_queues():
    provider = FakeModelProvider(coder_responses=[{"status": "completed"}],
                                  reviewer_responses=[{"decision": "APPROVE"}])
    assert provider.code({}) == {"status": "completed"}
    assert provider.review({}) == {"decision": "APPROVE"}


def test_timeout_sentinel_raises_model_timeout_error():
    provider = FakeModelProvider(planner_responses=[TIMEOUT, {"kind": "spec"}])
    with pytest.raises(ModelTimeoutError):
        provider.plan({})
    assert provider.plan({}) == {"kind": "spec"}


def test_exhausted_queue_raises_model_exhausted_error():
    provider = FakeModelProvider(planner_responses=[{"kind": "spec"}])
    provider.plan({})
    with pytest.raises(ModelExhaustedError):
        provider.plan({})


def test_exhausted_error_is_distinct_from_timeout_error():
    assert not issubclass(ModelExhaustedError, ModelTimeoutError)
    assert not issubclass(ModelTimeoutError, ModelExhaustedError)
