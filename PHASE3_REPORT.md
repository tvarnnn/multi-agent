# Phase 3 Report

## Implemented

- A secure process-execution primitive, `run_process`, for validation tools, with argv-list execution, a minimal child environment, hard wall-clock timeouts, full process-tree termination, and bounded output capture.
- Typed `test.run`, `lint.run`, and `typecheck.run` tools with fixed executables, bounded timeouts, sandbox-validated optional targets, gateway integration, and Coder/Reviewer permissions while Planner remains denied.
- `TestRunValidator`, which executes the project's real pytest suite through `test.run` and returns deterministic validation results.
- `CompositeValidator`, which requires every constituent validator to pass and concatenates all validation details.
- End-to-end orchestration coverage proving that reviewer approval cannot override a real deterministic test failure, without modifying `orchestrator/core.py`.

## Test results

- Command: `python -m pytest tests/ --ignore=tests/test_ollama_integration.py -v --tb=short`
- Result: **600 passed, 0 failed, 0 skipped, 2 warnings** in 10.90 seconds.
- The two warnings are `PytestCollectionWarning` messages caused by the required production class name `TestRunValidator` being visible in two test modules; they do not represent test failures.
- `tests/test_ollama_integration.py` remained excluded as the Phase 2 real-network test file, exactly as required by the Phase 3 plan.

## Actual Security Boundary

`run_process` and the three validation tools **do enforce** argv-only execution with `shell=False`, a fixed executable and fixed base command per tool, a caller-supplied target that must pass the existing filesystem sandbox validation, a minimal child-process environment, a hard wall-clock timeout, real process-tree termination on Windows through `taskkill /F /T`, and a hard output cap enforced by active truncation and process termination rather than post-hoc slicing after unbounded buffering. The process-tree behavior was proven against a real orphan-spawning script in Task 1, not a mock.

They explicitly **do not enforce containment**. A launched test, lint, or typecheck process shares the orchestrator's Windows user account and privileges. Nothing in Phase 3 prevents that running process from reading or writing files, making network calls, or launching other processes within that account's normal permissions, and nothing prevents it from being slow or resource-hungry short of the hard timeout and output limit. No OS-level sandboxing, restricted access token, Windows Job Object, container, or VM isolation is implemented in this phase.

If stronger isolation becomes a hard requirement in a future phase, concrete next steps include launching under a restricted access token, adding a Windows Job Object with CPU and memory limits, or using container/VM-level isolation. Windows Job Object limits could specifically be added through `ctypes` without introducing a new Python package dependency.

This is therefore a **launch-control boundary, not a containment boundary**.

## Security/determinism invariants confirmed

- Command injection is structurally impossible, not merely rejected by a validator: `shell=False` argv-list execution means there is no shell to inject into. This was proven with real subprocess execution, just as full process-tree termination was proven with a real subprocess rather than a mock.
- No parameter accepts a caller-chosen executable or raw command string. Tests prove that `executable`, `command`, and `args` keys are rejected before permission evaluation.
- Reviewer approval was proven end-to-end, with a real subprocess test run and zero changes to `orchestrator/core.py`, never to override a real deterministic validation failure. `test_reviewer_approval_does_not_override_a_real_failing_test` scripts the reviewer to approve every iteration and still reaches `ESCALATE_TO_USER` because pytest fails.
- Git remains exactly as restrictive as Phase 0, Phase 1, and Phase 2 left it. No git capability was added, the existing write-tool denials were confirmed alongside the new validation tools in the Task 4 gateway tests, and no git command was run in this session.

## Scope decisions

- `ruff` and `mypy` are intentionally not installed in this environment. `lint.run` and `typecheck.run` are fully implemented and registered, and a missing module was proven to degrade cleanly to `passed: False` rather than crash. This is also the behavior a generated project would encounter when its own development dependencies are unavailable.
- `AcceptanceCriteriaFileValidator` and `orchestrator/core.py` were not modified.
- Work stopped after Task 6; no phase beyond Phase 3 was started.
