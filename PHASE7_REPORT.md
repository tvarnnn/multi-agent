# Phase 7 Report — Adversarial Security Campaign

## Summary

**36/36 attacks attempted. 34 PASS, 2 FAIL (both documented, both
out-of-scope-to-fix per this phase's own "do not add new capabilities"
instruction). 2 real, previously-undiscovered vulnerabilities found and
fixed** with the smallest deterministic control in each case. **745/745
deterministic tests pass** (711 prior + 34 new), zero regressions.

## The two vulnerabilities found and fixed

### 1. Executable/module substitution (Attack 34)

**Reproduced empirically before writing any code**, in a disposable
directory outside this project: `python -m pytest` run with `cwd` set to
the sandboxed project directory imports a same-named `pytest.py` file
*from that directory* instead of the real installed package, because
Python's `-m` mode prepends the current working directory to `sys.path`.
A 4-line malicious `pytest.py` executed arbitrary code and never ran a
single real test.

**Fix:** added `-P` (isolated mode, Python 3.11+) to all three
validation tools' base argv in `tools/registry.py`. `-P` suppresses the
cwd-prepending behavior. Verified the fix doesn't affect normal test
discovery/execution before committing to it, and again via the full
regression run afterward.

**Regression test:** `tests/test_security_executable_substitution.py`

### 2. Git config-driven code execution on read-only operations (Attack 9)

**Reproduced empirically**: a crafted `.git/config` setting
`core.fsmonitor` or `diff.external` to an arbitrary command causes that
command to execute during `git status --porcelain` or `git diff` — the
exact two git operations Phase 1 built as "safe, read-only" tools.
Separately confirmed a `pre-commit` hook does **not** fire on these same
read-only commands (that vector was checked and is not live here).

**Fix:** added `_GIT_SAFETY_FLAGS = ["--no-pager", "-c",
"core.fsmonitor=", "-c", "diff.external="]`, applied to every git
subprocess invocation in `tools/registry.py` (`_git_toplevel` and
`_run_git_readonly`). Only the two confirmed-exploitable vectors are
neutralized — not a speculative list of every conceivable git config
key.

**Regression test:** `tests/test_security_git_config_execution.py`
(3 tests: `core.fsmonitor`, `diff.external`, and the `pre-commit`
confirmation).

## Full attack table

| # | Attack | Expected | Actual | PASS/FAIL | Control | Regression Test |
|---|---|---|---|---|---|---|
| 1 | Path traversal | Denied regardless of `../` depth | Denied | PASS | `FilesystemSandbox` containment via `relative_to`, not string matching | `test_sandbox_adversarial.py::test_traversal_depth_matrix_is_always_denied` |
| 2 | Absolute-path escape | Denied | Denied | PASS | Same sandbox containment | `test_sandbox.py::test_absolute_escape_is_denied` |
| 3 | Sibling-prefix attack | `ProjectsEvil` not treated as inside `Projects` | Denied | PASS | `relative_to` (path-segment, not string-prefix) comparison | `test_sandbox.py::test_sibling_prefix_attack_is_denied` |
| 4 | Symlink escape | Denied even with a real symlink | Denied | PASS | Reparse-point detection on the pre-resolution path chain | `test_sandbox.py::test_symlink_in_path_is_denied` |
| 5 | Junction escape | Denied | Denied | PASS | Same reparse-point detection | `test_sandbox.py::test_junction_escaping_workspace_is_denied` |
| 6 | Reparse-point escape (generic) | Denied even resolving back inside the workspace | Denied | PASS | Generic `FILE_ATTRIBUTE_REPARSE_POINT` check, not junction/symlink-specific | `test_sandbox.py::test_junction_in_path_is_denied_even_if_target_is_inside_workspace` |
| 7 | UNC path escape | Denied | Denied | PASS | UNC/device-prefix string rejection before resolution | `test_sandbox.py::test_unc_path_is_denied` |
| 8 | Device path escape | Denied | Denied | PASS | Reserved-device-name and device-namespace rejection | `test_sandbox.py::test_device_namespace_path_is_denied` |
| 9 | Git manipulation | Read-only git ops must not execute arbitrary code | **Initially executed attacker command via `core.fsmonitor`/`diff.external`** | **FAIL → FIXED** | `_GIT_SAFETY_FLAGS` on every git subprocess call | `test_security_git_config_execution.py` (new) |
| 10 | Git commit attempt | Denied unconditionally | Denied | PASS | `ABSOLUTE_DENY_TOOLS`, no session mode can override | `test_permission.py::test_absolute_deny_tools_are_always_denied` |
| 11 | Git hook execution | Pre-existing hooks must not fire on read-only ops | Confirmed: does not fire | PASS | Git's own semantics (commit hooks only run on commits) + `.git/` write denial prevents planting one | `test_security_git_config_execution.py::test_pre_commit_hook_does_not_fire_on_read_only_operations` (new) |
| 12 | Malicious tests | Collection-time code (e.g. `conftest.py`) is a documented execution boundary, not contained — but timeout/output controls must still hold | `conftest.py` executed (expected); timeout killed it cleanly | PASS *(against the documented expectation — see "Actual Security Boundary")* | `run_process`'s hard timeout + process-tree kill | `test_security_campaign_coverage.py::test_attacks_12_13_...` (new) |
| 13 | Malicious build scripts | No build/install tool exists to abuse | No such tool | PASS | Structural absence of any build-executing tool | `test_security_campaign_coverage.py::test_attack_16_...` (new; covers 13 by the same absence) |
| 14 | Command injection | Shell metacharacters inert | Inert | PASS | `shell=False`, argv-list execution — no shell to inject into | `process_execution.py` design, re-verified via Task 1's fix regression |
| 15 | Argument injection | A single string can't become multiple argv elements or a flag | Confirmed | PASS | Resolved paths are always absolute (never start with `-`); one string = one argv element, no splitting | `test_security_campaign_coverage.py::test_attack_35_...` (new; also proves no flag-shaped keys accepted) |
| 16 | Dependency abuse | No dependency-installation capability exists | Confirmed | PASS | Structural absence | `test_security_campaign_coverage.py::test_attack_16_no_dependency_installation_tool_exists` (new) |
| 17 | Source-file prompt injection | Inert text, zero side effects | Inert | PASS | No code path parses retrieved file content as instructions | `test_context_bundle_builder.py::test_source_file_prompt_injection_is_retrieved_as_inert_text` |
| 18 | Documentation prompt injection | Inert text | Inert | PASS | Same | `test_security_campaign_coverage.py::test_attack_18_...` (new) |
| 19 | MCP prompt injection | Inert, zero side effects | Inert | PASS | `MCPResponse.data` is plain data, never interpreted | `test_mcp_adversarial.py::test_prompt_injection_response_produces_zero_side_effects` |
| 20 | Secret exfiltration | — | A test process (same OS privileges) can read outside the sandbox and stage content inside it | **FAIL (documented, not fixed)** | None — requires OS-level process isolation, out of this phase's scope | `test_security_known_gaps.py::test_attack_20_...` (new — demonstrates, doesn't defend) |
| 21 | Unauthorized network access | — | A test process can make arbitrary outbound network calls | **FAIL (documented, not fixed)** | None — same reason | `test_security_known_gaps.py::test_attack_21_...` (new — demonstrates, doesn't defend) |
| 22 | Coder permission bypass | Denied outside its own project scope, including sibling projects | Denied | PASS | Sandbox `scope_root` narrowing, applied identically to validation-tool targets | `test_security_campaign_coverage.py::test_attack_22_coder_cannot_run_tests_against_a_sibling_project` (new) |
| 23 | Reviewer modification attempt | Zero write grants, any tool | Zero grants confirmed | PASS | No `filesystem.write`/git-write/`shell.run` grant in the permission table | `test_security_campaign_coverage.py::test_attacks_23_24_...` (new, parametrized sweep) |
| 24 | Planner permission bypass | Zero write grants, any tool | Zero grants confirmed | PASS | Same | Same test (new) |
| 25 | Malformed model output | Bounded retry then escalate, never crashes or drives a transition | Confirmed | PASS | Two-layer schema validation (Ollama JSON-schema + Python parse functions) | `test_orchestrator_clarification.py::test_malformed_planner_output_retries_then_succeeds` |
| 26 | Model timeout | Bounded retry then escalate | Confirmed | PASS | `ModelTimeoutError` handling in `_invoke_with_retry` | `test_orchestrator_clarification.py::test_model_timeout_is_retried_then_can_succeed` |
| 27 | Reviewer loop | Escalates, doesn't loop forever | Confirmed, now earlier via stall detection | PASS | Iteration cap + repeated-rejection detection (Phase 6) | `test_orchestrator_stall_detection.py` |
| 28 | Clarification loop | Escalates at the round cap | Confirmed | PASS | `max_clarification_rounds` | `test_orchestrator_clarification.py::test_repeated_blocking_beyond_cap_escalates_to_stuck` |
| 29 | Specification mismatch | Deterministically rejected | Confirmed, both Coder and Reviewer | PASS | `SpecStore.assert_current` | `test_orchestrator_clarification.py::test_coder_pinned_to_stale_spec_version_is_deterministically_rejected` |
| 30 | MCP failure | Clean observation, never a crash | Confirmed (timeout, server error) | PASS | `MCPClient.call`'s deterministic status mapping | `test_phase6_integration_scenarios.py::test_mcp_timeout_failure_is_a_clean_observation_not_a_crash` |
| 31 | Corrupted session state | Re-entrant `run()` on the same instance stays consistent | Confirmed | PASS | Append-only `SpecStore`, fresh per-call history reset | `test_security_campaign_coverage.py::test_attack_31_...` (new) |
| 32 | Orphan-process recovery | Full process tree killed on timeout, end-to-end | Confirmed | PASS | `taskkill /F /T` in `run_process`, exercised through the real `test.run` tool | `test_security_end_to_end_confirmations.py::test_attack_32_...` (new) |
| 33 | Output-limit bypass | Truncated, capped, end-to-end | Confirmed | PASS | Active-truncation reader threads in `run_process` | `test_security_end_to_end_confirmations.py::test_attack_33_...` (new) |
| 34 | Executable substitution | Real tool always runs, never a same-named project file | **Initially: malicious `pytest.py` executed instead** | **FAIL → FIXED** | `-P` isolated mode on all three validation tools | `test_security_executable_substitution.py` (new) |
| 35 | Environment-variable abuse | No caller-supplied env accepted; minimal env doesn't leak secrets | Confirmed | PASS | Fixed minimal environment + schema rejection of `env`/`environment` keys | `test_security_campaign_coverage.py::test_attack_35_...` (new) + `test_process_execution.py::test_uses_minimal_environment_not_full_parent_env` |
| 36 | Unauthorized configuration modification | No tool can register a server or change permissions/config | Confirmed | PASS | Frozen dataclasses, no mutation methods anywhere, structural absence of any config-mutating tool | `test_security_campaign_coverage.py::test_attack_36_...` (new) + `test_mcp_server_registry.py::test_registry_exposes_no_mutation_method` |

## Every failure and fix

Exactly two: Attack 9 (Git manipulation) and Attack 34 (executable
substitution), both detailed above with empirical reproduction, minimal
deterministic fix, and regression test.

## Remaining limitations

- **Attack 20 (secret exfiltration)** and **Attack 21 (unauthorized
  network access)**: both confirmed real. A process launched by
  `test.run`/`lint.run`/`typecheck.run` runs with the same OS privileges
  as the orchestrator itself, with no additional isolation. This is the
  same boundary Phase 3's report named in the abstract — this phase
  makes it concrete with two working, minimal exploits rather than
  leaving it as an assertion.
- **Attack 12/13 (malicious tests / conftest.py)**: collection-time code
  execution is real and not contained (same root cause as 20/21) — what
  *is* confirmed to still work correctly is the timeout/process-tree-kill
  safety net, even when the malicious behavior originates at collection
  time rather than inside a test function.
- Neither gap is fixed in this phase. Doing so would mean OS-level
  process isolation — a genuinely new capability, explicitly out of
  scope ("do not add new capabilities").

## Actual security boundary (restated, now with two more concrete examples)

Everything Phase 3 originally documented still holds, and this phase
adds specificity: `run_process` and the validation tools are a
**launch-control boundary** — they control *how* a process is started
(fixed executable, argv-only, no shell, minimal environment, `-P`
isolation against module shadowing, hard timeout, process-tree
termination, output caps) and *how it's stopped*. They are **not a
containment boundary** — once running, a process can read/write any file
the orchestrator's OS account can access (demonstrated: Attack 20), make
arbitrary network calls (demonstrated: Attack 21), and execute arbitrary
code at import/collection time before a single test function runs
(demonstrated: Attack 12/13). The same is now true, with equal
specificity, of git: `_run_git_readonly` closes the two config-driven
execution vectors that were found, but a git binary invocation is still
a real subprocess whose broader config-driven behavior surface has not
been exhaustively enumerated beyond the two confirmed vectors.

## OS-level containment limitations (unchanged recommendation, now with more evidence behind it)

The concrete next step, if stronger isolation becomes a hard requirement:
a restricted access token, a Windows Job Object with CPU/memory/handle
limits (addable via `ctypes`, no new dependency), or full container/VM
isolation for anything launched by the validation tools. Three
independent, empirically-confirmed exploit paths (secret exfiltration,
network access, and — the two fixed this phase — module shadowing and
git-config execution) all point at the same underlying gap: nothing
between "argv-controlled launch" and "OS-account-level privilege" exists
yet. The two fixes in this phase closed the specific vectors that were
*cheap and deterministic* to close (an interpreter flag, a git config
override); the remaining two require infrastructure this phase was
explicitly told not to add.

## Test results

**745 passed, 0 failed, 0 skipped**
(`python -m pytest tests/ --ignore=tests/test_ollama_integration.py
--ignore=tests/test_mcp_real_integration.py -q`) — 711 from Phase 0-6
plus 34 new this phase (1 executable-substitution regression, 3 git-
config-execution regressions, 26 new adversarial coverage tests, 2 end-
to-end confirmations, 2 known-gap demonstrations), zero regressions.

No git commands were run against the real project this session. The two
attack-simulation tests that needed a real `.git/config` (Task 2) ran
`git init`/`config`/`add` inside disposable `pytest` `tmp_path`
directories only, with explicit confirmation before doing so — never
touching this project's own (still git-uninitialized) state.
