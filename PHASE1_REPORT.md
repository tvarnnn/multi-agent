# Phase 1 Report

## Implemented
- **Structured event system** (`events.py`) — append-only log with a
  `stream` field (`"user"` | `"internal"`) implementing V3's separation
  between the single user-facing conversation and the internal execution
  trace, on one correlatable log rather than two.
- **Model output schemas** (`orchestrator/model_schemas.py`) — strict
  parse functions for Planner (`spec` | `needs_user_input`), Coder
  (`completed` | `blocked`), and Reviewer output. Unconstrained model
  prose never reaches the state machine; every dict is validated or
  rejected with `SchemaValidationError`.
- **Fake model provider** (`orchestrator/fake_model.py`) — scriptable,
  per-role response queues, a `TIMEOUT` sentinel, and a distinct
  `ModelExhaustedError` for incomplete test scripts vs. `ModelTimeoutError`
  for a simulated real timeout.
- **Typed tool registry** (`tools/registry.py`, `tools/schemas.py`) —
  `filesystem.read/write/create_directory/list` and read-only
  `git.status/diff/log/branch`, the last four toplevel-scope-verified so a
  project without its own repo never leaks an enclosing repo's status
  (the stray-outer-repo hazard from `architecture-review-v4`).
- **Permission gateway** (`tools/gateway.py`) — the fixed 6-step pipeline
  (schema → permission → precondition → execute → observation → log) is
  the only path from a tool request to execution, for every role alike,
  built directly on Phase 0's real `FilesystemSandbox` and
  `PermissionEvaluator`.
- **Deterministic validator** (`orchestrator/validation.py`) —
  `file:<path>` acceptance criteria are a real, working existence gate;
  everything else is honestly labeled advisory rather than silently
  passed.
- **Orchestrator state machine** (`orchestrator/states.py`,
  `orchestrator/core.py`) — the full 16-state lifecycle: happy path
  (PLAN→VALIDATE_PLAN→IMPLEMENT→TEST→REVIEW→FINAL_VALIDATION→COMPLETE),
  the coder-blocked/clarification loop (BLOCKED→RESOLVE_CLARIFICATION,
  capped), the reviewer fix loop (FEEDBACK→IMPLEMENT_FIX, capped),
  AWAITING_USER_INPUT and STUCK kept as distinct states, and
  `amend_requirements` as an explicit entry point for user-initiated
  requirement changes.
- **Configuration** (`config.py`, extended) — `PlatformConfig` now also
  carries `session_mode` and the three iteration caps, validated once at
  load time, never derived from model output.

## Test results
**541 passed, 0 failed, 0 skipped** — the full combined Phase 0 + Phase 1
suite in one run (`python -m pytest tests/ -v`), confirming Phase 1 didn't
regress Phase 0 (Phase 0's original 451 plus 2 field-proving additions to
`test_permission.py` = 453, plus 88 new Phase 1 tests = 541). No network
access anywhere — confirmed by grepping all `.py` source for
`requests`/`httpx`/`ollama`/`urllib.request`/`socket.`: zero matches (one
false-positive hit on a compiled `.pyc` byte sequence, excluded by
restricting the grep to `--include="*.py"`).

Breakdown of new Phase 1 tests by file:
- `test_events.py` — 6
- `test_model_schemas.py` — 28
- `test_fake_model.py` — 5
- `test_tools_registry.py` — 12
- `test_gateway.py` — 10
- `test_validation.py` — 5
- `test_orchestrator_happy_path.py` — 4
- `test_orchestrator_clarification.py` — 12
- `test_config.py` additions — 6
- `test_permission.py` additions (Task 0) — 2

One real bug was found and fixed during this run, in the orchestrator
itself: `clarification_round` was being reset to `0` every time `_blocked`
was re-entered from a fresh `_implement` call, so the clarification-round
cap never actually accumulated — a repeatedly-blocking coder just kept
looping until the fake model's scripted response queues ran out, raising
an unhandled `ModelExhaustedError` instead of reaching `STUCK` as designed.
`test_repeated_blocking_beyond_cap_escalates_to_stuck` caught this
immediately. Fixed by threading `clarification_round` through
`_implement`'s signature so a continuing clarification chain keeps its
count, while a genuinely fresh implement attempt (from `VALIDATE_PLAN` or
a new `FEEDBACK`/`IMPLEMENT_FIX` cycle) still starts its own budget at 0 —
each fix attempt gets its own clarification-round allowance, which is a
deliberate, defensible scoping choice, not an oversight.

## Security / determinism invariants enforced and tested
- The gateway's 6-step pipeline is the only path to tool execution for
  Planner, Coder, and Reviewer alike — proven end-to-end through the real
  Phase 0 sandbox and permission evaluator, not a mock.
- All git write operations (`init`/`add`/`commit`/`push`/`reset`/`rebase`)
  and `shell.run` are rejected at the gateway regardless of registration —
  tested both as unregistered tools (no handler exists) and, independently,
  via Phase 0's `ABSOLUTE_DENY_TOOLS` permission check, so removing a
  handler alone was never the only defense.
- Read-only git tools refuse to report status/diff/log/branch from an
  enclosing repo — `git.status` on a project with no `.git` of its own
  reports `{"scoped": False}` rather than silently walking up to a parent
  repository.
- Every Coder and Reviewer invocation is pinned to an exact specification
  version; a stale reference is deterministically rejected via Phase 0's
  `SpecStore.assert_current`, routing straight to `ESCALATE_TO_USER` rather
  than being silently honored — tested for both roles independently.
- `FINAL_VALIDATION` requires the deterministic gate to pass **and** the
  reviewer to approve — reviewer approval alone does not reach `COMPLETE`
  if the acceptance-criteria file check fails.
- Malformed model output and simulated model timeouts are both bounded-
  retried then escalated, never allowed to drive a state transition
  unvalidated.
- A tool failure during implementation (a Coder attempting to write
  outside the project scope) is caught by the real sandbox and routes to
  `ESCALATE_TO_USER` — the file was never created outside the workspace.
- `AWAITING_USER_INPUT` (routine) and `STUCK`→`ESCALATE_TO_USER` (abnormal)
  are verified as genuinely distinct code paths with distinct triggers,
  not two names for the same branch.
- The user-facing event stream and the internal execution trace stay
  separated in the same log — no `STATE_TRANSITION` or `TOOL_INVOKED`
  event ever appears on the `"user"` stream.

## Scope decisions made explicit
- `AMEND_REQUIREMENTS` is an explicit orchestrator method
  (`amend_requirements`), not a live mid-session interrupt — Phase 1
  builds the deterministic control plane, not an interactive session loop.
  Fully state-machine-tested; a later phase's real session would call it
  from an incoming-message classifier instead of a direct method call, with
  no change to the state transitions themselves.
- Deterministic validation is scoped to `file:<path>` existence checks —
  Phase 1's own tool list has no `test.run`/`lint.run`/`typecheck.run`, so
  none were built; running arbitrary generated code is out of scope until
  a phase that actually needs it.
- The gateway's `"requires_confirmation"` status is implemented and unit-
  tested at the gateway level, but no interactive confirmation UI/resume
  flow exists yet — CONFIRMATION/MANUAL session modes correctly produce
  the status and block execution, but resuming after a human confirms is
  a session/UX concern for a later phase.

## Remaining concerns
- None observed as flaky across repeated runs in this session.
- The `_invoke_with_retry` bounded-retry loop treats a timeout and a
  schema-validation failure identically (both consume one retry from the
  same budget) — a deliberate simplification per `architecture-review-v2`
  §1.11's "bounded retry then escalate" policy, not distinguished further
  in Phase 1.
- This session ran no git commands, per the standing instruction — the
  working tree (Phase 0 and Phase 1 combined) is entirely uncommitted and
  left for the user to review.
