import pytest

from agent_platform.events import Event, EventLog, EventType


def test_emit_returns_and_stores_event():
    log = EventLog()
    event = log.emit(EventType.USER_MESSAGE, "user", {"text": "hello"})
    assert event.event_type == EventType.USER_MESSAGE
    assert event.stream == "user"
    assert event.payload == {"text": "hello"}
    assert log.events() == (event,)


def test_invalid_stream_name_is_rejected():
    log = EventLog()
    with pytest.raises(ValueError):
        log.emit(EventType.INTERNAL, "not-a-real-stream", {})


def test_user_stream_filters_to_user_events_only():
    log = EventLog()
    log.emit(EventType.USER_MESSAGE, "user", {"text": "hi"})
    log.emit(EventType.TOOL_INVOKED, "internal", {"tool": "filesystem.read"})
    log.emit(EventType.USER_MESSAGE, "user", {"text": "bye"})
    user_events = log.user_stream()
    assert len(user_events) == 2
    assert all(e.stream == "user" for e in user_events)


def test_internal_stream_filters_to_internal_events_only():
    log = EventLog()
    log.emit(EventType.USER_MESSAGE, "user", {"text": "hi"})
    log.emit(EventType.TOOL_INVOKED, "internal", {"tool": "filesystem.read"})
    internal_events = log.internal_stream()
    assert len(internal_events) == 1
    assert internal_events[0].event_type == EventType.TOOL_INVOKED


def test_events_preserve_emission_order():
    log = EventLog()
    log.emit(EventType.STATE_TRANSITION, "internal", {"to": "PLAN"})
    log.emit(EventType.STATE_TRANSITION, "internal", {"to": "IMPLEMENT"})
    events = log.events()
    assert [e.payload["to"] for e in events] == ["PLAN", "IMPLEMENT"]


def test_payload_mutation_after_emit_does_not_affect_stored_event():
    log = EventLog()
    payload = {"text": "original"}
    event = log.emit(EventType.USER_MESSAGE, "user", payload)
    payload["text"] = "mutated"
    assert event.payload["text"] == "original"
