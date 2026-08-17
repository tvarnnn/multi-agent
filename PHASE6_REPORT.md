# Phase 6 Report

## Files created

- `src/agent_platform/orchestrator/stall_detection.py` — `is_negligible_diff`, `is_repeated_review_rejection`, `is_repeated_identical_test_failure`
- `src/agent_platform/orchestrator/context_aware_provider.py` — `ContextAwareModelProvider`
- `tests/test_stall_detection.py`, `test_orchestrator_stall_detection.py`, `test_context_aware_provider.py`, `test_phase6_integration_scenarios.py`, `test_phase6_end_to_end_demo.py`

## Files modified

**One file, five edits:** `src/agent_platform/orchestrator/core.py`.
Nothing else from Phase 0-5 was touched.

1. One new import (`stall_detection`'s three functions).
2. Three new instance attributes in `__init__`
   (`_review_issue_history`, `_validation_detail_history`,
   `_last_file_writes`), reset at the start of both `run()` and
   `amend_requirements()`.
3. `_implement`: one new check before applying a fix attempt's writes —
   if the diff from the previous attempt is negligible, escalate
   immediately instead of writing and re-testing.
4. `_test_and_review`: two new one-line history appends — validation
   details (always) and reviewer issue descriptions (on REJECT only).
5. `_feedback`: two new early-exit checks alongside the existing
   iteration-count check.

No state was added, no transition was added, and no existing transition
was removed — every existing edge in the state graph (`FEEDBACK →
IMPLEMENT_FIX`, `FEEDBACK → STUCK`) is exactly where it was; only the
*condition* for taking the `STUCK` edge gained two more inputs.

**Regression proof:** the full prior suite (701 tests through Task 2, 685
tests through Phase 5) passed unchanged after this edit. Two existing
tests were hand-traced before writing the plan and confirmed to still
pass by reaching `ESCALATE_TO_USER` via the *new*, earlier path instead
of the old iteration-cap path — neither asserts anything more specific
than final state, so both held:
`test_repeated_rejection_beyond_cap_escalates_to_stuck` (Phase 1) and
`test_reviewer_approval_does_not_override_a_real_failing_test` (Phase 3).
The empirical run confirmed the trace: 0 failures.

## State-machine integration

The brief's state diagram, rejection loop, blocked loop, and completion
checklist were **already fully implemented by Phase 1** — this table
maps each requirement to what already satisfies it:

| Requirement | Satisfied by |
|---|---|
| `RECEIVE_REQUEST → PLAN → VALIDATE_PLAN → IMPLEMENT → TEST → REVIEW → FINAL_VALIDATION → COMPLETE` | `Orchestrator.run`/`_after_plan`/`_validate_plan`/`_implement`/`_test_and_review`/`_final_validation` (Phase 1) |
| Models recommend, orchestrator decides | Every transition is schema-validated-output-driven, not prose-parsed (Phase 1) |
| `REVIEW → REJECT → STRUCTURED_FEEDBACK → IMPLEMENT_FIX → TEST → REVIEW` | `_test_and_review`/`_feedback`/`_implement` (Phase 1) |
| Reviewer never modifies files | Reviewer role has no `filesystem.write` grant (Phase 0 permission table) |
| `IMPLEMENT → BLOCKED → RESOLVE_CLARIFICATION`, resolution order (context → inspection → MCP → user) | `_blocked`/`_resolve_clarification` (Phase 1); MCP research tools available to Planner (Phase 4) |
| `AWAITING_USER_INPUT → USER → PLANNER → NEW SPECIFICATION → VALIDATE_PLAN → IMPLEMENT` | Same methods; `amend_requirements` (Phase 1) |
| Coder never communicates with the user | `CoderCompleted`/`CoderBlocked` schemas have no user-facing field (Phase 1) |
| Requirements immutable within an attempt; new version per genuine change | `SpecStore` append-only, frozen `SpecVersion` (Phase 0) |
| Every operation identifies the active spec; stale specs rejected deterministically | `SpecStore.assert_current`, checked in `_implement` and `_test_and_review` before any write or gate (Phase 1) |
| Completion requires requirements/validation/approval/security/spec-consistency/no-unauthorized-paths/no-unresolved-clarification/no-unresolved-failure | `_final_validation`'s `gates_pass` AND-condition (Phase 1) + Phase 0 sandbox (structural "no unauthorized paths") + state graph shape (structural "no unresolved clarification/failure" — those states never reach `FINAL_VALIDATION`) |
| Reviewer approval alone never sufficient | Same `gates_pass` AND — proven with a real failing test in Phase 3 |
| Iteration/retry/clarification limits, tool/model timeouts | `max_fix_iterations`/`max_output_retries`/`max_clarification_rounds` (Phase 1), `run_process` timeout (Phase 3), `ModelTimeoutError` handling (Phase 1/2) |
| Repeated-review / negligible-diff / repeated-identical-failure detection | **New this phase** — Tasks 1-2 |
| `STUCK` and `AWAITING_USER_INPUT` distinct | Distinct states since Phase 1, re-confirmed: this phase's new checks route only to `STUCK`, never touch `AWAITING_USER_INPUT` |
| User-visible progress without private reasoning | `EventLog.user_stream()` carries only user-facing text (Phase 1); demo output below shows exactly this |
| Agent never commits/pushes/resets/rebases/merges/rewrites history | `ABSOLUTE_DENY_TOOLS` (Phase 0), unconditional, unchanged |

## End-to-end result

Real transition trace from the controlled demo (Task 5), a health-check
module with a deliberately broken first attempt to exercise the fix loop:

```
PLAN -> VALIDATE_PLAN -> IMPLEMENT -> TEST -> REVIEW -> FEEDBACK ->
IMPLEMENT_FIX -> TEST -> REVIEW -> FINAL_VALIDATION -> COMPLETE
```

User-visible stream (exactly what `EventLog.user_stream()` carries — no
internal reasoning, no model names):
```
Add a health check function with a test for it.
Fixed health_check() to return True as required
```

`health.py` on disk after the run: `def health_check():\n    return True\n`
— the corrected version, real file, real write, real gateway. A second,
independent call to `TestRunValidator.validate(...)` after the run
(spawning real `pytest` against the real written files) confirms
`passed: True`.

## Tests added

26 new tests across 5 files:
- `test_stall_detection.py` — 13 (pure-function unit tests)
- `test_orchestrator_stall_detection.py` — 3 (orchestrator-level: early
  escalation on negligible diff, early escalation on repeated identical
  rejection, confirmation that genuinely different attempts are never
  falsely flagged)
- `test_context_aware_provider.py` — 5
- `test_phase6_integration_scenarios.py` — 4 (MCP timeout, MCP server
  failure, unauthorized MCP request, context-retrieval graceful
  degradation)
- `test_phase6_end_to_end_demo.py` — 1

Two real bugs were found and fixed **in the tests, not the production
code**, during this phase — consistent with every prior phase's TDD
discipline: a `reviewer_feedback` test value that didn't match the real
`ReviewerOutput` shape any real caller would pass, and an overly strict
"empty bundle" assertion that didn't account for the (correct) empty
tree-listing fallback the engine already produces when nothing is
discoverable.

## Exact test count

**711 passed, 0 failed, 0 skipped**
(`python -m pytest tests/ --ignore=tests/test_ollama_integration.py
--ignore=tests/test_mcp_real_integration.py -q`) — 685 from Phase 0-5
plus these 26, zero regressions.

## Demonstration result

**Pass.** One controlled, fully reproducible run exercised Planner →
context retrieval → Coder → tool gateway (real sandboxed writes) →
deterministic validation (real `pytest` via `TestRunValidator`) →
Reviewer → the review/fix loop → `COMPLETE`, using only existing
capabilities (`FakeModelProvider`, `ContextAwareModelProvider`,
`ToolGateway`, `TestRunValidator`, `FilesystemSandbox`, `Orchestrator` —
nothing built solely for the demo).

## Known limitations

- `OllamaModelProvider`'s prompt builders (Phase 2) do not yet consume
  `context["context_bundle"]`. The wiring is real and proven end-to-end
  (Task 3's tests confirm each role receives the right bundle; the demo
  confirms it flows correctly through a live orchestrator run) — but
  making a *real* model's prompt actually include retrieved file content
  would mean touching `orchestrator/prompts.py`, which this phase's "do
  not redesign model providers" instruction was read as ruling out. This
  is a real, named gap: context retrieval is fully wired and available,
  but not yet consumed by the one provider that talks to a real LLM.
- MCP is not part of the demo's own loop, matching the brief's own demo
  requirements list (Planner → context retrieval → Coder → tool gateway →
  validation → Reviewer → completion — MCP isn't named there). MCP
  failure/denial behavior is proven independently in Task 4, reusing
  Phase 4's exact machinery.
- The stall-detection thresholds are binary (exact match / no match),
  not fuzzy — a fix attempt that changes only whitespace, or a review
  rejection that rephrases the same underlying issue differently, will
  not be caught by `is_negligible_diff`/`is_repeated_review_rejection` as
  written. This is a deliberate simplicity choice (deterministic, no
  false positives from approximate matching) rather than an oversight;
  a future phase could make these fuzzier if empirical use shows the
  exact-match version misses real stalls too often.
- No git commands were run this session. All of Phase 0 through Phase 6
  remains uncommitted, entirely the user's to review and commit.
