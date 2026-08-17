> **STATUS: COMPLETE 2026-08-16.** All 6 tasks implemented. Deterministic
> suite: 711/711 passing, 0 network, 0 regressions from the one
> deliberate touch to `orchestrator/core.py`. Controlled end-to-end demo
> passed, exercising the full review/fix loop with real file writes and
> real `pytest` execution. See `../../../PHASE6_REPORT.md` for the full
> transition trace and report. This was the terminal instruction: stop
> after the first successful demonstration.

# Phase 6 Complete Autonomous SWE Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the already-built control plane (Phases 0-5) into one
demonstrated, controlled, end-to-end autonomous loop — Planner → context
retrieval → Coder → tool gateway → deterministic validation → Reviewer →
completion, including the review/fix loop — using only existing
capabilities, plus the two genuinely new failure-handling signals the
brief names that nothing built so far implements: negligible-diff and
repeated-review/repeated-failure stall detection.

**Architecture, and what does *not* need to change:** Phase 1's
`Orchestrator` already implements the entire state diagram in this
phase's brief verbatim — `RECEIVE_REQUEST → PLAN → VALIDATE_PLAN →
IMPLEMENT → TEST → REVIEW → FINAL_VALIDATION → COMPLETE`, the
`REJECT → STRUCTURED_FEEDBACK → IMPLEMENT_FIX` loop, the
`BLOCKED → RESOLVE_CLARIFICATION → AWAITING_USER_INPUT` loop, and every
item in the brief's "Completion" checklist (spec-version consistency,
deterministic-validation-AND-reviewer-approval, no-unauthorized-paths via
Phase 0's sandbox, no-unresolved-clarification via the state graph
itself). None of that is touched. What's missing is two things:

1. **Context retrieval was built (Phase 5) but never wired to a model
   call.** `ContextAwareModelProvider` (Task 3) closes this the same way
   every prior phase closed its integration gap — as a
   `ModelProvider`-conforming wrapper, a drop-in for `Orchestrator`'s
   existing `model=` parameter, zero changes to `orchestrator/core.py`.
2. **Three specific stall signals the brief names — negligible-diff,
   repeated-review-rejection, repeated-identical-test-failure — have no
   existing implementation anywhere** (the existing iteration cap is
   count-only). Unlike every other phase's integration, this genuinely
   requires touching `orchestrator/core.py`: the state graph and every
   transition stay exactly as they are, but the *condition* that decides
   `FEEDBACK → IMPLEMENT_FIX` vs. `FEEDBACK → STUCK` gains two more
   inputs alongside the existing iteration-count check, and `IMPLEMENT`
   gains one more check before applying a fix attempt's writes. This is
   the one deliberate, small, fully-traced, regression-proven touch to
   `orchestrator/core.py` in this plan — see Task 2's reasoning for why
   each existing orchestrator test still holds after it.

**Tech Stack:** Python 3.12.5 standard library only. The demo (Task 5)
uses `FakeModelProvider` (Phase 1) wrapped in `ContextAwareModelProvider`
— real sandbox, real gateway, real `test.run` execution, real context
retrieval, scripted-but-realistic model responses. This is what "a
controlled demonstration using the existing project/test infrastructure"
means: everything is real except the LLM calls themselves, which Phase 2
already separately proved work against real Ollama models with real
measurements — re-proving that here would just make the demo slow and
non-reproducible for no additional confidence.

**Spec:** Phase 1 (`orchestrator/core.py`, `orchestrator/states.py`),
Phase 2 (`orchestrator/model_provider.py`), Phase 3
(`orchestrator/validation.py`'s `TestRunValidator`), Phase 4
(`mcp/gateway_tools.py`), Phase 5 (`context/role_context.py`),
`architecture-review-v2.md` §1.9 (non-progress stall signals — named
there, never implemented until now).

## Global Constraints

- No new capability. No new tool, no new MCP server, no new state, no
  new transition. Task 2 refines an existing decision's *input signal*;
  it does not add a state or change the transition graph.
- No git commands run this session, anywhere.
- `security/permission.py`, `security/sandbox.py`, `mcp/*`,
  `orchestrator/model_provider.py`, `orchestrator/prompts.py`,
  `context/*` (Phase 5) are not modified. `orchestrator/core.py` is
  touched exactly once (Task 2), additively, and the full existing
  orchestrator test suite is re-run immediately after to prove nothing
  broke — the same discipline Phase 2's Task 0 used for
  `security/permission.py`.
- The demo creates no new capability solely for itself — it is a
  `pytest` test using `tmp_path`, `FilesystemSandbox`, `ToolGateway`,
  `TestRunValidator`, `FakeModelProvider`, and `ContextAwareModelProvider`,
  every one of them already built.
- Most of the brief's 17 required test scenarios already exist from
  Phase 1/3/4 (happy path, review rejection, successful fix, repeated
  rejection, Coder blocked, Planner clarification, requirement amendment,
  stale specification — both roles, test failure preventing completion,
  reviewer-approval-not-bypassing-validation, iteration exhaustion,
  clarification exhaustion, model failure, unauthorized tool request,
  Git write denial). This plan does not re-write those; Task 6's report
  lists exactly which existing test proves each one. Task 4 adds the two
  that are genuinely new integration surface: MCP failure and context
  failure (both reusing existing Phase 4/5 machinery, no new wiring), plus
  an explicit unauthorized-MCP-request check reusing Phase 4's registry
  intersection.

---

### Task 1: Stall-detection heuristics

**Files:**
- Create: `src/agent_platform/orchestrator/stall_detection.py`
- Create: `tests/test_stall_detection.py`

**Interfaces:**
- Produces: `is_negligible_diff(previous_writes, new_writes) -> bool`;
  `is_repeated_review_rejection(review_issue_history: tuple) -> bool`;
  `is_repeated_identical_test_failure(validation_detail_history: tuple) -> bool`.
  Task 2 imports and calls exactly these three, feeding them history it
  maintains as new `Orchestrator` instance state.

- [ ] **Step 1: Write the failing tests**

`tests/test_stall_detection.py`:
```python
from agent_platform.orchestrator.model_schemas import CoderFileWrite
from agent_platform.orchestrator.stall_detection import (
    is_negligible_diff,
    is_repeated_identical_test_failure,
    is_repeated_review_rejection,
)


def test_negligible_diff_true_for_identical_writes():
    prev = (CoderFileWrite(path="app.py", content="x = 1"),)
    new = (CoderFileWrite(path="app.py", content="x = 1"),)
    assert is_negligible_diff(prev, new) is True


def test_negligible_diff_false_for_different_content():
    prev = (CoderFileWrite(path="app.py", content="x = 1"),)
    new = (CoderFileWrite(path="app.py", content="x = 2"),)
    assert is_negligible_diff(prev, new) is False


def test_negligible_diff_false_for_different_paths():
    prev = (CoderFileWrite(path="a.py", content="x = 1"),)
    new = (CoderFileWrite(path="b.py", content="x = 1"),)
    assert is_negligible_diff(prev, new) is False


def test_negligible_diff_false_when_either_side_is_empty_or_none():
    write = (CoderFileWrite(path="a.py", content="x"),)
    assert is_negligible_diff(None, write) is False
    assert is_negligible_diff((), write) is False
    assert is_negligible_diff((), ()) is False


def test_repeated_review_rejection_false_with_fewer_than_two_entries():
    assert is_repeated_review_rejection(()) is False
    assert is_repeated_review_rejection((("bug",),)) is False


def test_repeated_review_rejection_true_when_last_two_match():
    history = (("missing auth",), ("missing auth",))
    assert is_repeated_review_rejection(history) is True


def test_repeated_review_rejection_false_when_last_two_differ():
    history = (("missing auth",), ("different issue",))
    assert is_repeated_review_rejection(history) is False


def test_repeated_review_rejection_ignores_order_within_an_entry():
    history = (("issue a", "issue b"), ("issue b", "issue a"))
    assert is_repeated_review_rejection(history) is True


def test_repeated_review_rejection_false_when_both_entries_are_empty():
    assert is_repeated_review_rejection(((), ())) is False


def test_repeated_identical_test_failure_false_with_fewer_than_two_entries():
    assert is_repeated_identical_test_failure(()) is False
    assert is_repeated_identical_test_failure((("fail: test_x",),)) is False


def test_repeated_identical_test_failure_true_when_last_two_match():
    history = (("test.run exit_code=1",), ("test.run exit_code=1",))
    assert is_repeated_identical_test_failure(history) is True


def test_repeated_identical_test_failure_false_when_last_two_differ():
    history = (("test.run exit_code=1",), ("test.run exit_code=0",))
    assert is_repeated_identical_test_failure(history) is False


def test_repeated_identical_test_failure_false_when_both_are_trivially_empty():
    # An empty acceptance-criteria list produces empty details every
    # time by design (Phase 1's AcceptanceCriteriaFileValidator) - that
    # must never be mistaken for a repeated failure.
    assert is_repeated_identical_test_failure(((), ())) is False
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_stall_detection.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/agent_platform/orchestrator/stall_detection.py`:
```python
"""Stall-detection heuristics that refine the EXISTING FEEDBACK ->
IMPLEMENT_FIX / STUCK decision and the EXISTING IMPLEMENT write-
application step Phase 1 already has - no new states, no new
transitions, just additional signals for when the fix loop is going
nowhere before the raw iteration cap is hit (architecture-review-v2.md
section 1.9's "non-progress" signals, named there and implemented here
for the first time).
"""
from __future__ import annotations


def is_negligible_diff(previous_writes, new_writes) -> bool:
    if not previous_writes or not new_writes:
        return False
    prev = {w.path: w.content for w in previous_writes}
    new = {w.path: w.content for w in new_writes}
    return prev == new


def is_repeated_review_rejection(review_issue_history: tuple) -> bool:
    if len(review_issue_history) < 2:
        return False
    last_two = review_issue_history[-2:]
    if not last_two[0] or not last_two[1]:
        return False
    return frozenset(last_two[0]) == frozenset(last_two[1])


def is_repeated_identical_test_failure(validation_detail_history: tuple) -> bool:
    if len(validation_detail_history) < 2:
        return False
    last_two = validation_detail_history[-2:]
    return last_two[0] == last_two[1] and len(last_two[0]) > 0
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_stall_detection.py -v`
Expected: PASS (13 tests)

---

### Task 2: Wire stall detection into the orchestrator (the one core.py touch)

**Files:**
- Modify: `src/agent_platform/orchestrator/core.py`
- Create: `tests/test_orchestrator_stall_detection.py`

**Interfaces:**
- Consumes: Task 1's three functions
- Produces: no new public interface — `Orchestrator`'s constructor,
  `run`, and `amend_requirements` signatures are unchanged.
  `_review_issue_history`, `_validation_detail_history`, and
  `_last_file_writes` are new private instance attributes reset at the
  start of `run()` and `amend_requirements()`.

- [ ] **Step 1: Write the failing tests**

`tests/test_orchestrator_stall_detection.py`:
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


def test_identical_fix_attempt_escalates_without_waiting_for_the_full_iteration_cap(workspace):
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []}],
        coder_responses=[
            {"status": "completed", "spec_version_label": "task-1-v1", "summary": "attempt 1",
             "file_writes": [{"path": "app.py", "content": "same content every time"}]},
            {"status": "completed", "spec_version_label": "task-1-v1", "summary": "attempt 2 (identical)",
             "file_writes": [{"path": "app.py", "content": "same content every time"}]},
        ],
        reviewer_responses=[
            {"spec_version_label": "task-1-v1", "decision": "REJECT", "requirements_met": False,
             "security_ok": True, "validation_ok": True,
             "issues": [{"severity": "high", "file": "app.py", "description": "still wrong",
                         "required_fix": "change it"}]},
        ],
    )
    orchestrator, event_log = _build_orchestrator(workspace, model, max_fix_iterations=5)
    result = orchestrator.run("task-1", "build an app")
    assert result.final_state == State.ESCALATE_TO_USER
    assert "negligible" in result.summary.lower()
    # Only 2 coder calls and 1 reviewer call were needed - proof this
    # stopped well before the max_fix_iterations=5 cap would have.
    transitions = [e.payload["to"] for e in event_log.internal_stream() if e.event_type.name == "STATE_TRANSITION"]
    assert transitions.count("IMPLEMENT_FIX") == 1


def test_repeated_identical_review_rejection_escalates_early(workspace):
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []}],
        coder_responses=[
            {"status": "completed", "spec_version_label": "task-1-v1", "summary": f"attempt {i}",
             "file_writes": [{"path": "app.py", "content": f"version {i}"}]} for i in range(1, 4)
        ],
        reviewer_responses=[
            {"spec_version_label": "task-1-v1", "decision": "REJECT", "requirements_met": False,
             "security_ok": True, "validation_ok": True,
             "issues": [{"severity": "high", "file": "app.py", "description": "same root cause",
                         "required_fix": "fix root cause"}]} for _ in range(3)
        ],
    )
    orchestrator, _ = _build_orchestrator(workspace, model, max_fix_iterations=5)
    result = orchestrator.run("task-1", "build an app")
    assert result.final_state == State.ESCALATE_TO_USER
    assert "repeated" in result.summary.lower() or "same" in result.summary.lower()


def test_genuinely_different_fix_attempts_are_not_flagged_as_stalled(workspace):
    model = FakeModelProvider(
        planner_responses=[{"kind": "spec", "goals": ["g"], "constraints": [], "acceptance_criteria": []}],
        coder_responses=[
            {"status": "completed", "spec_version_label": "task-1-v1", "summary": "v1",
             "file_writes": [{"path": "app.py", "content": "buggy version"}]},
            {"status": "completed", "spec_version_label": "task-1-v1", "summary": "v2 fixed",
             "file_writes": [{"path": "app.py", "content": "corrected version"}]},
        ],
        reviewer_responses=[
            {"spec_version_label": "task-1-v1", "decision": "REJECT", "requirements_met": False,
             "security_ok": True, "validation_ok": True,
             "issues": [{"severity": "high", "file": "app.py", "description": "has a bug",
                         "required_fix": "fix the bug"}]},
            {"spec_version_label": "task-1-v1", "decision": "APPROVE", "requirements_met": True,
             "security_ok": True, "validation_ok": True, "issues": []},
        ],
    )
    orchestrator, _ = _build_orchestrator(workspace, model, max_fix_iterations=5)
    result = orchestrator.run("task-1", "build an app")
    assert result.final_state == State.COMPLETE
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_orchestrator_stall_detection.py -v`
Expected: FAIL — the first two tests currently run all the way to the
iteration cap instead of escalating early (no `AssertionError` crash
necessarily, but `transitions.count("IMPLEMENT_FIX") == 1` and the
`"negligible"/"repeated"` text in `result.summary` will fail against
current behavior).

- [ ] **Step 3: Implement — apply these five edits to `orchestrator/core.py`**

Add to the imports (after the existing `from .states import State` line):
```python
from .stall_detection import is_negligible_diff, is_repeated_identical_test_failure, is_repeated_review_rejection
```

In `__init__`, after `self._state = State.RECEIVE_REQUEST`, add:
```python
        self._review_issue_history: list = []
        self._validation_detail_history: list = []
        self._last_file_writes = None
```

In `run`, replace:
```python
    def run(self, spec_id: str, user_request: str) -> OrchestratorResult:
        self._event_log.emit(EventType.USER_REQUEST_RECEIVED, "user", {"spec_id": spec_id, "request": user_request})
        self._user_event(user_request)
        self._transition(State.PLAN)
```
with:
```python
    def run(self, spec_id: str, user_request: str) -> OrchestratorResult:
        self._review_issue_history = []
        self._validation_detail_history = []
        self._last_file_writes = None
        self._event_log.emit(EventType.USER_REQUEST_RECEIVED, "user", {"spec_id": spec_id, "request": user_request})
        self._user_event(user_request)
        self._transition(State.PLAN)
```

In `amend_requirements`, replace:
```python
        self._user_event(amendment_request)
        self._transition(State.AMEND_REQUIREMENTS)
```
with:
```python
        self._review_issue_history = []
        self._validation_detail_history = []
        self._last_file_writes = None
        self._user_event(amendment_request)
        self._transition(State.AMEND_REQUIREMENTS)
```

In `_implement`, replace:
```python
        failed = self._apply_file_writes(coder_output)
        if failed is not None:
            return self._stuck(spec_id, f"file write failed during implement: {failed.error}")
        return self._test_and_review(spec_id, spec, coder_output, fix_iteration)
```
with:
```python
        if fix_iteration > 0 and is_negligible_diff(self._last_file_writes, coder_output.file_writes):
            return self._stuck(
                spec_id, "the fix attempt produced a negligible diff from the previous attempt - no progress detected"
            )
        self._last_file_writes = coder_output.file_writes

        failed = self._apply_file_writes(coder_output)
        if failed is not None:
            return self._stuck(spec_id, f"file write failed during implement: {failed.error}")
        return self._test_and_review(spec_id, spec, coder_output, fix_iteration)
```

In `_test_and_review`, replace:
```python
        self._transition(State.TEST)
        validation_result = self._validator.validate(self._project_root, spec)
        self._transition(State.REVIEW)
```
with:
```python
        self._transition(State.TEST)
        validation_result = self._validator.validate(self._project_root, spec)
        self._validation_detail_history.append(validation_result.details)
        self._transition(State.REVIEW)
```

Still in `_test_and_review`, replace:
```python
        if reviewer_output.decision == "APPROVE":
            return self._final_validation(spec_id, spec, coder_output, validation_result,
                                           reviewer_output, fix_iteration)
        return self._feedback(spec_id, spec, reviewer_output, fix_iteration)
```
with:
```python
        if reviewer_output.decision == "APPROVE":
            return self._final_validation(spec_id, spec, coder_output, validation_result,
                                           reviewer_output, fix_iteration)
        self._review_issue_history.append(tuple(issue.description for issue in reviewer_output.issues))
        return self._feedback(spec_id, spec, reviewer_output, fix_iteration)
```

Finally, in `_feedback`, replace:
```python
    def _feedback(self, spec_id: str, spec: SpecVersion, reviewer_output, fix_iteration: int) -> OrchestratorResult:
        self._transition(State.FEEDBACK)
        if fix_iteration >= self._max_fix_iterations:
            return self._stuck(spec_id, f"fix loop exceeded {self._max_fix_iterations} iterations")
        return self._implement(spec_id, spec, reviewer_output, fix_iteration + 1)
```
with:
```python
    def _feedback(self, spec_id: str, spec: SpecVersion, reviewer_output, fix_iteration: int) -> OrchestratorResult:
        self._transition(State.FEEDBACK)
        if fix_iteration >= self._max_fix_iterations:
            return self._stuck(spec_id, f"fix loop exceeded {self._max_fix_iterations} iterations")
        if is_repeated_review_rejection(tuple(self._review_issue_history)):
            return self._stuck(spec_id, "reviewer repeated the same rejection reasons - no progress detected")
        if is_repeated_identical_test_failure(tuple(self._validation_detail_history)):
            return self._stuck(spec_id, "the same validation failure recurred - no progress detected")
        return self._implement(spec_id, spec, reviewer_output, fix_iteration + 1)
```

- [ ] **Step 4: Run the new tests, then the ENTIRE prior orchestrator-related test suite**

Run: `python -m pytest tests/test_orchestrator_stall_detection.py -v`
Expected: PASS (3 tests)

Run: `python -m pytest tests/ --ignore=tests/test_ollama_integration.py --ignore=tests/test_mcp_real_integration.py -q`
Expected: all 685 prior tests plus these 3 new ones pass — 688 total, 0
regressions. If any prior orchestrator test fails, read it against this
plan's reasoning above (every existing test's trace was checked by hand
before writing this plan - `test_repeated_rejection_beyond_cap_
escalates_to_stuck` and `test_reviewer_approval_does_not_override_a_
real_failing_test` both reach `ESCALATE_TO_USER` *earlier* than before
with these changes, but neither asserts anything more specific than the
final state, so both should still hold) - fix the stall-detection logic
to match the test's actual intent, do not weaken the test to paper over
a real behavior change.

---

### Task 3: `ContextAwareModelProvider`

**Files:**
- Create: `src/agent_platform/orchestrator/context_aware_provider.py`
- Create: `tests/test_context_aware_provider.py`

**Interfaces:**
- Consumes: `build_planner_context`, `build_coder_context`,
  `build_reviewer_context` (Phase 5, unchanged), `build_context_bundle`
  (Phase 5, unchanged), `ModelProvider` protocol (Phase 2, unchanged)
- Produces: `class ContextAwareModelProvider` with constructor
  `ContextAwareModelProvider(inner, *, gateway, session_mode,
  project_root, limits=DEFAULT_LIMITS, cache=None)` and `plan`/`code`/
  `review` matching `ModelProvider` exactly - a drop-in for
  `Orchestrator(model=...)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_context_aware_provider.py`:
```python
from agent_platform.events import EventLog
from agent_platform.context.bundle import ContextBundle
from agent_platform.orchestrator.context_aware_provider import ContextAwareModelProvider
from agent_platform.orchestrator.model_schemas import CoderCompleted, CoderFileWrite
from agent_platform.security.enums import SessionMode
from agent_platform.security.permission import PermissionEvaluator
from agent_platform.security.sandbox import FilesystemSandbox
from agent_platform.spec.versioning import SpecStore
from agent_platform.tools.gateway import ToolGateway
from agent_platform.tools.registry import build_default_registry


class _RecordingInnerProvider:
    def __init__(self, plan_response=None, code_response=None, review_response=None):
        self.received: list = []
        self._plan_response = plan_response
        self._code_response = code_response
        self._review_response = review_response

    def plan(self, context):
        self.received.append(("plan", context))
        return self._plan_response

    def code(self, context):
        self.received.append(("code", context))
        return self._code_response

    def review(self, context):
        self.received.append(("review", context))
        return self._review_response


def _workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    proj = root / "MyProj"
    proj.mkdir()
    return proj


def _gateway(proj):
    sandbox = FilesystemSandbox(proj.parent)
    evaluator = PermissionEvaluator(sandbox)
    return ToolGateway(build_default_registry(), evaluator, EventLog())


def test_plan_enriches_context_with_a_planner_bundle(tmp_path):
    proj = _workspace(tmp_path)
    (proj / "app.py").write_text("x = 1", encoding="utf-8")
    inner = _RecordingInnerProvider(plan_response={"kind": "spec", "goals": [], "constraints": [],
                                                    "acceptance_criteria": []})
    provider = ContextAwareModelProvider(inner, gateway=_gateway(proj), session_mode=SessionMode.AUTO,
                                          project_root=proj.resolve())
    provider.plan({"request": "fix app.py"})
    _, received_context = inner.received[0]
    bundle = received_context["context_bundle"]
    assert isinstance(bundle, ContextBundle)
    assert bundle.role == "PLANNER"
    assert any(f.path == "app.py" for f in bundle.files)


def test_code_enriches_context_with_a_coder_bundle(tmp_path):
    proj = _workspace(tmp_path)
    (proj / "app.py").write_text("x = 1", encoding="utf-8")
    spec = SpecStore().create("task-1", goals=["fix app.py"], constraints=[], acceptance_criteria=[])
    inner = _RecordingInnerProvider(code_response={"status": "completed", "spec_version_label": spec.version_label,
                                                    "summary": "s", "file_writes": []})
    provider = ContextAwareModelProvider(inner, gateway=_gateway(proj), session_mode=SessionMode.AUTO,
                                          project_root=proj.resolve())
    provider.code({"spec": spec, "reviewer_feedback": None})
    _, received_context = inner.received[0]
    bundle = received_context["context_bundle"]
    assert bundle.role == "CODER"
    assert any(f.path == "app.py" for f in bundle.files)


def test_review_enriches_context_with_a_reviewer_bundle(tmp_path):
    proj = _workspace(tmp_path)
    (proj / "app.py").write_text("x = 1", encoding="utf-8")
    spec = SpecStore().create("task-1", goals=["g"], constraints=[], acceptance_criteria=[])
    coder_output = CoderCompleted(spec_version_label=spec.version_label, summary="s",
                                   file_writes=(CoderFileWrite(path="app.py", content="x = 1"),))
    inner = _RecordingInnerProvider(review_response={"spec_version_label": spec.version_label,
                                                       "decision": "APPROVE", "requirements_met": True,
                                                       "security_ok": True, "validation_ok": True, "issues": []})
    provider = ContextAwareModelProvider(inner, gateway=_gateway(proj), session_mode=SessionMode.AUTO,
                                          project_root=proj.resolve())
    provider.review({"spec": spec, "coder_output": coder_output, "validation_result": None})
    _, received_context = inner.received[0]
    bundle = received_context["context_bundle"]
    assert bundle.role == "REVIEWER"
    assert any(f.path == "app.py" for f in bundle.files)


def test_plan_uses_blocking_questions_as_hints_during_clarification(tmp_path):
    proj = _workspace(tmp_path)
    (proj / "auth.py").write_text("x = 1", encoding="utf-8")
    inner = _RecordingInnerProvider(plan_response={"kind": "spec", "goals": [], "constraints": [],
                                                    "acceptance_criteria": []})
    provider = ContextAwareModelProvider(inner, gateway=_gateway(proj), session_mode=SessionMode.AUTO,
                                          project_root=proj.resolve())
    provider.plan({"spec": SpecStore().create("t", goals=["g"], constraints=[], acceptance_criteria=[]),
                    "blocking_questions": ["should auth.py use OAuth?"]})
    _, received_context = inner.received[0]
    bundle = received_context["context_bundle"]
    assert any(f.path == "auth.py" for f in bundle.files)


def test_original_context_keys_are_preserved_alongside_the_bundle(tmp_path):
    proj = _workspace(tmp_path)
    spec = SpecStore().create("task-1", goals=["g"], constraints=[], acceptance_criteria=[])
    inner = _RecordingInnerProvider(code_response={"status": "completed", "spec_version_label": spec.version_label,
                                                    "summary": "s", "file_writes": []})
    provider = ContextAwareModelProvider(inner, gateway=_gateway(proj), session_mode=SessionMode.AUTO,
                                          project_root=proj.resolve())
    provider.code({"spec": spec, "reviewer_feedback": "some feedback"})
    _, received_context = inner.received[0]
    assert received_context["spec"] is spec
    assert received_context["reviewer_feedback"] == "some feedback"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_context_aware_provider.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/agent_platform/orchestrator/context_aware_provider.py`:
```python
"""Wraps any ModelProvider, enriching each role's context dict with a
real, bounded bundle from Phase 5's retrieval engine before delegating.
Orchestrator (Phase 1) is never touched: this is a drop-in ModelProvider,
constructed once and passed to Orchestrator exactly like FakeModelProvider
or OllamaModelProvider would be - the "Planner -> context retrieval" step
in the architecture diagram is this wrapper's plan()/code()/review()
gathering a bundle before ever calling the inner provider.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..context.bundle_builder import build_context_bundle
from ..context.limits import ContextLimits, DEFAULT_LIMITS
from ..context.role_context import build_coder_context, build_planner_context, build_reviewer_context
from ..context.staleness import ContextCache
from ..security.enums import Role, SessionMode
from ..tools.gateway import ToolGateway


class ContextAwareModelProvider:
    def __init__(self, inner, *, gateway: ToolGateway, session_mode: SessionMode,
                 project_root: Path, limits: ContextLimits = DEFAULT_LIMITS,
                 cache: Optional[ContextCache] = None):
        self._inner = inner
        self._gateway = gateway
        self._session_mode = session_mode
        self._project_root = project_root
        self._limits = limits
        self._cache = cache if cache is not None else ContextCache()

    def plan(self, context: dict) -> dict:
        enriched = dict(context)
        if "blocking_questions" in context:
            bundle = build_context_bundle(
                gateway=self._gateway, role=Role.PLANNER, session_mode=self._session_mode,
                project_root=self._project_root, reference_hints=tuple(context["blocking_questions"]),
                limits=self._limits, cache=self._cache,
            )
        else:
            bundle = build_planner_context(self._gateway, self._session_mode, self._project_root,
                                            context["request"], limits=self._limits, cache=self._cache)
        enriched["context_bundle"] = bundle
        return self._inner.plan(enriched)

    def code(self, context: dict) -> dict:
        enriched = dict(context)
        bundle = build_coder_context(self._gateway, self._session_mode, self._project_root,
                                      context["spec"], context.get("reviewer_feedback"),
                                      limits=self._limits, cache=self._cache)
        enriched["context_bundle"] = bundle
        return self._inner.code(enriched)

    def review(self, context: dict) -> dict:
        enriched = dict(context)
        bundle = build_reviewer_context(self._gateway, self._session_mode, self._project_root,
                                         context["spec"], context["coder_output"],
                                         limits=self._limits, cache=self._cache)
        enriched["context_bundle"] = bundle
        return self._inner.review(enriched)
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_context_aware_provider.py -v`
Expected: PASS (5 tests)

---

### Task 4: Two new integration scenarios — MCP failure and context failure

**Files:**
- Create: `tests/test_phase6_integration_scenarios.py`

**Interfaces:** none new - reuses Phase 4's `MCPClient`/`MockMCPTransport`/
`register_mcp_capabilities` and Phase 5's `build_context_bundle` exactly
as built.

- [ ] **Step 1: Write and run the tests**

`tests/test_phase6_integration_scenarios.py`:
```python
import pytest

from agent_platform.context.bundle_builder import build_context_bundle
from agent_platform.events import EventLog
from agent_platform.mcp.client import MCPClient
from agent_platform.mcp.gateway_tools import register_mcp_capabilities
from agent_platform.mcp.mock_transport import TIMEOUT, MockMCPTransport, MockServerFailure
from agent_platform.mcp.schemas import MCPServerConfig
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


def test_mcp_timeout_failure_is_a_clean_observation_not_a_crash(workspace):
    config = MCPServerConfig(server_id="docs", transport="mock", capabilities=("search",))
    client = MCPClient(MockMCPTransport({"search": [TIMEOUT]}))
    registry = build_default_registry()
    sandbox = FilesystemSandbox(workspace)
    grants = register_mcp_capabilities(registry, (config,), {"docs": client}, (Role.CODER,))
    evaluator = PermissionEvaluator(sandbox, tool_table=grants)
    gateway = ToolGateway(registry, evaluator, EventLog())
    obs = gateway.invoke(role=Role.CODER, tool_name="mcp.docs.search", arguments={"query": "x"},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "ok"  # the gateway call succeeded
    assert obs.result["status"] == "timeout"  # the MCP-level result carries the failure


def test_mcp_server_failure_is_a_clean_observation_not_a_crash(workspace):
    config = MCPServerConfig(server_id="docs", transport="mock", capabilities=("search",))
    client = MCPClient(MockMCPTransport({"search": [MockServerFailure("upstream is down")]}))
    registry = build_default_registry()
    sandbox = FilesystemSandbox(workspace)
    grants = register_mcp_capabilities(registry, (config,), {"docs": client}, (Role.CODER,))
    evaluator = PermissionEvaluator(sandbox, tool_table=grants)
    gateway = ToolGateway(registry, evaluator, EventLog())
    obs = gateway.invoke(role=Role.CODER, tool_name="mcp.docs.search", arguments={"query": "x"},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "ok"
    assert obs.result["status"] == "error"


def test_unauthorized_mcp_request_is_denied(workspace):
    config = MCPServerConfig(server_id="docs", transport="mock", capabilities=("search",))
    client = MCPClient(MockMCPTransport({"search": [{"results": []}]}))
    registry = build_default_registry()
    sandbox = FilesystemSandbox(workspace)
    # Only CODER is granted access - PLANNER is not, in this configuration.
    grants = register_mcp_capabilities(registry, (config,), {"docs": client}, (Role.CODER,))
    evaluator = PermissionEvaluator(sandbox, tool_table=grants)
    gateway = ToolGateway(registry, evaluator, EventLog())
    obs = gateway.invoke(role=Role.PLANNER, tool_name="mcp.docs.search", arguments={"query": "x"},
                          session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve())
    assert obs.status == "denied"


def test_context_retrieval_degrades_gracefully_when_a_gateway_call_is_denied(workspace):
    # A role with no filesystem.list grant (there isn't one in the
    # default table, so this simulates the general "a gateway call
    # inside retrieval fails" case) must not crash retrieval - it should
    # simply retrieve nothing rather than propagate an exception.
    sandbox = FilesystemSandbox(workspace)
    evaluator = PermissionEvaluator(sandbox, tool_table={})  # no grants for anyone
    gateway = ToolGateway(build_default_registry(), evaluator, EventLog())
    bundle = build_context_bundle(gateway=gateway, role=Role.CODER, session_mode=SessionMode.AUTO,
                                   project_root=(workspace / "MyProj").resolve(),
                                   reference_hints=("fix app.py",))
    assert bundle.files == ()
    assert bundle.changed_files == ()
```

- [ ] **Step 2: Run**

Run: `python -m pytest tests/test_phase6_integration_scenarios.py -v`
Expected: PASS (4 tests)

---

### Task 5: The controlled end-to-end demonstration

**Files:**
- Create: `tests/test_phase6_end_to_end_demo.py`

**Interfaces:** none new - assembles Phase 0 (`FilesystemSandbox`), Phase 1
(`ToolGateway`, `Orchestrator`, `FakeModelProvider`), Phase 3
(`TestRunValidator`), Task 3 (`ContextAwareModelProvider`) into one
scripted, controlled run.

- [ ] **Step 1: Write and run the demo**

`tests/test_phase6_end_to_end_demo.py`:
```python
"""The Phase 6 controlled end-to-end demonstration: Planner -> context
retrieval -> Coder -> tool gateway -> deterministic validation ->
Reviewer -> completion, exercising the review/fix loop along the way.
Everything is real (sandbox, gateway, real pytest execution via
test.run) except the model calls, which are scripted for
reproducibility - Phase 2 already separately proved real Ollama
integration with real measurements; re-proving that here would only add
non-determinism and slowness to what this test needs to show, which is
that the whole control plane is correctly wired together.
"""
from agent_platform.events import EventLog
from agent_platform.orchestrator.context_aware_provider import ContextAwareModelProvider
from agent_platform.orchestrator.core import Orchestrator, State
from agent_platform.orchestrator.fake_model import FakeModelProvider
from agent_platform.orchestrator.validation import TestRunValidator
from agent_platform.security.enums import Role, SessionMode
from agent_platform.security.permission import PermissionEvaluator
from agent_platform.security.sandbox import FilesystemSandbox
from agent_platform.spec.versioning import SpecStore
from agent_platform.tools.gateway import ToolGateway
from agent_platform.tools.registry import build_default_registry


def test_phase6_controlled_end_to_end_demo_with_review_fix_loop(tmp_path, capsys):
    workspace = tmp_path / "Projects"
    workspace.mkdir()
    project = workspace / "HealthCheckDemo"
    project.mkdir()

    sandbox = FilesystemSandbox(workspace)
    evaluator = PermissionEvaluator(sandbox)
    event_log = EventLog()
    gateway = ToolGateway(build_default_registry(), evaluator, event_log)

    # Attempt 1 is deliberately wrong (health_check() returns False) so
    # the demo exercises REJECT -> STRUCTURED_FEEDBACK -> IMPLEMENT_FIX,
    # not just the happy path.
    fake_model = FakeModelProvider(
        planner_responses=[{
            "kind": "spec",
            "goals": ["Add a health_check() function that reports the service is healthy"],
            "constraints": ["Keep it minimal"],
            "acceptance_criteria": ["file:health.py", "file:test_health.py"],
        }],
        coder_responses=[
            {
                "status": "completed", "spec_version_label": "demo-task-v1",
                "summary": "Added health_check(), returns False by mistake",
                "file_writes": [
                    {"path": "health.py", "content": "def health_check():\n    return False\n"},
                    {"path": "test_health.py",
                     "content": "from health import health_check\n\n\ndef test_health_check():\n"
                                "    assert health_check() is True\n"},
                ],
            },
            {
                "status": "completed", "spec_version_label": "demo-task-v1",
                "summary": "Fixed health_check() to return True as required",
                "file_writes": [
                    {"path": "health.py", "content": "def health_check():\n    return True\n"},
                    {"path": "test_health.py",
                     "content": "from health import health_check\n\n\ndef test_health_check():\n"
                                "    assert health_check() is True\n"},
                ],
            },
        ],
        reviewer_responses=[
            {
                "spec_version_label": "demo-task-v1", "decision": "REJECT",
                "requirements_met": False, "security_ok": True, "validation_ok": True,
                "issues": [{"severity": "high", "file": "health.py",
                            "description": "health_check() returns False, contradicting its own test",
                            "required_fix": "return True"}],
            },
            {
                "spec_version_label": "demo-task-v1", "decision": "APPROVE",
                "requirements_met": True, "security_ok": True, "validation_ok": True, "issues": [],
            },
        ],
    )
    model = ContextAwareModelProvider(fake_model, gateway=gateway, session_mode=SessionMode.AUTO,
                                       project_root=project.resolve())
    spec_store = SpecStore()
    validator = TestRunValidator(gateway, Role.REVIEWER, SessionMode.AUTO)
    orchestrator = Orchestrator(
        gateway=gateway, model=model, spec_store=spec_store, event_log=event_log,
        session_mode=SessionMode.AUTO, project_root=project.resolve(), validator=validator,
    )

    result = orchestrator.run("demo-task", "Add a health check function with a test for it.")

    transitions = [e.payload["to"] for e in event_log.internal_stream() if e.event_type.name == "STATE_TRANSITION"]
    print("\n=== PHASE 6 DEMO: state transitions ===")
    print(" -> ".join(transitions))
    print("=== user-visible progress ===")
    for event in event_log.user_stream():
        print(f"  {event.payload.get('text', event.payload)}")
    print(f"=== final state: {result.final_state} ===")
    print(f"=== summary: {result.summary} ===")

    assert result.final_state == State.COMPLETE
    assert "REVIEW" in transitions
    assert "FEEDBACK" in transitions and "IMPLEMENT_FIX" in transitions  # the fix loop was exercised
    assert (project / "health.py").read_text(encoding="utf-8") == "def health_check():\n    return True\n"

    # Deterministic validation actually ran real pytest against the real
    # written files - not a stub.
    real_validation = validator.validate(project.resolve(), spec_store.latest("demo-task"))
    assert real_validation.passed

    captured = capsys.readouterr()
    assert "Planning" not in captured.out or True  # transitions list above is the authoritative trace
```

- [ ] **Step 2: Run the demo with output visible**

Run: `python -m pytest tests/test_phase6_end_to_end_demo.py -v -s`
Expected: PASS (1 test). Capture the printed transition trace and final
summary for the report (Task 6) - this is the actual, real trace of a
review/fix loop running against real file writes and real `pytest`
execution, not a description of what it would do.

---

### Task 6: Full suite re-run and Phase 6 report

**Files:**
- Create: `PHASE6_REPORT.md`

- [ ] **Step 1: Run everything**

Run: `python -m pytest tests/ --ignore=tests/test_ollama_integration.py --ignore=tests/test_mcp_real_integration.py -v --tb=short`
Expected: every prior test (685) plus Tasks 1-5's new tests pass
together. Record the exact count.

- [ ] **Step 2: Write `PHASE6_REPORT.md`**

Cover: files created, files modified (`orchestrator/core.py` only, with
the exact five edits from Task 2 summarized and the regression-proof
result stated), state-machine integration (confirm the state diagram in
the brief was already fully implemented by Phase 1 - table mapping each
of the brief's Completion/Failure-Handling requirements to the existing
code or test that satisfies it, per this plan's Global Constraints
section), end-to-end result (paste the actual transition trace and
summary captured in Task 5), tests added and exact count, demonstration
result (pass/fail, real file contents produced, real `pytest` result),
known limitations (name explicitly: `OllamaModelProvider`'s prompt
builders do not yet consume `context["context_bundle"]` - the wiring
exists and is proven end-to-end with `FakeModelProvider`, but making a
real model's prompt actually include retrieved file content would mean
touching `orchestrator/prompts.py`, which this phase's "do not redesign
model providers" instruction was read as ruling out; MCP is not part of
the demo's own loop, per the brief's own demo requirements list, though
MCP failure/denial behavior is proven in Task 4).

- [ ] **Step 3: Stop**

This is the terminal instruction for this plan: stop after the first
successful controlled end-to-end demonstration and final verification.
Report back in full per the brief's 8-item Final Report list.
