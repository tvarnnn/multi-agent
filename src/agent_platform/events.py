"""Structured, append-only event log. Every event belongs to exactly one
of two streams: "user" (the single conversational thread the Planner
holds with the user) or "internal" (the execution trace - model calls,
tool invocations, state transitions). Both streams share one underlying
log so everything stays correlatable by emission order, but they're
cleanly filterable - V3's requirement that the user-facing conversation
never gets buried in internal noise, without needing two separate logs.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

_VALID_STREAMS = {"user", "internal"}


class EventType(Enum):
    USER_REQUEST_RECEIVED = "USER_REQUEST_RECEIVED"
    STATE_TRANSITION = "STATE_TRANSITION"
    MODEL_OUTPUT_INVALID = "MODEL_OUTPUT_INVALID"
    TOOL_INVOKED = "TOOL_INVOKED"
    TOOL_DENIED = "TOOL_DENIED"
    USER_MESSAGE = "USER_MESSAGE"
    INTERNAL = "INTERNAL"
    SPEC_VERSION_CREATED = "SPEC_VERSION_CREATED"
    SPEC_VERSION_MISMATCH = "SPEC_VERSION_MISMATCH"


@dataclass(frozen=True)
class Event:
    event_type: EventType
    stream: str
    payload: dict
    timestamp: float = field(default_factory=time.time)


class EventLog:
    def __init__(self) -> None:
        self._events: list[Event] = []

    def emit(self, event_type: EventType, stream: str, payload: dict) -> Event:
        if stream not in _VALID_STREAMS:
            raise ValueError(f"invalid event stream: {stream!r} (must be one of {_VALID_STREAMS})")
        event = Event(event_type=event_type, stream=stream, payload=dict(payload))
        self._events.append(event)
        return event

    def events(self) -> tuple[Event, ...]:
        return tuple(self._events)

    def user_stream(self) -> tuple[Event, ...]:
        return tuple(e for e in self._events if e.stream == "user")

    def internal_stream(self) -> tuple[Event, ...]:
        return tuple(e for e in self._events if e.stream == "internal")
