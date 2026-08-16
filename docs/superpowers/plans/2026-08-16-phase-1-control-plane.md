> **STATUS: COMPLETE 2026-08-16.** All 11 tasks implemented, 541/541 tests
> passing (full Phase 0 + Phase 1 suite), 0 skipped, 0 regressions. See
> `../../../PHASE1_REPORT.md` at the project root for full results. Per
> the standing instruction, no further phase was started.

# Phase 1 Control Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic control plane on top of Phase 0's
sandbox/permission/spec-versioning foundation: a typed tool registry, a
6-step permission gateway, a full state-machine orchestrator, a structured
event system, and a scriptable fake model provider — so the entire
lifecycle (plan → implement → test → review → fix loop → completion, plus
clarification, requirement amendment, and stall/escalation) is testable
without a GPU, an LLM, Ollama, or MCP.

**Architecture:** Two new packages under `src/agent_platform/`: `tools/`
(schema validation, typed registry, permission gateway) and `orchestrator/`
(state machine, model output schemas, fake model provider, deterministic
validator, event system). Every model output is a raw `dict` (simulating
parsed JSON) that must pass a schema-validation function before it can
influence a state transition — malformed output is a first-class,
deterministically-handled case, never something that reaches the state
machine unchecked. Every tool call goes through the gateway's fixed
6-step pipeline built on Phase 0's real `FilesystemSandbox` and
`PermissionEvaluator` — nothing here reimplements or bypasses Phase 0's
security logic.

**Tech Stack:** Same as Phase 0 — Python 3.12.5 standard library only, no
new dependencies, `pytest` 8.4.2.

**Spec:** `architecture-review-v2.md`, `architecture-review-v3-agent-
interaction.md`, `architecture-review-v4-human-controlled-git.md`, and
Phase 0's own implementation (`src/agent_platform/security/`,
`src/agent_platform/config.py`, `src/agent_platform/spec/versioning.py`,
`PHASE0_REPORT.md`).

## Global Constraints

- Phase 0's `sandbox.py`, `enums.py`, `config.py`, `spec/versioning.py` are
  not redesigned or weakened. The one touch to Phase 0 code (Task 0, adding
  a field to `PermissionDecision`) is additive and backward-compatible,
  and Phase 0's full 451-test suite must still pass unchanged afterward —
  verified as part of Task 0, not assumed.
- No real LLM, no Ollama, no MCP, no network access anywhere in this
  phase. `FakeModelProvider` is the only model implementation.
- No `git.add`/`commit`/`push`/`reset`/`rebase`/`init` tool is implemented
  — these remain absolute denies inherited from Phase 0's
  `ABSOLUTE_DENY_TOOLS`. Only `git.status`/`diff`/`log`/`branch` (current)
  are real, read-only, toplevel-scope-verified tools.
- No `shell.run`, no package installation, no unrestricted subprocess -
  the only subprocess calls in this phase are the fixed `git` read-only
  invocations inside the git tool handlers themselves.
- Deterministic validation in this phase is scoped to what's actually
  checkable without executing generated code: acceptance criteria of the
  form `file:<relative-path>` are checked for existence; other criteria
  are recorded as advisory. Running real tests/lint/typecheck on generated
  code is out of scope — Phase 1's own TOOLS list has no `test.run`/
  `lint.run`/`typecheck.run` entries, so none are built.
- `AMEND_REQUIREMENTS` is implemented as an explicit orchestrator entry
  point (`amend_requirements(...)`), not as a live mid-session interrupt —
  Phase 1 builds the deterministic control plane, not an interactive
  session loop. This is a scope decision, not a gap: it is fully testable
  and matches the state machine's transitions.
- This session runs no git commands (per the standing instruction from
  Phase 0) — no commits, no `git init`. Working tree changes are left for
  the user to review.

---

### Task 0: Non-breaking extension to Phase 0's `PermissionDecision`

**Files:**
- Modify: `src/agent_platform/security/permission.py`

**Interfaces:**
- Consumes: existing `PermissionDecision` from Phase 0
- Produces: `PermissionDecision.resolved_path: Optional[Path] = None` —
  populated whenever the evaluator authorized a path, so the gateway (Task
  5) doesn't need to re-run sandbox authorization or reach into the
  evaluator's private state to get the already-computed resolved path.

**Why this is additive, not a redesign:** the field defaults to `None` and
is purely informational — no existing behavior, return value, or test
assertion in Phase 0 depends on `PermissionDecision` *not* having this
field. Phase 0's 451 tests check `.permission` and `.reason`; none of them
assert on the dataclass's exact field set.

- [ ] **Step 1: Add the field and populate it**

In `src/agent_platform/security/permission.py`, change:

```python
@dataclass(frozen=True)
class PermissionDecision:
    permission: ToolPermission
    reason: str

    @property
    def is_denied(self) -> bool:
        return self.permission == ToolPermission.DENY
```

to:

```python
@dataclass(frozen=True)
class PermissionDecision:
    permission: ToolPermission
    reason: str
    resolved_path: Optional[Path] = None

    @property
    def is_denied(self) -> bool:
        return self.permission == ToolPermission.DENY
```

And in `PermissionEvaluator.evaluate`, change the path-checking block from:

```python
        if call.path_argument is not None:
            path_decision = self._sandbox.authorize(call.path_argument, scope_root=call.scope_root)
            if not path_decision.allowed:
                return PermissionDecision(ToolPermission.DENY, f"sandbox denial: {path_decision.reason}")
```

to:

```python
        resolved_path: Optional[Path] = None
        if call.path_argument is not None:
            path_decision = self._sandbox.authorize(call.path_argument, scope_root=call.scope_root)
            if not path_decision.allowed:
                return PermissionDecision(ToolPermission.DENY, f"sandbox denial: {path_decision.reason}")
            resolved_path = path_decision.resolved_path
```

and change the final return from:

```python
        ceiling = _SESSION_CEILING[session_mode]
        effective_tier = min(_TIER[static_permission], _TIER[ceiling])
        effective = _TIER_TO_PERMISSION[effective_tier]
        return PermissionDecision(
            effective, f"{static_permission.value} capped by {session_mode.value} ceiling"
        )
```

to:

```python
        ceiling = _SESSION_CEILING[session_mode]
        effective_tier = min(_TIER[static_permission], _TIER[ceiling])
        effective = _TIER_TO_PERMISSION[effective_tier]
        return PermissionDecision(
            effective, f"{static_permission.value} capped by {session_mode.value} ceiling",
            resolved_path=resolved_path,
        )
```

- [ ] **Step 2: Re-run the full Phase 0 suite to prove nothing broke**

Run: `python -m pytest tests/ -v`
Expected: 451 passed, 0 failed, 0 skipped (same as the Phase 0 report) —
if anything differs, stop and treat it as a real regression, not a Phase 1
concern to work around.

- [ ] **Step 3: Add a small test proving the new field is populated on ALLOW and absent on DENY**

Add to `tests/test_permission.py`:

```python
def test_resolved_path_populated_on_allow(evaluator, workspace):
    call = ToolCall(role=Role.CODER, tool_name="filesystem.write",
                     path_argument="MyProj/app.py", scope_root=(workspace / "MyProj").resolve())
    decision = evaluator.evaluate(call, SessionMode.AUTO)
    assert decision.resolved_path == (workspace / "MyProj" / "app.py").resolve()


def test_resolved_path_none_on_deny(evaluator, workspace):
    call = ToolCall(role=Role.PLANNER, tool_name="filesystem.write",
                     path_argument="MyProj/app.py", scope_root=(workspace / "MyProj").resolve())
    decision = evaluator.evaluate(call, SessionMode.AUTO)
    assert decision.resolved_path is None
```

Run: `python -m pytest tests/test_permission.py -v`
Expected: 79 passed (77 existing + 2 new)

---

### Task 1: Structured event system

**Files:**
- Create: `src/agent_platform/events.py`
- Create: `tests/test_events.py`

**Interfaces:**
- Produces: `class EventType(Enum)` with members `USER_REQUEST_RECEIVED,
  STATE_TRANSITION, MODEL_OUTPUT_INVALID, TOOL_INVOKED, TOOL_DENIED,
  USER_MESSAGE, INTERNAL, SPEC_VERSION_CREATED, SPEC_VERSION_MISMATCH`;
  `@dataclass(frozen=True) class Event` with fields `event_type: EventType`,
  `stream: str`, `payload: dict`, `timestamp: float`; `class EventLog` with
  methods `emit(event_type, stream, payload) -> Event`, `events() ->
  tuple[Event, ...]`, `user_stream() -> tuple[Event, ...]`,
  `internal_stream() -> tuple[Event, ...]`. `stream` is always exactly
  `"user"` or `"internal"` — this is V3's user-conversation-vs-internal-
  trace separation (V3 §10), made concrete as a filterable field on one
  underlying log rather than two separate logs, so everything stays
  correlatable while still being cleanly separable.

- [ ] **Step 1: Write the failing tests**

`tests/test_events.py`:
```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_events.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_platform.events'`

- [ ] **Step 3: Implement**

`src/agent_platform/events.py`:
```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_events.py -v`
Expected: PASS (6 tests)

---

### Task 2: Model output schemas

**Files:**
- Create: `src/agent_platform/orchestrator/__init__.py`
- Create: `src/agent_platform/orchestrator/model_schemas.py`
- Create: `tests/test_model_schemas.py`

**Interfaces:**
- Produces: `class SchemaValidationError(Exception)`;
  `PlannerSpec(goals, constraints, acceptance_criteria)`,
  `PlannerClarification(question)`, `parse_planner_output(raw: dict) ->
  PlannerSpec | PlannerClarification`;
  `CoderFileWrite(path, content)`, `CoderCompleted(spec_version_label,
  summary, file_writes)`, `CoderBlocked(spec_version_label, reason,
  attempted, blocking_questions)`, `parse_coder_output(raw: dict) ->
  CoderCompleted | CoderBlocked`;
  `ReviewerIssue(severity, file, description, required_fix)`,
  `ReviewerOutput(spec_version_label, decision, requirements_met,
  security_ok, validation_ok, issues)`, `parse_reviewer_output(raw: dict)
  -> ReviewerOutput`. These exact names and shapes are what Task 7-9's
  orchestrator imports and matches on with `isinstance`.

- [ ] **Step 1: Write the failing tests**

`tests/test_model_schemas.py`:
```python
import pytest

from agent_platform.orchestrator.model_schemas import (
    CoderBlocked,
    CoderCompleted,
    PlannerClarification,
    PlannerSpec,
    ReviewerOutput,
    SchemaValidationError,
    parse_coder_output,
    parse_planner_output,
    parse_reviewer_output,
)


def test_parse_planner_spec():
    raw = {"kind": "spec", "goals": ["build a thing"], "constraints": ["no network"],
           "acceptance_criteria": ["file:app.py"]}
    result = parse_planner_output(raw)
    assert isinstance(result, PlannerSpec)
    assert result.goals == ("build a thing",)
    assert result.constraints == ("no network",)
    assert result.acceptance_criteria == ("file:app.py",)


def test_parse_planner_clarification():
    raw = {"kind": "needs_user_input", "question": "OAuth or API keys?"}
    result = parse_planner_output(raw)
    assert isinstance(result, PlannerClarification)
    assert result.question == "OAuth or API keys?"


@pytest.mark.parametrize("raw", [
    {},
    {"kind": "spec"},
    {"kind": "spec", "goals": "not-a-list", "constraints": [], "acceptance_criteria": []},
    {"kind": "spec", "goals": [1, 2], "constraints": [], "acceptance_criteria": []},
    {"kind": "needs_user_input"},
    {"kind": "needs_user_input", "question": ""},
    {"kind": "unknown_kind"},
    "not a dict",
    None,
])
def test_malformed_planner_output_is_rejected(raw):
    with pytest.raises(SchemaValidationError):
        parse_planner_output(raw)


def test_parse_coder_completed():
    raw = {
        "status": "completed", "spec_version_label": "task-1-v1",
        "summary": "wrote the app", "file_writes": [
            {"path": "app.py", "content": "print('hi')"},
        ],
    }
    result = parse_coder_output(raw)
    assert isinstance(result, CoderCompleted)
    assert result.spec_version_label == "task-1-v1"
    assert result.file_writes[0].path == "app.py"
    assert result.file_writes[0].content == "print('hi')"


def test_parse_coder_completed_allows_empty_file_content():
    raw = {"status": "completed", "spec_version_label": "task-1-v1", "summary": "s",
           "file_writes": [{"path": "empty.py", "content": ""}]}
    result = parse_coder_output(raw)
    assert result.file_writes[0].content == ""


def test_parse_coder_blocked():
    raw = {"status": "blocked", "spec_version_label": "task-1-v1", "reason": "ambiguous auth",
           "attempted": "looked at existing code", "blocking_questions": ["OAuth or API keys?"]}
    result = parse_coder_output(raw)
    assert isinstance(result, CoderBlocked)
    assert result.blocking_questions == ("OAuth or API keys?",)


@pytest.mark.parametrize("raw", [
    {},
    {"status": "completed"},
    {"status": "completed", "spec_version_label": "v1", "summary": "s", "file_writes": "not-a-list"},
    {"status": "completed", "spec_version_label": "v1", "summary": "s",
     "file_writes": [{"path": "x.py"}]},
    {"status": "blocked", "spec_version_label": "v1"},
    {"status": "unknown"},
    "not a dict",
])
def test_malformed_coder_output_is_rejected(raw):
    with pytest.raises(SchemaValidationError):
        parse_coder_output(raw)


def test_parse_reviewer_approve():
    raw = {"spec_version_label": "task-1-v1", "decision": "APPROVE", "requirements_met": True,
           "security_ok": True, "validation_ok": True, "issues": []}
    result = parse_reviewer_output(raw)
    assert isinstance(result, ReviewerOutput)
    assert result.decision == "APPROVE"
    assert result.issues == ()


def test_parse_reviewer_reject_with_issues():
    raw = {"spec_version_label": "task-1-v1", "decision": "REJECT", "requirements_met": False,
           "security_ok": True, "validation_ok": True,
           "issues": [{"severity": "high", "file": "app.py", "description": "missing auth",
                       "required_fix": "add auth check"}]}
    result = parse_reviewer_output(raw)
    assert result.decision == "REJECT"
    assert len(result.issues) == 1
    assert result.issues[0].severity == "high"


@pytest.mark.parametrize("raw", [
    {},
    {"spec_version_label": "v1", "decision": "MAYBE", "requirements_met": True,
     "security_ok": True, "validation_ok": True, "issues": []},
    {"spec_version_label": "v1", "decision": "APPROVE", "requirements_met": "yes",
     "security_ok": True, "validation_ok": True, "issues": []},
    {"spec_version_label": "v1", "decision": "REJECT", "requirements_met": False,
     "security_ok": True, "validation_ok": True,
     "issues": [{"severity": "high", "file": "app.py"}]},
    "not a dict",
])
def test_malformed_reviewer_output_is_rejected(raw):
    with pytest.raises(SchemaValidationError):
        parse_reviewer_output(raw)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_model_schemas.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_platform.orchestrator'`

- [ ] **Step 3: Implement**

`src/agent_platform/orchestrator/__init__.py`:
```python
```

`src/agent_platform/orchestrator/model_schemas.py`:
```python
"""Structured output contracts for Planner, Coder, and Reviewer.

Every model output is a raw dict (standing in for parsed JSON from a real
model) and must pass one of these parse functions before it can influence
a state transition. Unconstrained model prose never controls the state
machine - a dict that doesn't match its schema raises
SchemaValidationError, which the orchestrator treats as a bounded-retry-
then-escalate case (see orchestrator/core.py), never as free-form input
to interpret.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Union


class SchemaValidationError(Exception):
    pass


def _require_str(d: dict, key: str) -> str:
    value = d.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"missing or invalid required string field: {key}")
    return value


def _require_str_allow_empty(d: dict, key: str) -> str:
    value = d.get(key)
    if not isinstance(value, str):
        raise SchemaValidationError(f"missing or invalid required string field: {key}")
    return value


def _require_bool(d: dict, key: str) -> bool:
    value = d.get(key)
    if not isinstance(value, bool):
        raise SchemaValidationError(f"missing or invalid required boolean field: {key}")
    return value


def _require_str_tuple(d: dict, key: str, *, allow_empty_list: bool = True) -> tuple:
    value = d.get(key)
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise SchemaValidationError(f"missing or invalid required string-list field: {key}")
    if not allow_empty_list and not value:
        raise SchemaValidationError(f"required string-list field must not be empty: {key}")
    return tuple(value)


def _require_dict(raw) -> dict:
    if not isinstance(raw, dict):
        raise SchemaValidationError("model output must be an object")
    return raw


# ---------------------------------------------------------------- Planner

@dataclass(frozen=True)
class PlannerSpec:
    goals: tuple[str, ...]
    constraints: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]


@dataclass(frozen=True)
class PlannerClarification:
    question: str


PlannerOutput = Union[PlannerSpec, PlannerClarification]


def parse_planner_output(raw) -> PlannerOutput:
    d = _require_dict(raw)
    kind = d.get("kind")
    if kind == "spec":
        return PlannerSpec(
            goals=_require_str_tuple(d, "goals"),
            constraints=_require_str_tuple(d, "constraints"),
            acceptance_criteria=_require_str_tuple(d, "acceptance_criteria"),
        )
    if kind == "needs_user_input":
        return PlannerClarification(question=_require_str(d, "question"))
    raise SchemaValidationError(f"unknown planner output kind: {kind!r}")


# ------------------------------------------------------------------ Coder

@dataclass(frozen=True)
class CoderFileWrite:
    path: str
    content: str


@dataclass(frozen=True)
class CoderCompleted:
    spec_version_label: str
    summary: str
    file_writes: tuple[CoderFileWrite, ...]


@dataclass(frozen=True)
class CoderBlocked:
    spec_version_label: str
    reason: str
    attempted: str
    blocking_questions: tuple[str, ...]


CoderOutput = Union[CoderCompleted, CoderBlocked]


def _parse_file_write(raw) -> CoderFileWrite:
    d = _require_dict(raw)
    return CoderFileWrite(path=_require_str(d, "path"), content=_require_str_allow_empty(d, "content"))


def parse_coder_output(raw) -> CoderOutput:
    d = _require_dict(raw)
    status = d.get("status")
    if status == "completed":
        writes_raw = d.get("file_writes")
        if not isinstance(writes_raw, list):
            raise SchemaValidationError("file_writes must be a list")
        return CoderCompleted(
            spec_version_label=_require_str(d, "spec_version_label"),
            summary=_require_str(d, "summary"),
            file_writes=tuple(_parse_file_write(w) for w in writes_raw),
        )
    if status == "blocked":
        return CoderBlocked(
            spec_version_label=_require_str(d, "spec_version_label"),
            reason=_require_str(d, "reason"),
            attempted=_require_str(d, "attempted"),
            blocking_questions=_require_str_tuple(d, "blocking_questions", allow_empty_list=False),
        )
    raise SchemaValidationError(f"unknown coder output status: {status!r}")


# --------------------------------------------------------------- Reviewer

@dataclass(frozen=True)
class ReviewerIssue:
    severity: str
    file: str
    description: str
    required_fix: str


@dataclass(frozen=True)
class ReviewerOutput:
    spec_version_label: str
    decision: str
    requirements_met: bool
    security_ok: bool
    validation_ok: bool
    issues: tuple[ReviewerIssue, ...]


def _parse_issue(raw) -> ReviewerIssue:
    d = _require_dict(raw)
    return ReviewerIssue(
        severity=_require_str(d, "severity"),
        file=_require_str(d, "file"),
        description=_require_str(d, "description"),
        required_fix=_require_str(d, "required_fix"),
    )


def parse_reviewer_output(raw) -> ReviewerOutput:
    d = _require_dict(raw)
    decision = d.get("decision")
    if decision not in ("APPROVE", "REJECT"):
        raise SchemaValidationError(f"invalid reviewer decision: {decision!r}")
    issues_raw = d.get("issues", [])
    if not isinstance(issues_raw, list):
        raise SchemaValidationError("issues must be a list")
    return ReviewerOutput(
        spec_version_label=_require_str(d, "spec_version_label"),
        decision=decision,
        requirements_met=_require_bool(d, "requirements_met"),
        security_ok=_require_bool(d, "security_ok"),
        validation_ok=_require_bool(d, "validation_ok"),
        issues=tuple(_parse_issue(i) for i in issues_raw),
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_model_schemas.py -v`
Expected: PASS (21 tests)

---

### Task 3: Fake model provider

**Files:**
- Create: `src/agent_platform/orchestrator/fake_model.py`
- Create: `tests/test_fake_model.py`

**Interfaces:**
- Consumes: nothing (raw dicts in, raw dicts out — schema parsing is the
  orchestrator's job, not the provider's)
- Produces: `TIMEOUT` sentinel; `class ModelTimeoutError(Exception)`;
  `class ModelExhaustedError(Exception)`; `class FakeModelProvider` with
  constructor `FakeModelProvider(*, planner_responses=(),
  coder_responses=(), reviewer_responses=())` and methods `plan(context) ->
  dict`, `code(context) -> dict`, `review(context) -> dict`, each popping
  the next scripted response (or raising `ModelTimeoutError` if the next
  scripted item is `TIMEOUT`, or `ModelExhaustedError` if the queue is
  empty — the latter signals an incomplete test script, not a real
  orchestrator scenario, and is never caught by the orchestrator).

- [ ] **Step 1: Write the failing tests**

`tests/test_fake_model.py`:
```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_fake_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_platform.orchestrator.fake_model'`

- [ ] **Step 3: Implement**

`src/agent_platform/orchestrator/fake_model.py`:
```python
"""A scriptable model provider for testing the orchestrator without a
GPU, an LLM, Ollama, or MCP. Each role's responses are a pre-configured
queue of raw dicts (standing in for parsed model JSON, including
deliberately malformed ones) popped in order. ModelExhaustedError means
the test script ran out of responses - a test bug, never a real
orchestrator scenario - and the orchestrator never catches it.
"""
from __future__ import annotations


class ModelTimeoutError(Exception):
    pass


class ModelExhaustedError(Exception):
    pass


class _TimeoutSentinel:
    def __repr__(self) -> str:
        return "TIMEOUT"


TIMEOUT = _TimeoutSentinel()


class FakeModelProvider:
    def __init__(self, *, planner_responses=(), coder_responses=(), reviewer_responses=()):
        self._planner = list(planner_responses)
        self._coder = list(coder_responses)
        self._reviewer = list(reviewer_responses)

    def plan(self, context) -> dict:
        return self._pop(self._planner, "planner")

    def code(self, context) -> dict:
        return self._pop(self._coder, "coder")

    def review(self, context) -> dict:
        return self._pop(self._reviewer, "reviewer")

    def _pop(self, queue: list, role_name: str) -> dict:
        if not queue:
            raise ModelExhaustedError(f"no more scripted {role_name} responses")
        item = queue.pop(0)
        if item is TIMEOUT:
            raise ModelTimeoutError(f"{role_name} call timed out")
        return item
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_fake_model.py -v`
Expected: PASS (5 tests)

---

### Task 4: Tool argument schemas and typed registry

**Files:**
- Create: `src/agent_platform/tools/__init__.py`
- Create: `src/agent_platform/tools/schemas.py`
- Create: `src/agent_platform/tools/registry.py`
- Create: `tests/test_tools_registry.py`

**Interfaces:**
- Consumes: nothing from Phase 0 directly (git handlers call the real
  `git` executable via `subprocess`, path handlers just read/write
  already-resolved `Path` objects handed to them by the gateway in Task 5
  — they never resolve paths themselves)
- Produces: `class ToolArgumentError(Exception)`, `class
  ToolPreconditionError(Exception)`, `@dataclass(frozen=True) class
  ToolExecutionContext(resolved_path: Optional[Path], project_root:
  Path)`, `@dataclass(frozen=True) class ToolSpec(name, validate_arguments,
  path_argument_key, check_preconditions, execute)`, `class ToolRegistry`
  with `register(spec)`, `get(name) -> Optional[ToolSpec]`, `names() ->
  tuple[str, ...]`, and `build_default_registry() -> ToolRegistry`
  pre-registering `filesystem.read/write/create_directory/list` and
  `git.status/diff/log/branch`. Task 5's `ToolGateway` consumes
  `ToolRegistry`, `ToolSpec`, `ToolExecutionContext`,
  `ToolArgumentError`, `ToolPreconditionError` exactly as named here.

- [ ] **Step 1: Write the failing tests**

`tests/test_tools_registry.py`:
```python
from pathlib import Path

import pytest

from agent_platform.tools.registry import ToolExecutionContext, build_default_registry
from agent_platform.tools.schemas import ToolArgumentError, ToolPreconditionError


@pytest.fixture
def registry():
    return build_default_registry()


def test_all_expected_tools_are_registered(registry):
    assert registry.names() == (
        "filesystem.create_directory", "filesystem.list", "filesystem.read",
        "filesystem.write", "git.branch", "git.diff", "git.log", "git.status",
    )


def test_unregistered_tool_returns_none(registry):
    assert registry.get("git.commit") is None
    assert registry.get("shell.run") is None


def test_filesystem_read_validate_arguments_requires_path(registry):
    spec = registry.get("filesystem.read")
    with pytest.raises(ToolArgumentError):
        spec.validate_arguments({})
    with pytest.raises(ToolArgumentError):
        spec.validate_arguments({"path": ""})
    assert spec.validate_arguments({"path": "app.py"}) == {"path": "app.py"}


def test_filesystem_write_validate_arguments_requires_path_and_content(registry):
    spec = registry.get("filesystem.write")
    with pytest.raises(ToolArgumentError):
        spec.validate_arguments({"path": "app.py"})
    assert spec.validate_arguments({"path": "app.py", "content": "x"}) == {
        "path": "app.py", "content": "x"
    }


def test_git_tools_validate_arguments_ignores_extra_and_requires_nothing(registry):
    spec = registry.get("git.status")
    assert spec.validate_arguments({}) == {}
    assert spec.validate_arguments({"anything": "ignored"}) == {}


def test_filesystem_read_precondition_requires_existing_file(tmp_path, registry):
    spec = registry.get("filesystem.read")
    missing = tmp_path / "missing.py"
    ctx = ToolExecutionContext(resolved_path=missing, project_root=tmp_path)
    with pytest.raises(ToolPreconditionError):
        spec.check_preconditions({"path": "missing.py"}, ctx)


def test_filesystem_read_executes_and_returns_content(tmp_path, registry):
    target = tmp_path / "app.py"
    target.write_text("print('hi')", encoding="utf-8")
    spec = registry.get("filesystem.read")
    ctx = ToolExecutionContext(resolved_path=target, project_root=tmp_path)
    result = spec.execute({"path": "app.py"}, ctx)
    assert result == {"content": "print('hi')"}


def test_filesystem_write_creates_parent_dirs_and_writes(tmp_path, registry):
    target = tmp_path / "sub" / "app.py"
    spec = registry.get("filesystem.write")
    ctx = ToolExecutionContext(resolved_path=target, project_root=tmp_path)
    result = spec.execute({"path": "sub/app.py", "content": "x = 1"}, ctx)
    assert target.read_text(encoding="utf-8") == "x = 1"
    assert result == {"written": str(target)}


def test_filesystem_create_directory_executes(tmp_path, registry):
    target = tmp_path / "newdir"
    spec = registry.get("filesystem.create_directory")
    ctx = ToolExecutionContext(resolved_path=target, project_root=tmp_path)
    spec.execute({"path": "newdir"}, ctx)
    assert target.is_dir()


def test_filesystem_list_precondition_requires_existing_directory(tmp_path, registry):
    spec = registry.get("filesystem.list")
    missing = tmp_path / "missing_dir"
    ctx = ToolExecutionContext(resolved_path=missing, project_root=tmp_path)
    with pytest.raises(ToolPreconditionError):
        spec.check_preconditions({"path": "missing_dir"}, ctx)


def test_filesystem_list_executes_and_returns_sorted_entries(tmp_path, registry):
    (tmp_path / "b.py").write_text("", encoding="utf-8")
    (tmp_path / "a.py").write_text("", encoding="utf-8")
    spec = registry.get("filesystem.list")
    ctx = ToolExecutionContext(resolved_path=tmp_path, project_root=tmp_path)
    result = spec.execute({"path": "."}, ctx)
    assert result == {"entries": ["a.py", "b.py"]}


def test_git_status_reports_unscoped_outside_a_repo(tmp_path, registry):
    spec = registry.get("git.status")
    ctx = ToolExecutionContext(resolved_path=None, project_root=tmp_path)
    result = spec.execute({}, ctx)
    assert result["scoped"] is False
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_tools_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_platform.tools'`

- [ ] **Step 3: Implement**

`src/agent_platform/tools/__init__.py`:
```python
```

`src/agent_platform/tools/schemas.py`:
```python
"""Typed-tool building blocks: the exceptions and dataclasses ToolSpec
implementations (registry.py) and the gateway (gateway.py) share. Kept
separate from registry.py so the vocabulary (what an argument error vs a
precondition error means) is easy to find without wading through every
tool's concrete implementation.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional


class ToolArgumentError(Exception):
    """Raised when a tool call's arguments don't match its schema - wrong
    type, missing required field. Caught by the gateway before permission
    is ever evaluated (there's nothing safe to check permission against
    yet)."""


class ToolPreconditionError(Exception):
    """Raised when arguments are well-typed and the path is sandbox-
    authorized, but a business-logic precondition still fails - e.g.
    reading a file that doesn't exist. Distinct from ToolArgumentError:
    this is caught *after* permission evaluation, never before."""


@dataclass(frozen=True)
class ToolExecutionContext:
    resolved_path: Optional[Path]
    project_root: Path


@dataclass(frozen=True)
class ToolSpec:
    name: str
    validate_arguments: Callable[[dict], dict]
    path_argument_key: Optional[str]
    check_preconditions: Callable[[dict, ToolExecutionContext], None]
    execute: Callable[[dict, ToolExecutionContext], Any]
```

`src/agent_platform/tools/registry.py`:
```python
"""Typed tool registry: filesystem.read/write/create_directory/list and
read-only git.status/diff/log/branch. No shell.run, no git write
operations - those simply have no ToolSpec here, so a lookup for them
returns None and the gateway reports "unknown_tool" before permission is
even evaluated. (Permission evaluation would deny them too, per Phase 0's
ABSOLUTE_DENY_TOOLS - not having a handler is defense in depth, not the
only defense.)
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from .schemas import ToolArgumentError, ToolExecutionContext, ToolPreconditionError, ToolSpec


def _no_precondition(args: dict, ctx: ToolExecutionContext) -> None:
    return None


def _validate_path_only(args: dict) -> dict:
    if not isinstance(args, dict):
        raise ToolArgumentError("arguments must be an object")
    path = args.get("path")
    if not isinstance(path, str) or not path.strip():
        raise ToolArgumentError("missing or invalid required field: path")
    return {"path": path}


def _validate_write_args(args: dict) -> dict:
    validated = _validate_path_only(args)
    content = args.get("content")
    if not isinstance(content, str):
        raise ToolArgumentError("missing or invalid required field: content")
    validated["content"] = content
    return validated


def _validate_no_args(args: dict) -> dict:
    if not isinstance(args, dict):
        raise ToolArgumentError("arguments must be an object")
    return {}


def _require_existing_file(args: dict, ctx: ToolExecutionContext) -> None:
    if ctx.resolved_path is None or not ctx.resolved_path.is_file():
        raise ToolPreconditionError(f"file does not exist: {args.get('path')}")


def _require_existing_directory(args: dict, ctx: ToolExecutionContext) -> None:
    if ctx.resolved_path is None or not ctx.resolved_path.is_dir():
        raise ToolPreconditionError(f"directory does not exist: {args.get('path')}")


def _execute_filesystem_read(args: dict, ctx: ToolExecutionContext) -> dict:
    return {"content": ctx.resolved_path.read_text(encoding="utf-8")}


def _execute_filesystem_write(args: dict, ctx: ToolExecutionContext) -> dict:
    ctx.resolved_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.resolved_path.write_text(args["content"], encoding="utf-8")
    return {"written": str(ctx.resolved_path)}


def _execute_filesystem_create_directory(args: dict, ctx: ToolExecutionContext) -> dict:
    ctx.resolved_path.mkdir(parents=True, exist_ok=True)
    return {"created": str(ctx.resolved_path)}


def _execute_filesystem_list(args: dict, ctx: ToolExecutionContext) -> dict:
    return {"entries": sorted(p.name for p in ctx.resolved_path.iterdir())}


def _git_toplevel(cwd: Path) -> Optional[Path]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(cwd), capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def _git_scoped_root(ctx: ToolExecutionContext) -> Optional[Path]:
    """Returns the project root only if git's own toplevel for that
    directory matches it exactly - never an enclosing repo. See the
    stray-outer-repo hazard documented in architecture-review-v4."""
    toplevel = _git_toplevel(ctx.project_root)
    if toplevel is None or toplevel != ctx.project_root.resolve():
        return None
    return toplevel


def _run_git_readonly(args: list[str], cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=10)
    return result.stdout


def _execute_git_status(args: dict, ctx: ToolExecutionContext) -> dict:
    scoped = _git_scoped_root(ctx)
    if scoped is None:
        return {"scoped": False, "message": "no git repository scoped to this project"}
    return {"scoped": True, "output": _run_git_readonly(["status", "--porcelain"], scoped)}


def _execute_git_diff(args: dict, ctx: ToolExecutionContext) -> dict:
    scoped = _git_scoped_root(ctx)
    if scoped is None:
        return {"scoped": False, "message": "no git repository scoped to this project"}
    return {"scoped": True, "output": _run_git_readonly(["diff"], scoped)}


def _execute_git_log(args: dict, ctx: ToolExecutionContext) -> dict:
    scoped = _git_scoped_root(ctx)
    if scoped is None:
        return {"scoped": False, "message": "no git repository scoped to this project"}
    return {"scoped": True, "output": _run_git_readonly(["log", "--oneline"], scoped)}


def _execute_git_branch(args: dict, ctx: ToolExecutionContext) -> dict:
    scoped = _git_scoped_root(ctx)
    if scoped is None:
        return {"scoped": False, "message": "no git repository scoped to this project"}
    return {"scoped": True, "output": _run_git_readonly(["branch", "--show-current"], scoped).strip()}


class ToolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._specs[spec.name] = spec

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._specs.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs.keys()))


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ToolSpec(
        name="filesystem.read", validate_arguments=_validate_path_only,
        path_argument_key="path", check_preconditions=_require_existing_file,
        execute=_execute_filesystem_read,
    ))
    registry.register(ToolSpec(
        name="filesystem.write", validate_arguments=_validate_write_args,
        path_argument_key="path", check_preconditions=_no_precondition,
        execute=_execute_filesystem_write,
    ))
    registry.register(ToolSpec(
        name="filesystem.create_directory", validate_arguments=_validate_path_only,
        path_argument_key="path", check_preconditions=_no_precondition,
        execute=_execute_filesystem_create_directory,
    ))
    registry.register(ToolSpec(
        name="filesystem.list", validate_arguments=_validate_path_only,
        path_argument_key="path", check_preconditions=_require_existing_directory,
        execute=_execute_filesystem_list,
    ))
    for name, handler in (
        ("git.status", _execute_git_status), ("git.diff", _execute_git_diff),
        ("git.log", _execute_git_log), ("git.branch", _execute_git_branch),
    ):
        registry.register(ToolSpec(
            name=name, validate_arguments=_validate_no_args,
            path_argument_key=None, check_preconditions=_no_precondition,
            execute=handler,
        ))
    return registry
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_tools_registry.py -v`
Expected: PASS (12 tests)

---

### Task 5: Permission gateway

**Files:**
- Create: `src/agent_platform/tools/gateway.py`
- Create: `tests/test_gateway.py`

**Interfaces:**
- Consumes: `ToolRegistry`, `ToolExecutionContext`, `ToolArgumentError`,
  `ToolPreconditionError` (Task 4); `PermissionEvaluator`, `ToolCall`,
  `PermissionDecision` (Phase 0, extended in Task 0); `Role`, `SessionMode`,
  `ToolPermission` (Phase 0); `EventLog`, `EventType` (Task 1)
- Produces: `@dataclass(frozen=True) class ToolObservation(status,
  tool_name, result, error)` with `status` one of `"ok"`, `"denied"`,
  `"requires_confirmation"`, `"invalid_schema"`, `"unknown_tool"`,
  `"error"`; `class ToolGateway` with constructor `ToolGateway(registry,
  evaluator, event_log)` and method `invoke(*, role: Role, tool_name: str,
  arguments: dict, session_mode: SessionMode, project_root: Path) ->
  ToolObservation`. Task 7's orchestrator calls `gateway.invoke(...)`
  exactly like this for every file write it performs on the Coder's
  behalf.

- [ ] **Step 1: Write the failing tests**

`tests/test_gateway.py`:
```python
import pytest

from agent_platform.events import EventLog
from agent_platform.security.enums import Role, SessionMode
from agent_platform.security.permission import PermissionEvaluator
from agent_platform.security.sandbox import FilesystemSandbox
from agent_platform.tools.gateway import ToolGateway
from agent_platform.tools.registry import build_default_registry


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    (root / "MyProj").mkdir()
    return root


@pytest.fixture
def gateway(workspace):
    sandbox = FilesystemSandbox(workspace)
    evaluator = PermissionEvaluator(sandbox)
    return ToolGateway(build_default_registry(), evaluator, EventLog())


def test_unknown_tool_is_reported_and_never_reaches_permission(gateway, workspace):
    obs = gateway.invoke(role=Role.CODER, tool_name="shell.run", arguments={},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "unknown_tool"


def test_invalid_schema_is_reported_before_execution(gateway, workspace):
    obs = gateway.invoke(role=Role.CODER, tool_name="filesystem.write", arguments={"path": "app.py"},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "invalid_schema"


def test_denied_by_role_is_reported(gateway, workspace):
    obs = gateway.invoke(role=Role.PLANNER, tool_name="filesystem.write",
                          arguments={"path": "app.py", "content": "x"},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "denied"


def test_denied_by_sandbox_path_escape_is_reported(gateway, workspace, tmp_path):
    outside = str(tmp_path / "Outside" / "evil.py")
    obs = gateway.invoke(role=Role.CODER, tool_name="filesystem.write",
                          arguments={"path": outside, "content": "x"},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "denied"


def test_confirmation_mode_reports_requires_confirmation_not_ok(gateway, workspace):
    obs = gateway.invoke(role=Role.CODER, tool_name="filesystem.write",
                          arguments={"path": "app.py", "content": "x"},
                          session_mode=SessionMode.CONFIRMATION, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "requires_confirmation"
    assert not (workspace / "MyProj" / "app.py").exists()


def test_successful_write_executes_and_returns_ok(gateway, workspace):
    obs = gateway.invoke(role=Role.CODER, tool_name="filesystem.write",
                          arguments={"path": "app.py", "content": "x = 1"},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "ok"
    assert (workspace / "MyProj" / "app.py").read_text(encoding="utf-8") == "x = 1"


def test_precondition_failure_is_reported_as_error_not_a_crash(gateway, workspace):
    obs = gateway.invoke(role=Role.CODER, tool_name="filesystem.read", arguments={"path": "missing.py"},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "error"


def test_all_git_write_tools_are_denied_regardless_of_registration(gateway, workspace):
    for tool in ["git.init", "git.add", "git.commit", "git.push", "git.reset", "git.rebase"]:
        obs = gateway.invoke(role=Role.CODER, tool_name=tool, arguments={},
                              session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
        assert obs.status in ("unknown_tool", "denied"), f"{tool} was not rejected: {obs.status}"
        assert obs.status != "ok"


def test_shell_run_is_denied_regardless_of_registration(gateway, workspace):
    obs = gateway.invoke(role=Role.CODER, tool_name="shell.run", arguments={"command": "echo hi"},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status != "ok"


def test_every_invocation_is_logged(gateway, workspace):
    log = gateway._event_log if hasattr(gateway, "_event_log") else None
    gateway.invoke(role=Role.CODER, tool_name="filesystem.write",
                    arguments={"path": "app.py", "content": "x"},
                    session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert len(gateway.event_log.internal_stream()) >= 1
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_gateway.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_platform.tools.gateway'`

- [ ] **Step 3: Implement**

`src/agent_platform/tools/gateway.py`:
```python
"""The tool gateway is the only path from a model-requested tool call to
actual execution - for every role alike, no exceptions. Every invocation
passes through six steps, in order:

  1. schema validation    - is this a known tool, are arguments well-typed
  2. permission evaluation - role x session-mode x DENY-absolute x
     sandboxed path containment, via Phase 0's PermissionEvaluator (which
     is already path-aware, so this one call covers both the tool-level
     and path-level decision)
  3. argument/path preconditions - business-logic checks that aren't
     security-relevant but must hold before execution (e.g. a read
     target must actually exist) - by this point the path is already
     known-safe, so these are correctness checks, not security checks
  4. execute
  5. wrap as a structured ToolObservation
  6. log the event

No step is ever skipped, and no step behaves differently by role - the
Planner, Coder, and Reviewer all go through exactly this pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..events import EventLog, EventType
from ..security.enums import Role, SessionMode, ToolPermission
from ..security.permission import PermissionEvaluator, ToolCall
from .registry import ToolRegistry
from .schemas import ToolArgumentError, ToolExecutionContext, ToolPreconditionError


@dataclass(frozen=True)
class ToolObservation:
    status: str
    tool_name: str
    result: Optional[dict]
    error: Optional[str]


class ToolGateway:
    def __init__(self, registry: ToolRegistry, evaluator: PermissionEvaluator, event_log: EventLog):
        self._registry = registry
        self._evaluator = evaluator
        self.event_log = event_log

    def invoke(self, *, role: Role, tool_name: str, arguments: dict,
               session_mode: SessionMode, project_root: Path) -> ToolObservation:
        # 1. schema validation
        spec = self._registry.get(tool_name)
        if spec is None:
            return self._finish(role, tool_name, arguments, ToolObservation(
                status="unknown_tool", tool_name=tool_name, result=None,
                error=f"no such tool: {tool_name}"))
        try:
            validated_args = spec.validate_arguments(arguments)
        except ToolArgumentError as exc:
            return self._finish(role, tool_name, arguments, ToolObservation(
                status="invalid_schema", tool_name=tool_name, result=None, error=str(exc)))

        # 2. permission evaluation (role x session-mode x DENY-absolute x sandboxed path)
        path_argument = validated_args.get(spec.path_argument_key) if spec.path_argument_key else None
        call = ToolCall(role=role, tool_name=tool_name, path_argument=path_argument, scope_root=project_root)
        decision = self._evaluator.evaluate(call, session_mode)
        if decision.permission == ToolPermission.DENY:
            return self._finish(role, tool_name, arguments, ToolObservation(
                status="denied", tool_name=tool_name, result=None, error=decision.reason))
        if decision.permission == ToolPermission.CONFIRM:
            return self._finish(role, tool_name, arguments, ToolObservation(
                status="requires_confirmation", tool_name=tool_name, result=None, error=decision.reason))

        # 3. argument/path preconditions
        ctx = ToolExecutionContext(resolved_path=decision.resolved_path, project_root=project_root)
        try:
            spec.check_preconditions(validated_args, ctx)
        except ToolPreconditionError as exc:
            return self._finish(role, tool_name, arguments, ToolObservation(
                status="error", tool_name=tool_name, result=None, error=str(exc)))

        # 4-5. execute + wrap
        try:
            result = spec.execute(validated_args, ctx)
            obs = ToolObservation(status="ok", tool_name=tool_name, result=result, error=None)
        except Exception as exc:
            obs = ToolObservation(status="error", tool_name=tool_name, result=None, error=str(exc))

        # 6. log
        return self._finish(role, tool_name, arguments, obs)

    def _finish(self, role: Role, tool_name: str, arguments: dict, obs: ToolObservation) -> ToolObservation:
        event_type = EventType.TOOL_INVOKED if obs.status == "ok" else EventType.TOOL_DENIED
        self.event_log.emit(event_type, "internal", {
            "role": role.value, "tool": tool_name, "arguments": arguments,
            "status": obs.status, "error": obs.error,
        })
        return obs
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_gateway.py -v`
Expected: PASS (10 tests)

---

### Task 6: Deterministic validation interface

**Files:**
- Create: `src/agent_platform/orchestrator/validation.py`
- Create: `tests/test_validation.py`

**Interfaces:**
- Consumes: `SpecVersion` (Phase 0's `spec/versioning.py`)
- Produces: `@dataclass(frozen=True) class ValidationResult(passed: bool,
  details: tuple[str, ...])`; `class Validator(Protocol)` with method
  `validate(project_root: Path, spec: SpecVersion) -> ValidationResult`;
  `class AcceptanceCriteriaFileValidator` implementing it. Task 7's
  orchestrator is constructed with a `Validator` and calls
  `.validate(project_root, spec)` in the `TEST` state.

- [ ] **Step 1: Write the failing tests**

`tests/test_validation.py`:
```python
from agent_platform.orchestrator.validation import AcceptanceCriteriaFileValidator
from agent_platform.spec.versioning import SpecStore


def _spec(**kwargs):
    store = SpecStore()
    defaults = {"goals": ["g"], "constraints": [], "acceptance_criteria": []}
    defaults.update(kwargs)
    return store.create("task-1", **defaults)


def test_passes_when_all_file_criteria_exist(tmp_path):
    (tmp_path / "app.py").write_text("x", encoding="utf-8")
    spec = _spec(acceptance_criteria=["file:app.py"])
    result = AcceptanceCriteriaFileValidator().validate(tmp_path, spec)
    assert result.passed


def test_fails_when_a_file_criterion_is_missing(tmp_path):
    spec = _spec(acceptance_criteria=["file:missing.py"])
    result = AcceptanceCriteriaFileValidator().validate(tmp_path, spec)
    assert not result.passed
    assert any("MISSING" in d for d in result.details)


def test_non_file_criteria_are_advisory_and_never_fail_validation(tmp_path):
    spec = _spec(acceptance_criteria=["the app should feel fast"])
    result = AcceptanceCriteriaFileValidator().validate(tmp_path, spec)
    assert result.passed
    assert any("ADVISORY" in d for d in result.details)


def test_no_criteria_passes_trivially(tmp_path):
    spec = _spec(acceptance_criteria=[])
    result = AcceptanceCriteriaFileValidator().validate(tmp_path, spec)
    assert result.passed
    assert result.details == ()


def test_mixed_criteria_fail_overall_if_any_file_criterion_is_missing(tmp_path):
    (tmp_path / "present.py").write_text("x", encoding="utf-8")
    spec = _spec(acceptance_criteria=["file:present.py", "file:absent.py", "should be fast"])
    result = AcceptanceCriteriaFileValidator().validate(tmp_path, spec)
    assert not result.passed
    assert len(result.details) == 3
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_validation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_platform.orchestrator.validation'`

- [ ] **Step 3: Implement**

`src/agent_platform/orchestrator/validation.py`:
```python
"""Deterministic validation interface. Phase 1 doesn't execute generated
code (no test.run/lint.run/typecheck.run tool exists yet - see the plan's
Global Constraints), so the one thing checkable without running arbitrary
code is file existence: an acceptance criterion of the form
'file:<relative-path>' is a real, working deterministic gate. Any other
criterion is recorded as advisory - honestly labeled as something this
phase cannot verify, rather than silently claiming a pass it can't back
up.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..spec.versioning import SpecVersion


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    details: tuple[str, ...]


class Validator(Protocol):
    def validate(self, project_root: Path, spec: SpecVersion) -> ValidationResult: ...


class AcceptanceCriteriaFileValidator:
    def validate(self, project_root: Path, spec: SpecVersion) -> ValidationResult:
        details = []
        passed = True
        for criterion in spec.acceptance_criteria:
            if criterion.startswith("file:"):
                rel = criterion[len("file:"):]
                if (project_root / rel).is_file():
                    details.append(f"OK: {criterion}")
                else:
                    details.append(f"MISSING: {criterion}")
                    passed = False
            else:
                details.append(f"ADVISORY (not deterministically checkable in Phase 1): {criterion}")
        return ValidationResult(passed=passed, details=tuple(details))
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_validation.py -v`
Expected: PASS (5 tests)

---

### Task 7: Orchestrator state machine — happy path

**Files:**
- Create: `src/agent_platform/orchestrator/states.py`
- Create: `src/agent_platform/orchestrator/core.py`
- Create: `tests/test_orchestrator_happy_path.py`

**Interfaces:**
- Consumes: everything from Tasks 1-6 plus Phase 0's `SpecStore`,
  `SpecVersionMismatchError`, `Role`, `SessionMode`
- Produces: `class State(Enum)` with all 16 states from the plan brief;
  `TERMINAL_STATES`; `@dataclass(frozen=True) class OrchestratorResult
  (final_state: State, spec_id: str, summary: str)`; `class Orchestrator`
  with constructor `Orchestrator(*, gateway, model, spec_store, event_log,
  session_mode, project_root, max_output_retries=3,
  max_clarification_rounds=3, max_fix_iterations=3)`, property `state ->
  State`, and method `run(spec_id: str, user_request: str) ->
  OrchestratorResult`. Task 8 and 9 add methods to this same class in the
  same file — read `core.py` as written by this task before adding to it,
  don't recreate it.

- [ ] **Step 1: Write the failing tests**

`tests/test_orchestrator_happy_path.py`:
```python
import pytest

from agent_platform.events import EventLog
from agent_platform.orchestrator.core import Orchestrator, State
from agent_platform.orchestrator.fake_model import FakeModelProvider
from agent_platform.orchestrator.validation import AcceptanceCriteriaFileValidator
from agent_platform.security.enums import Role, SessionMode
from agent_platform.security.permission import PermissionEvaluator
from agent_platform.security.sandbox import FilesystemSandbox
from agent_platform.spec.versioning import SpecStore
from agent_platform.tools.gateway import ToolGateway
from agent_platform.tools.registry import build_default_registry


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    (root / "MyProj").mkdir()
    return root


def _build_orchestrator(workspace, model, **overrides):
    sandbox = FilesystemSandbox(workspace)
    evaluator = PermissionEvaluator(sandbox)
    event_log = EventLog()
    gateway = ToolGateway(build_default_registry(), evaluator, event_log)
    kwargs = dict(
        gateway=gateway, model=model, spec_store=SpecStore(), event_log=event_log,
        session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve(),
        validator=AcceptanceCriteriaFileValidator(),
    )
    kwargs.update(overrides)
    return Orchestrator(**kwargs), event_log


def test_full_happy_path_reaches_complete(workspace):
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["build app"], "constraints": [],
                             "acceptance_criteria": ["file:app.py"]}],
        coder_responses=[{"status": "completed", "spec_version_label": "task-1-v1",
                           "summary": "wrote app.py",
                           "file_writes": [{"path": "app.py", "content": "print('hi')"}]}],
        reviewer_responses=[{"spec_version_label": "task-1-v1", "decision": "APPROVE",
                              "requirements_met": True, "security_ok": True,
                              "validation_ok": True, "issues": []}],
    )
    orchestrator, _ = _build_orchestrator(workspace, model)
    result = orchestrator.run("task-1", "build me an app")
    assert result.final_state == State.COMPLETE
    assert (workspace / "MyProj" / "app.py").read_text(encoding="utf-8") == "print('hi')"


def test_final_validation_gate_fails_despite_reviewer_approval_and_returns_to_feedback(workspace):
    # Reviewer approves but the deterministic gate (missing acceptance file)
    # still fails - FINAL_VALIDATION must not treat approval alone as enough.
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["build app"], "constraints": [],
                             "acceptance_criteria": ["file:app.py"]}],
        coder_responses=[
            {"status": "completed", "spec_version_label": "task-1-v1", "summary": "wrote wrong file",
             "file_writes": [{"path": "wrong.py", "content": "x"}]},
            {"status": "completed", "spec_version_label": "task-1-v1", "summary": "wrote app.py",
             "file_writes": [{"path": "app.py", "content": "x"}]},
        ],
        reviewer_responses=[
            {"spec_version_label": "task-1-v1", "decision": "APPROVE", "requirements_met": True,
             "security_ok": True, "validation_ok": True, "issues": []},
            {"spec_version_label": "task-1-v1", "decision": "APPROVE", "requirements_met": True,
             "security_ok": True, "validation_ok": True, "issues": []},
        ],
    )
    orchestrator, _ = _build_orchestrator(workspace, model)
    result = orchestrator.run("task-1", "build me an app")
    assert result.final_state == State.COMPLETE
    assert (workspace / "MyProj" / "app.py").exists()


def test_state_transitions_are_logged_in_order(workspace):
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []}],
        coder_responses=[{"status": "completed", "spec_version_label": "task-1-v1",
                           "summary": "s", "file_writes": []}],
        reviewer_responses=[{"spec_version_label": "task-1-v1", "decision": "APPROVE",
                              "requirements_met": True, "security_ok": True,
                              "validation_ok": True, "issues": []}],
    )
    orchestrator, event_log = _build_orchestrator(workspace, model)
    orchestrator.run("task-1", "build me an app")
    transitions = [e.payload["to"] for e in event_log.internal_stream()
                   if e.event_type.name == "STATE_TRANSITION"]
    assert transitions == ["PLAN", "VALIDATE_PLAN", "IMPLEMENT", "TEST", "REVIEW",
                            "FINAL_VALIDATION", "COMPLETE"]


def test_user_and_internal_streams_stay_separated(workspace):
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []}],
        coder_responses=[{"status": "completed", "spec_version_label": "task-1-v1",
                           "summary": "s", "file_writes": []}],
        reviewer_responses=[{"spec_version_label": "task-1-v1", "decision": "APPROVE",
                              "requirements_met": True, "security_ok": True,
                              "validation_ok": True, "issues": []}],
    )
    orchestrator, event_log = _build_orchestrator(workspace, model)
    orchestrator.run("task-1", "build me an app")
    assert len(event_log.user_stream()) >= 1
    assert all(e.event_type.name != "STATE_TRANSITION" for e in event_log.user_stream())
    assert all(e.event_type.name != "TOOL_INVOKED" or e.stream == "internal"
               for e in event_log.events())
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_orchestrator_happy_path.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_platform.orchestrator.core'`

- [ ] **Step 3: Implement**

`src/agent_platform/orchestrator/states.py`:
```python
"""The Phase 1 lifecycle state machine, per architecture-review-v3's
revised state diagram. AWAITING_USER_INPUT (routine - the Planner needs
one fact from the user) and STUCK (abnormal - iteration exhaustion or a
detected stall) are deliberately distinct states, never merged - see
architecture-review-v3-agent-interaction.md section 1.3 for why.
"""
from __future__ import annotations

from enum import Enum


class State(Enum):
    RECEIVE_REQUEST = "RECEIVE_REQUEST"
    PLAN = "PLAN"
    AWAITING_USER_INPUT = "AWAITING_USER_INPUT"
    VALIDATE_PLAN = "VALIDATE_PLAN"
    IMPLEMENT = "IMPLEMENT"
    BLOCKED = "BLOCKED"
    RESOLVE_CLARIFICATION = "RESOLVE_CLARIFICATION"
    TEST = "TEST"
    REVIEW = "REVIEW"
    FEEDBACK = "FEEDBACK"
    IMPLEMENT_FIX = "IMPLEMENT_FIX"
    AMEND_REQUIREMENTS = "AMEND_REQUIREMENTS"
    FINAL_VALIDATION = "FINAL_VALIDATION"
    STUCK = "STUCK"
    ESCALATE_TO_USER = "ESCALATE_TO_USER"
    COMPLETE = "COMPLETE"


TERMINAL_STATES = frozenset({State.COMPLETE, State.ESCALATE_TO_USER})
```

`src/agent_platform/orchestrator/core.py`:
```python
"""The deterministic orchestrator. Models propose (via ModelProvider),
the orchestrator decides (every transition below is driven by a
schema-validated structured output or a deterministic gate, never by
parsing free-form prose). No model gets a direct execution path - file
writes go through the ToolGateway, which re-enforces Phase 0's sandbox
and permission system on every call.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..events import EventLog, EventType
from ..security.enums import Role, SessionMode
from ..spec.versioning import SpecStore, SpecVersion, SpecVersionMismatchError
from ..tools.gateway import ToolGateway
from .fake_model import ModelTimeoutError
from .model_schemas import (
    CoderBlocked,
    CoderCompleted,
    PlannerClarification,
    PlannerSpec,
    SchemaValidationError,
    parse_coder_output,
    parse_planner_output,
    parse_reviewer_output,
)
from .states import State
from .validation import Validator


@dataclass(frozen=True)
class OrchestratorResult:
    final_state: State
    spec_id: str
    summary: str


class Orchestrator:
    def __init__(self, *, gateway: ToolGateway, model, spec_store: SpecStore,
                 event_log: EventLog, session_mode: SessionMode, project_root: Path,
                 validator: Validator, max_output_retries: int = 3,
                 max_clarification_rounds: int = 3, max_fix_iterations: int = 3):
        self._gateway = gateway
        self._model = model
        self._spec_store = spec_store
        self._event_log = event_log
        self._session_mode = session_mode
        self._project_root = project_root
        self._validator = validator
        self._max_output_retries = max_output_retries
        self._max_clarification_rounds = max_clarification_rounds
        self._max_fix_iterations = max_fix_iterations
        self._state = State.RECEIVE_REQUEST

    @property
    def state(self) -> State:
        return self._state

    def run(self, spec_id: str, user_request: str) -> OrchestratorResult:
        self._event_log.emit(EventType.USER_REQUEST_RECEIVED, "user", {"spec_id": spec_id, "request": user_request})
        self._user_event(user_request)
        self._transition(State.PLAN)
        plan_output = self._invoke_with_retry(
            "planner", lambda: self._model.plan({"request": user_request}), parse_planner_output)
        return self._after_plan(spec_id, plan_output)

    # ----------------------------------------------------------- internals

    def _transition(self, new_state: State) -> None:
        self._event_log.emit(EventType.STATE_TRANSITION, "internal",
                              {"from": self._state.value, "to": new_state.value})
        self._state = new_state

    def _user_event(self, text: str) -> None:
        self._event_log.emit(EventType.USER_MESSAGE, "user", {"text": text})

    def _invoke_with_retry(self, role_name: str, call_fn, parse_fn):
        for _ in range(self._max_output_retries):
            try:
                raw = call_fn()
            except ModelTimeoutError:
                self._event_log.emit(EventType.MODEL_OUTPUT_INVALID, "internal",
                                      {"role": role_name, "error": "timeout"})
                continue
            try:
                return parse_fn(raw)
            except SchemaValidationError as exc:
                self._event_log.emit(EventType.MODEL_OUTPUT_INVALID, "internal",
                                      {"role": role_name, "error": str(exc)})
                continue
        return None

    def _after_plan(self, spec_id: str, plan_output) -> OrchestratorResult:
        if plan_output is None:
            return self._stuck(spec_id, "planner output invalid after max retries")
        if isinstance(plan_output, PlannerClarification):
            self._transition(State.AWAITING_USER_INPUT)
            self._user_event(plan_output.question)
            return OrchestratorResult(State.AWAITING_USER_INPUT, spec_id, plan_output.question)
        spec = self._spec_store.create(
            spec_id, goals=plan_output.goals, constraints=plan_output.constraints,
            acceptance_criteria=plan_output.acceptance_criteria)
        self._event_log.emit(EventType.SPEC_VERSION_CREATED, "internal", {"version_label": spec.version_label})
        return self._validate_plan(spec_id, spec)

    def _validate_plan(self, spec_id: str, spec: SpecVersion) -> OrchestratorResult:
        self._transition(State.VALIDATE_PLAN)
        if not spec.goals:
            return self._stuck(spec_id, "plan failed deterministic validation: no goals")
        return self._implement(spec_id, spec, reviewer_feedback=None, fix_iteration=0)

    def _implement(self, spec_id: str, spec: SpecVersion, reviewer_feedback, fix_iteration: int) -> OrchestratorResult:
        self._transition(State.IMPLEMENT_FIX if fix_iteration > 0 else State.IMPLEMENT)
        coder_output = self._invoke_with_retry(
            "coder", lambda: self._model.code({"spec": spec, "reviewer_feedback": reviewer_feedback}),
            parse_coder_output)
        if coder_output is None:
            return self._stuck(spec_id, "coder output invalid after max retries")
        if isinstance(coder_output, CoderBlocked):
            return self._blocked(spec_id, spec, coder_output, fix_iteration, clarification_round=0)

        try:
            self._spec_store.assert_current(spec_id, coder_output.spec_version_label)
        except SpecVersionMismatchError as exc:
            self._event_log.emit(EventType.SPEC_VERSION_MISMATCH, "internal",
                                  {"expected": exc.expected, "actual": exc.actual})
            return self._stuck(spec_id, f"coder attempt pinned to wrong specification version: {exc}")

        failed = self._apply_file_writes(coder_output)
        if failed is not None:
            return self._stuck(spec_id, f"file write failed during implement: {failed.error}")
        return self._test_and_review(spec_id, spec, coder_output, fix_iteration)

    def _apply_file_writes(self, coder_output: CoderCompleted):
        for write in coder_output.file_writes:
            obs = self._gateway.invoke(
                role=Role.CODER, tool_name="filesystem.write",
                arguments={"path": write.path, "content": write.content},
                session_mode=self._session_mode, project_root=self._project_root)
            if obs.status != "ok":
                return obs
        return None

    def _test_and_review(self, spec_id: str, spec: SpecVersion, coder_output: CoderCompleted,
                          fix_iteration: int) -> OrchestratorResult:
        self._transition(State.TEST)
        validation_result = self._validator.validate(self._project_root, spec)
        self._transition(State.REVIEW)
        reviewer_output = self._invoke_with_retry(
            "reviewer",
            lambda: self._model.review({"spec": spec, "coder_output": coder_output,
                                         "validation_result": validation_result}),
            parse_reviewer_output)
        if reviewer_output is None:
            return self._stuck(spec_id, "reviewer output invalid after max retries")
        try:
            self._spec_store.assert_current(spec_id, reviewer_output.spec_version_label)
        except SpecVersionMismatchError as exc:
            self._event_log.emit(EventType.SPEC_VERSION_MISMATCH, "internal",
                                  {"expected": exc.expected, "actual": exc.actual})
            return self._stuck(spec_id, f"reviewer spec version mismatch: {exc}")

        if reviewer_output.decision == "APPROVE":
            return self._final_validation(spec_id, spec, coder_output, validation_result,
                                           reviewer_output, fix_iteration)
        return self._feedback(spec_id, spec, reviewer_output, fix_iteration)

    def _final_validation(self, spec_id, spec, coder_output, validation_result, reviewer_output, fix_iteration):
        self._transition(State.FINAL_VALIDATION)
        gates_pass = (validation_result.passed and reviewer_output.requirements_met
                      and reviewer_output.security_ok and reviewer_output.validation_ok)
        if gates_pass:
            self._transition(State.COMPLETE)
            self._user_event(coder_output.summary)
            return OrchestratorResult(State.COMPLETE, spec_id, coder_output.summary)
        return self._feedback(spec_id, spec, reviewer_output, fix_iteration)

    def _feedback(self, spec_id: str, spec: SpecVersion, reviewer_output, fix_iteration: int) -> OrchestratorResult:
        self._transition(State.FEEDBACK)
        if fix_iteration >= self._max_fix_iterations:
            return self._stuck(spec_id, f"fix loop exceeded {self._max_fix_iterations} iterations")
        return self._implement(spec_id, spec, reviewer_output, fix_iteration + 1)

    def _blocked(self, spec_id, spec, coder_output: CoderBlocked, fix_iteration, clarification_round):
        self._transition(State.BLOCKED)
        if clarification_round >= self._max_clarification_rounds:
            return self._stuck(spec_id, f"clarification loop exceeded {self._max_clarification_rounds} rounds")
        return self._resolve_clarification(spec_id, spec, coder_output, fix_iteration, clarification_round + 1)

    def _resolve_clarification(self, spec_id, spec, coder_output: CoderBlocked, fix_iteration, clarification_round):
        self._transition(State.RESOLVE_CLARIFICATION)
        resolution = self._invoke_with_retry(
            "planner",
            lambda: self._model.plan({"spec": spec, "blocking_questions": coder_output.blocking_questions}),
            parse_planner_output)
        if resolution is None:
            return self._stuck(spec_id, "planner clarification output invalid after max retries")
        if isinstance(resolution, PlannerClarification):
            self._transition(State.AWAITING_USER_INPUT)
            self._user_event(resolution.question)
            return OrchestratorResult(State.AWAITING_USER_INPUT, spec_id, resolution.question)
        new_spec = self._spec_store.create(
            spec_id, goals=resolution.goals, constraints=resolution.constraints,
            acceptance_criteria=resolution.acceptance_criteria)
        self._event_log.emit(EventType.SPEC_VERSION_CREATED, "internal", {"version_label": new_spec.version_label})
        return self._implement(spec_id, new_spec, reviewer_feedback=None, fix_iteration=fix_iteration)

    def _stuck(self, spec_id: str, reason: str) -> OrchestratorResult:
        self._transition(State.STUCK)
        self._event_log.emit(EventType.INTERNAL, "internal", {"reason": reason})
        self._transition(State.ESCALATE_TO_USER)
        self._user_event(f"I'm stopping and need your input: {reason}")
        return OrchestratorResult(State.ESCALATE_TO_USER, spec_id, reason)
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_orchestrator_happy_path.py -v`
Expected: PASS (4 tests). If `test_final_validation_gate_fails_despite_reviewer_approval_and_returns_to_feedback`
fails, check the FEEDBACK path re-enters `_implement` with `fix_iteration`
correctly threaded through - this is the test most likely to expose an
off-by-one in the fix-iteration counter.

---

### Task 8: Clarification, blocking, and spec-mismatch tests

**Files:**
- Create: `tests/test_orchestrator_clarification.py`

**Interfaces:**
- Consumes: `Orchestrator`, `State`, `OrchestratorResult` (Task 7) — no
  new production code, this task adds coverage for behavior Task 7 already
  implements (`_blocked`/`_resolve_clarification`, spec-mismatch handling)
  the happy-path task didn't exercise.

- [ ] **Step 1: Write the tests**

`tests/test_orchestrator_clarification.py`:
```python
import pytest

from agent_platform.events import EventLog
from agent_platform.orchestrator.core import Orchestrator, State
from agent_platform.orchestrator.fake_model import FakeModelProvider
from agent_platform.orchestrator.validation import AcceptanceCriteriaFileValidator
from agent_platform.security.enums import SessionMode
from agent_platform.security.permission import PermissionEvaluator
from agent_platform.security.sandbox import FilesystemSandbox
from agent_platform.spec.versioning import SpecStore
from agent_platform.tools.gateway import ToolGateway
from agent_platform.tools.registry import build_default_registry


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    (root / "MyProj").mkdir()
    return root


def _build_orchestrator(workspace, model, **overrides):
    sandbox = FilesystemSandbox(workspace)
    evaluator = PermissionEvaluator(sandbox)
    event_log = EventLog()
    gateway = ToolGateway(build_default_registry(), evaluator, event_log)
    kwargs = dict(
        gateway=gateway, model=model, spec_store=SpecStore(), event_log=event_log,
        session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve(),
        validator=AcceptanceCriteriaFileValidator(),
    )
    kwargs.update(overrides)
    return Orchestrator(**kwargs), event_log


def test_coder_blocked_then_clarified_then_completes(workspace):
    model = FakeModelProvider(
        planner_responses=[
            {"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []},
            {"kind": "spec", "goals": ["g", "use OAuth"], "constraints": [], "acceptance_criteria": []},
        ],
        coder_responses=[
            {"status": "blocked", "spec_version_label": "task-1-v1", "reason": "ambiguous auth",
             "attempted": "read existing code", "blocking_questions": ["OAuth or API keys?"]},
            {"status": "completed", "spec_version_label": "task-1-v2", "summary": "used OAuth",
             "file_writes": []},
        ],
        reviewer_responses=[{"spec_version_label": "task-1-v2", "decision": "APPROVE",
                              "requirements_met": True, "security_ok": True,
                              "validation_ok": True, "issues": []}],
    )
    orchestrator, event_log = _build_orchestrator(workspace, model)
    result = orchestrator.run("task-1", "build an app with login")
    assert result.final_state == State.COMPLETE
    transitions = [e.payload["to"] for e in event_log.internal_stream() if e.event_type.name == "STATE_TRANSITION"]
    assert "BLOCKED" in transitions
    assert "RESOLVE_CLARIFICATION" in transitions


def test_planner_itself_needs_user_input_during_clarification(workspace):
    model = FakeModelProvider(
        planner_responses=[
            {"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []},
            {"kind": "needs_user_input", "question": "OAuth or API keys?"},
        ],
        coder_responses=[
            {"status": "blocked", "spec_version_label": "task-1-v1", "reason": "ambiguous auth",
             "attempted": "read existing code", "blocking_questions": ["OAuth or API keys?"]},
        ],
        reviewer_responses=[],
    )
    orchestrator, _ = _build_orchestrator(workspace, model)
    result = orchestrator.run("task-1", "build an app with login")
    assert result.final_state == State.AWAITING_USER_INPUT
    assert result.summary == "OAuth or API keys?"


def test_repeated_blocking_beyond_cap_escalates_to_stuck(workspace):
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []}]
        + [{"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []} for _ in range(5)],
        coder_responses=[
            {"status": "blocked", "spec_version_label": f"task-1-v{i}", "reason": "still ambiguous",
             "attempted": "tried again", "blocking_questions": ["still unclear"]}
            for i in range(1, 6)
        ],
        reviewer_responses=[],
    )
    orchestrator, event_log = _build_orchestrator(workspace, model, max_clarification_rounds=3)
    result = orchestrator.run("task-1", "build something vague")
    assert result.final_state == State.ESCALATE_TO_USER
    transitions = [e.payload["to"] for e in event_log.internal_stream() if e.event_type.name == "STATE_TRANSITION"]
    assert transitions[-2:] == ["STUCK", "ESCALATE_TO_USER"]


def test_coder_pinned_to_stale_spec_version_is_deterministically_rejected(workspace):
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []}],
        coder_responses=[{"status": "completed", "spec_version_label": "task-1-v99",
                           "summary": "s", "file_writes": []}],
        reviewer_responses=[],
    )
    orchestrator, event_log = _build_orchestrator(workspace, model)
    result = orchestrator.run("task-1", "build an app")
    assert result.final_state == State.ESCALATE_TO_USER
    assert "version" in result.summary.lower()
    mismatches = [e for e in event_log.internal_stream() if e.event_type.name == "SPEC_VERSION_MISMATCH"]
    assert len(mismatches) == 1


def test_reviewer_pinned_to_stale_spec_version_is_deterministically_rejected(workspace):
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []}],
        coder_responses=[{"status": "completed", "spec_version_label": "task-1-v1",
                           "summary": "s", "file_writes": []}],
        reviewer_responses=[{"spec_version_label": "task-1-v0", "decision": "APPROVE",
                              "requirements_met": True, "security_ok": True,
                              "validation_ok": True, "issues": []}],
    )
    orchestrator, _ = _build_orchestrator(workspace, model)
    result = orchestrator.run("task-1", "build an app")
    assert result.final_state == State.ESCALATE_TO_USER


def test_malformed_planner_output_retries_then_succeeds(workspace):
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec"}, {"kind": "spec", "goals": ["g"], "constraints": [],
                                                "acceptance_criteria": []}],
        coder_responses=[{"status": "completed", "spec_version_label": "task-1-v1", "summary": "s",
                           "file_writes": []}],
        reviewer_responses=[{"spec_version_label": "task-1-v1", "decision": "APPROVE",
                              "requirements_met": True, "security_ok": True,
                              "validation_ok": True, "issues": []}],
    )
    orchestrator, event_log = _build_orchestrator(workspace, model)
    result = orchestrator.run("task-1", "build an app")
    assert result.final_state == State.COMPLETE
    invalid_events = [e for e in event_log.internal_stream() if e.event_type.name == "MODEL_OUTPUT_INVALID"]
    assert len(invalid_events) == 1


def test_malformed_planner_output_exhausting_retries_escalates(workspace):
    model = FakeModelProvider(planner_responses=[{"kind": "spec"}] * 3)
    orchestrator, _ = _build_orchestrator(workspace, model, max_output_retries=3)
    result = orchestrator.run("task-1", "build an app")
    assert result.final_state == State.ESCALATE_TO_USER


def test_model_timeout_is_retried_then_can_succeed(workspace):
    from agent_platform.orchestrator.fake_model import TIMEOUT
    model = FakeModelProvider(
        planner_responses=[TIMEOUT, {"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []}],
        coder_responses=[{"status": "completed", "spec_version_label": "task-1-v1", "summary": "s",
                           "file_writes": []}],
        reviewer_responses=[{"spec_version_label": "task-1-v1", "decision": "APPROVE",
                              "requirements_met": True, "security_ok": True,
                              "validation_ok": True, "issues": []}],
    )
    orchestrator, _ = _build_orchestrator(workspace, model)
    result = orchestrator.run("task-1", "build an app")
    assert result.final_state == State.COMPLETE


def test_tool_failure_on_writing_outside_scope_escalates(workspace, tmp_path):
    outside = str(tmp_path / "Outside" / "evil.py")
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []}],
        coder_responses=[{"status": "completed", "spec_version_label": "task-1-v1", "summary": "s",
                           "file_writes": [{"path": outside, "content": "malicious"}]}],
        reviewer_responses=[],
    )
    orchestrator, _ = _build_orchestrator(workspace, model)
    result = orchestrator.run("task-1", "build an app")
    assert result.final_state == State.ESCALATE_TO_USER
    assert not (tmp_path / "Outside").exists()


def test_reviewer_rejection_then_fix_then_approve(workspace):
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []}],
        coder_responses=[
            {"status": "completed", "spec_version_label": "task-1-v1", "summary": "v1",
             "file_writes": [{"path": "app.py", "content": "bug"}]},
            {"status": "completed", "spec_version_label": "task-1-v1", "summary": "v2 fixed",
             "file_writes": [{"path": "app.py", "content": "fixed"}]},
        ],
        reviewer_responses=[
            {"spec_version_label": "task-1-v1", "decision": "REJECT", "requirements_met": False,
             "security_ok": True, "validation_ok": True,
             "issues": [{"severity": "high", "file": "app.py", "description": "bug",
                         "required_fix": "fix it"}]},
            {"spec_version_label": "task-1-v1", "decision": "APPROVE", "requirements_met": True,
             "security_ok": True, "validation_ok": True, "issues": []},
        ],
    )
    orchestrator, event_log = _build_orchestrator(workspace, model)
    result = orchestrator.run("task-1", "build an app")
    assert result.final_state == State.COMPLETE
    assert (workspace / "MyProj" / "app.py").read_text(encoding="utf-8") == "fixed"
    transitions = [e.payload["to"] for e in event_log.internal_stream() if e.event_type.name == "STATE_TRANSITION"]
    assert "FEEDBACK" in transitions and "IMPLEMENT_FIX" in transitions


def test_repeated_rejection_beyond_cap_escalates_to_stuck(workspace):
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []}],
        coder_responses=[
            {"status": "completed", "spec_version_label": "task-1-v1", "summary": f"attempt {i}",
             "file_writes": []} for i in range(1, 6)
        ],
        reviewer_responses=[
            {"spec_version_label": "task-1-v1", "decision": "REJECT", "requirements_met": False,
             "security_ok": True, "validation_ok": True,
             "issues": [{"severity": "high", "file": "app.py", "description": "still broken",
                         "required_fix": "fix it"}]} for _ in range(5)
        ],
    )
    orchestrator, _ = _build_orchestrator(workspace, model, max_fix_iterations=3)
    result = orchestrator.run("task-1", "build an app")
    assert result.final_state == State.ESCALATE_TO_USER


def test_amend_requirements_creates_new_spec_version_and_reimplements(workspace):
    model = FakeModelProvider(
        planner_responses=[
            {"kind": "spec", "goals": ["g1"], "constraints": [], "acceptance_criteria": []},
            {"kind": "spec", "goals": ["g1", "g2 - use sqlite"], "constraints": [], "acceptance_criteria": []},
        ],
        coder_responses=[
            {"status": "completed", "spec_version_label": "task-1-v1", "summary": "v1", "file_writes": []},
            {"status": "completed", "spec_version_label": "task-1-v2", "summary": "v2 with sqlite",
             "file_writes": []},
        ],
        reviewer_responses=[
            {"spec_version_label": "task-1-v1", "decision": "APPROVE", "requirements_met": True,
             "security_ok": True, "validation_ok": True, "issues": []},
            {"spec_version_label": "task-1-v2", "decision": "APPROVE", "requirements_met": True,
             "security_ok": True, "validation_ok": True, "issues": []},
        ],
    )
    orchestrator, event_log = _build_orchestrator(workspace, model)
    first = orchestrator.run("task-1", "build an app")
    assert first.final_state == State.COMPLETE
    second = orchestrator.amend_requirements("task-1", "actually use sqlite")
    assert second.final_state == State.COMPLETE
    version_events = [e.payload["version_label"] for e in event_log.internal_stream()
                       if e.event_type.name == "SPEC_VERSION_CREATED"]
    assert version_events == ["task-1-v1", "task-1-v2"]
    transitions = [e.payload["to"] for e in event_log.internal_stream() if e.event_type.name == "STATE_TRANSITION"]
    assert "AMEND_REQUIREMENTS" in transitions
```

- [ ] **Step 2: Run to verify failure (only the amend test should fail — Task 7's `Orchestrator` has no `amend_requirements` method yet)**

Run: `python -m pytest tests/test_orchestrator_clarification.py -v`
Expected: every test except `test_amend_requirements_creates_new_spec_version_and_reimplements`
PASSES already (Task 7's implementation already covers blocked/
clarification/spec-mismatch/retry/tool-failure/fix-loop behavior); the
amend test FAILS with `AttributeError: 'Orchestrator' object has no
attribute 'amend_requirements'`.

---

### Task 9: Requirement amendment entry point

**Files:**
- Modify: `src/agent_platform/orchestrator/core.py` (add one method to
  the `Orchestrator` class from Task 7 — do not recreate the file)

**Interfaces:**
- Consumes: everything already imported in `core.py`
- Produces: `Orchestrator.amend_requirements(spec_id: str,
  amendment_request: str) -> OrchestratorResult`

- [ ] **Step 1: Add the method**

Add to the `Orchestrator` class in `src/agent_platform/orchestrator/core.py`,
after `run`:

```python
    def amend_requirements(self, spec_id: str, amendment_request: str) -> OrchestratorResult:
        """A user-initiated requirement change. Phase 1 exposes this as an
        explicit entry point rather than a live mid-session interrupt -
        the deterministic control plane is what's in scope here, not an
        interactive session loop. A later phase's real session would call
        this the moment an incoming user message is recognized as an
        amendment rather than a status query or an answer to a pending
        question; the state transitions and spec-versioning behavior are
        identical either way."""
        self._user_event(amendment_request)
        self._transition(State.AMEND_REQUIREMENTS)
        plan_output = self._invoke_with_retry(
            "planner", lambda: self._model.plan({"request": amendment_request, "amendment": True}),
            parse_planner_output)
        return self._after_plan(spec_id, plan_output)
```

- [ ] **Step 2: Run to verify the full clarification test file passes**

Run: `python -m pytest tests/test_orchestrator_clarification.py -v`
Expected: PASS (11 tests, including the amend test from Task 8)

---

### Task 10: Orchestrator configuration loading

**Files:**
- Modify: `src/agent_platform/config.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Consumes: existing `PlatformConfig`, `ConfigurationError`
- Produces: `PlatformConfig` gains `session_mode: SessionMode =
  SessionMode.AUTO`, `max_output_retries: int = 3`,
  `max_clarification_rounds: int = 3`, `max_fix_iterations: int = 3`,
  each independently validated in `load`. This is the one place these
  orchestrator-level values become trusted configuration - never read
  from model output, mirroring how the workspace root itself is loaded.

- [ ] **Step 1: Extend the failing tests**

Add to `tests/test_config.py`:
```python
from agent_platform.security.enums import SessionMode


def test_default_session_mode_and_caps(tmp_path):
    config = PlatformConfig.load(str(tmp_path))
    assert config.session_mode == SessionMode.AUTO
    assert config.max_output_retries == 3
    assert config.max_clarification_rounds == 3
    assert config.max_fix_iterations == 3


def test_explicit_session_mode_and_caps_are_honored(tmp_path):
    config = PlatformConfig.load(str(tmp_path), session_mode=SessionMode.MANUAL,
                                  max_output_retries=5, max_clarification_rounds=2,
                                  max_fix_iterations=4)
    assert config.session_mode == SessionMode.MANUAL
    assert config.max_output_retries == 5
    assert config.max_clarification_rounds == 2
    assert config.max_fix_iterations == 4


@pytest.mark.parametrize("field,value", [
    ("max_output_retries", 0), ("max_output_retries", -1),
    ("max_clarification_rounds", 0), ("max_fix_iterations", 0),
])
def test_non_positive_caps_are_rejected(tmp_path, field, value):
    with pytest.raises(ConfigurationError):
        PlatformConfig.load(str(tmp_path), **{field: value})
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `PlatformConfig.load()` doesn't accept these keyword
arguments yet.

- [ ] **Step 3: Implement**

Replace `src/agent_platform/config.py`'s contents with:

```python
"""Trusted configuration loading. The workspace root and orchestrator-
level session settings are read from here only - never from LLM output,
never inferred at runtime from something a model said."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .security.enums import SessionMode


class ConfigurationError(Exception):
    pass


@dataclass(frozen=True)
class PlatformConfig:
    workspace_root: Path
    session_mode: SessionMode = SessionMode.AUTO
    max_output_retries: int = 3
    max_clarification_rounds: int = 3
    max_fix_iterations: int = 3

    @staticmethod
    def load(workspace_root: str, *, session_mode: SessionMode = SessionMode.AUTO,
              max_output_retries: int = 3, max_clarification_rounds: int = 3,
              max_fix_iterations: int = 3) -> "PlatformConfig":
        root = Path(workspace_root)
        if not root.is_absolute():
            raise ConfigurationError(f"workspace_root must be an absolute path, got: {workspace_root}")
        if not root.exists():
            raise ConfigurationError(f"workspace_root does not exist: {root}")
        if not root.is_dir():
            raise ConfigurationError(f"workspace_root is not a directory: {root}")
        for name, value in (
            ("max_output_retries", max_output_retries),
            ("max_clarification_rounds", max_clarification_rounds),
            ("max_fix_iterations", max_fix_iterations),
        ):
            if value <= 0:
                raise ConfigurationError(f"{name} must be a positive integer, got: {value}")
        return PlatformConfig(
            workspace_root=root.resolve(strict=True), session_mode=session_mode,
            max_output_retries=max_output_retries, max_clarification_rounds=max_clarification_rounds,
            max_fix_iterations=max_fix_iterations,
        )
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (9 tests: 5 existing + 4 new)

---

### Task 11: Full suite run and Phase 1 report

**Files:**
- Create: `PHASE1_REPORT.md`

- [ ] **Step 1: Run the complete test suite**

Run: `python -m pytest tests/ -v --tb=short`

Record total passed/failed/skipped. Expected: all Phase 0 tests (453,
including Task 0's 2 additions) plus all Phase 1 tests continue to pass
together in one run — this is the check that Phase 1 didn't regress
Phase 0, not just that Phase 1's own new tests pass in isolation.

- [ ] **Step 2: Confirm no new network dependency**

Run: `grep -rEl "requests|httpx|ollama|urllib.request|socket\." tests/ src/`
Expected: no matches (same check as Phase 0, re-run because Phase 1 added
new source files).

- [ ] **Step 3: Write `PHASE1_REPORT.md`**

Structure it like `PHASE0_REPORT.md`: Implemented, Test results (exact
counts from Step 1), Security/determinism invariants enforced and tested
(the 6-step gateway pipeline, absolute-deny tools still denied end-to-end
through the gateway, spec-version mismatch rejection for both Coder and
Reviewer, AWAITING_USER_INPUT vs STUCK staying distinct, user/internal
event stream separation), scope decisions made explicit (AMEND_REQUIREMENTS
as an entry point not a live interrupt; file-existence-only deterministic
validation; no test.run/lint.run/typecheck.run tools), and remaining
concerns.

- [ ] **Step 4: Stop**

Per the standing instruction, do not proceed to any further phase. Report
back: what was implemented, real test counts, security/determinism
invariants, and scope decisions. Wait for further instructions.
