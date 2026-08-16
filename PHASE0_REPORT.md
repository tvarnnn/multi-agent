# Phase 0 Report

## Implemented
- Windows-aware filesystem sandbox (`security/sandbox.py`): path
  containment via `relative_to` (not string-prefix), traversal/absolute/
  drive-relative/root-relative/UNC/device-path rejection, reserved device
  name rejection, reparse-point detection on the pre-resolution path chain
  (catches junctions/symlinks even when they resolve back inside the
  workspace, and catches the workspace root itself being a reparse point
  at construction time), `.git` protection, safe new-project creation
  refusing to overwrite an existing directory or reparse point.
- Deterministic permission evaluator (`security/permission.py`): role x
  tool x session-mode x concrete-path evaluation, DENY-absolute tools
  (all git writes — `git.init`/`add`/`commit`/`push`/`reset`/`rebase` —
  plus `shell.run`) unconditionally denied regardless of table or session
  mode, `DENY < CONFIRM < ALLOW` composition where session mode only ever
  tightens, never loosens.
- Trusted configuration loading (`config.py`): workspace root validated
  once at startup from a plain string, never from model output.
- Immutable specification versioning (`spec/versioning.py`): append-only
  `SpecStore`, frozen `SpecVersion`, deterministic rejection of a stale
  version reference via `SpecVersionMismatchError`.

## Test results
**451 passed, 0 failed, 0 skipped**, full suite (`python -m pytest tests/ -v`),
run 2026-08-16 against native Windows Python 3.12.5. No test required
network access, an LLM, Ollama, or MCP — confirmed by running the suite and
separately grepping the whole `tests/` and `src/` tree for network-facing
imports (`requests`, `httpx`, `ollama`, `urllib.request`, `socket.`): zero
matches.

Breakdown by file:
- `test_smoke.py` — 1
- `test_enums.py` — 3
- `test_sandbox.py` — 27
- `test_sandbox_adversarial.py` — 309
- `test_sandbox_new_project.py` — 19
- `test_permission.py` — 77
- `test_config.py` — 5
- `test_versioning.py` — 10

One implementation bug was found and fixed during this run: the sandbox's
constructor originally checked the *resolved* workspace-root path for
reparse points, but `resolve()` had already dereferenced any junction by
that point, so a junction-as-workspace-root would have silently passed.
Fixed by checking the raw, pre-resolution path instead
(`test_workspace_root_itself_as_reparse_point_is_rejected` now passes and
would have caught this on its own before any code shipped).

One test-design bug was found and fixed in the adversarial suite: a
traversal-depth test asserted denial for `MyProj/../outside.txt` without
scoping to the active project, which is actually a correct ALLOW (it
resolves to the workspace root itself, not an escape). Fixed by scoping
that test to the active project directory, which is the property it was
actually meant to check.

## Security invariants enforced and tested
- DENY overrides ALLOW and CONFIRM in every session mode (77 cases across
  the full Role x SessionMode x tool cross-product).
- Containment uses path-segment comparison, not string prefix — the
  sibling-prefix attack (`ProjectsEvil` vs `Projects`) is explicitly
  tested against the naive `startswith` check it avoids.
- Reparse points are denied even when their target resolves back inside
  the workspace, not just when they escape it — confirmed with real
  junctions (`mklink /J`) and real symlinks (this account has symlink
  privilege enabled, so the symlink test ran for real rather than
  skipping).
- The workspace root itself being a reparse point is rejected at
  `FilesystemSandbox` construction time, before any path authorization
  can happen.
- `.git` is unreachable through generic filesystem authorization from
  anywhere in a project.
- New project creation refuses to overwrite an existing directory or
  reparse point at the target path.
- Permission evaluation is per-invocation with concrete arguments, not
  tool-name-only — proven by the ALLOW-tool-with-denied-path test.
- All git write operations (`init`/`add`/`commit`/`push`/`reset`/`rebase`)
  and `shell.run` are absolute denies, unconditionally, for every role and
  every session mode — 63 explicit cases (7 tools x 3 roles x 3 modes).
- Specification versions are immutable and append-only; a stale version
  reference is deterministically rejected, not silently honored.

## Windows-specific behavior not fully verified in this environment
- This machine has symlink-creation privilege enabled (Developer Mode or
  equivalent), so `test_symlink_in_path_is_denied` exercised a real
  symlink rather than skipping — meaning symlink-path denial has actual
  coverage here, not just coverage-by-analogy through the junction tests.
  On an account without that privilege the test would skip and symlink
  denial would only be proven indirectly (same code path as junctions,
  but not exercised against a real symlink).
- 8.3 short-name aliasing (e.g. `PROGRA~1` resolving to a long-named
  directory) was not tested — flagged as an open concern in the original
  architecture review and not covered by this phase's test matrix.
- Unicode confusable/normalization tricks beyond trailing dot/space
  stripping (e.g. fullwidth dot characters, combining diacritics) were not
  exhaustively tested. The trailing-dot/space case specifically *was*
  tested and denied correctly.

## Remaining concerns
- None observed as flaky — the full suite ran deterministically on repeat
  invocation during this session.
- Property-based testing was done via large deterministic parametrized
  matrices (452 total cases, most from the adversarial file) rather than
  the `hypothesis` library, to avoid a new network-fetched dependency and
  keep every test case reproducible without pinning a random seed. This
  was a deliberate scope decision, not an oversight — noted here in case
  a future phase wants randomized fuzzing on top of this deterministic
  base.
- `git.init` for this project itself was intentionally not run in this
  session, per explicit instruction — the working tree is uncommitted and
  entirely under the user's control to initialize and commit when ready.
