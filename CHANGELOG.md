# Changelog

All notable changes to Agent Platform are documented in this file.

## [1.0.0] — 2026-08-17

First complete release. Agent Platform is a local-first, backend-authoritative software
engineering platform: specialized model roles (Planner, Coder, Reviewer) operate against
a real project on disk through a single Python backend that owns every permission
decision, filesystem write, MCP call, and piece of persisted state. A VS Code extension
and a CLI script are both thin clients over that backend. This release was built across
thirteen phases (Phase 0 through Phase 12), each independently tested and reported in
its own `PHASE<N>_REPORT.md`; this entry summarizes the cumulative, final result.

Final verification for this release: **1177 backend tests passing, 0 failed, 2
pre-existing environment skips**; a VS Code extension built, packaged, installed, and
driven through a real live end-to-end workflow against real Ollama models with no
scripted/fake responses.

### Added

**Autonomous orchestration (Phases 0–3, 6)**
- A deterministic state machine (`orchestrator/core.py`) driving Planner → Coder →
  Reviewer through `RECEIVE_REQUEST → PLAN → VALIDATE_PLAN → IMPLEMENT → TEST → REVIEW
  → FEEDBACK → IMPLEMENT_FIX → FINAL_VALIDATION → COMPLETE`, with `BLOCKED` /
  `RESOLVE_CLARIFICATION` and `STUCK` / `ESCALATE_TO_USER` as distinct handling for
  routine clarification versus genuine stalls.
- Real, deterministic validation: `test.run`/`lint.run`/`typecheck.run` execute the
  project's actual test/lint/typecheck commands as subprocesses; a Reviewer's approval
  can never override a real deterministic test failure.
- Stall detection (negligible diffs, repeated identical test failures, repeated
  reviewer rejections) that routes to `STUCK` instead of looping indefinitely, with
  bounded fix-loop and clarification-round iteration caps.
- A `ModelProvider` protocol satisfied by both a real `OllamaModelProvider` (structured
  JSON output via Ollama's `format` schema constraint) and a scripted
  `FakeModelProvider` for deterministic testing.

**Permission and operating-mode architecture (Phases 0, 9)**
- Three independent axes: `Role` (PLANNER/CODER/REVIEWER — who's acting), `SessionMode`
  (AUTO/CONFIRMATION/MANUAL — how much approval friction applies), and `OperatingMode`
  (CHAT/PLAN/CODE/EDIT/REVIEW — what kind of session this is, immutable for the
  session's lifetime).
- A deterministic `PermissionEvaluator` evaluating role × mode × session-mode ceiling ×
  concrete path on every tool invocation — never by tool name alone.
- `ABSOLUTE_DENY_TOOLS` (all git write operations, raw shell execution) that no role,
  mode, or table entry can ever unlock.
- Per-mode policy narrowing (`security/mode_policy.py`): CHAT/REVIEW are read-only;
  PLAN may write only inside `.agent/plans/`; CODE/EDIT retain full, unrestricted
  pre-existing tool access.

**Filesystem sandboxing and security controls (Phase 0, hardened in Phase 7)**
- `FilesystemSandbox`: path containment via `Path.relative_to` (never string-prefix
  matching), reparse-point (junction/symlink) detection on the unresolved path chain,
  UNC/device-namespace path rejection, drive-relative/root-relative ambiguity
  rejection, reserved Windows device name rejection, and `.git` internals protection.
- A `ToolGateway` six-step pipeline (schema validation → permission evaluation →
  precondition checks → execute → wrap as a structured observation → log) that every
  role and every tool type goes through with no privileged shortcut.
- A dedicated adversarial security campaign (Phase 7) that found and fixed two real,
  reproducible exploits (a `test.run`/`lint.run` executable-substitution vector and a
  `git`-config-driven code-execution vector) with minimal deterministic fixes and
  regression tests.

**MCP integration (Phase 4)**
- Trusted-configuration-only `MCPServerConfig`/`MCPServerRegistry` — no code path lets
  model output, a caller argument, or an MCP server's own response create or mutate a
  server entry.
- Capability registration as the intersection of live server discovery and trusted
  configuration (discovery can only narrow, never expand, what gets registered).
- MCP tools registered into the exact same `ToolRegistry`/`PermissionEvaluator` every
  other tool uses — no separate, weaker MCP permission system.
- Credential redaction (`mcp/secrets.py`) applied to MCP responses before they reach a
  role.

**Context management (Phase 5)**
- Bounded, deterministic, priority-ordered context retrieval (`referenced` → `changed`
  → `dependency` → `test` → `config` → `documentation` → `tree`), itself mediated by
  the same `ToolGateway`.
- Explicit limits (`ContextLimits`: 20 files, 200,000 bytes, ~50,000 estimated tokens,
  20,000 bytes per file, depth 6) — files past a limit are recorded as excluded, never
  silently dropped; oversized files are truncated with a flag.
- Structural sensitive-file exclusion (`.env*`, `credentials*`, `secrets.*`, private
  key files) from context discovery entirely — a fixed, auditable list, not content
  scanning.
- Per-role context isolation and a staleness cache flagging files whose content
  changed since last included.

**Persistent sessions, checkpoints, and restart recovery (Phase 10)**
- A SQLite database per project (`<project_root>/.agent/agent.db`) with append-only
  `messages`, `decisions`, `spec_versions`, `plan_snapshots`, `checkpoints`, and
  `tool_observations` tables, plus a `sessions` table tracking current status.
- Compaction that triggers on a token-budget threshold or forced milestones
  (plan approved/rejected, terminal state, archive) — compaction only ever *adds* a
  checkpoint; it never deletes or truncates the underlying message/decision history.
- Restart recovery: every persisted specification version is rehydrated into a fresh
  `SpecStore` once at backend startup before any session can be created; a corrupted
  sequence stops the backend from starting rather than serving against unknown state.
- Session resume that reconstructs from the latest checkpoint plus messages since it,
  with checkpoints treated as derived context — never authoritative for permissions,
  the active specification, or operating mode.

**Plan Mode and specification workflow (Phase 9)**
- A structured planning cycle — draft → revise → reviewer critique → explicit approval
  or rejection — producing a versioned, authoritative `SpecVersion` only on approval.
- A human-readable Markdown plan artifact per draft, written through the standard
  `ToolGateway` pipeline and scoped to `.agent/plans/`; the artifact does not become
  authoritative by being hand-edited.
- Strict `spec_id` validation that rejects invalid identifiers outright rather than
  sanitizing or truncating them.

**Chat, Code, Edit, and Review modes (Phase 9, wired end-to-end in Phase 12)**
- **Chat** — free-form conversation with the Planner role, read-only tool access.
- **Code** — the full autonomous implementation/test/review/fix-loop state machine.
- **Edit** — amends an already-approved specification and re-runs the implementation
  loop against the change.
- **Review** — Reviewer-only critique of an existing target, independent of an
  implementation run.
- All five modes are reachable over the backend HTTP API
  (`POST /sessions/{id}/messages`, routed internally by the session's operating mode).

**YAML configuration and model/MCP preferences (Phase 11)**
- A YAML settings layer (`settings/`) that only ever produces inputs to already-trusted
  constructors (`PlatformConfig.load()`, `MCPServerConfig`) — never a second authority,
  and never called from anything but backend startup.
- Workspace settings auto-loaded from `<project_root>/.agent/settings.yaml`; strict
  parsing that rejects unknown top-level or per-section keys as a hard startup error
  rather than silently ignoring them.
- Credential *references* (not raw secrets) in settings, resolved at startup via
  `AGENT_PLATFORM_MCP_CREDENTIAL_<NAME>` environment variables.
- A read-only `/configuration`, `/configuration/models`, `/configuration/mcp` API
  surface returning a safe view (model names/availability, MCP policy, effective
  agent-behavior values) that never includes a credential field.
- A live-mutable MCP preference route (`PUT /mcp/servers/{id}/preferences`) that can
  only narrow an already-established capability set, never grant a new one.

**FastAPI backend and API (Phase 9, extended through Phase 12)**
- A loopback-only (`127.0.0.1`) FastAPI backend with a bearer token generated fresh per
  process launch, printed once to stdout, never written to disk or logged.
- Authentication enforced both by per-route dependency and by request middleware that
  runs before route resolution, so an unauthenticated request to a nonexistent path
  returns 401, not 404.
- A full session/plan/configuration/MCP route surface (see the current `README.md`'s
  API section for the complete, current route list).

**Ollama model integration (Phase 2, defaulted in Phase 12)**
- `OllamaModelProvider` calling a local Ollama HTTP API with a JSON-schema `format`
  constraint per role/session-mode combination — grammar-constrained structured
  output, not free-text parsing.
- Configurable per-role model names (`planner`/`coder`/`reviewer`) via settings, with
  hardcoded fallbacks (`phi4-reasoning:plus` for Planner/Reviewer,
  `qwen2.5-coder:14b` for Coder) used consistently by the backend, the live-run CLI
  script, and the Phase 8 benchmark harness.
- Optional, network-failure-tolerant model availability discovery via Ollama's
  `/api/tags` endpoint.

**VS Code extension (Phase 12)**
- `agent-platform-vscode` v1.0.0 — see the dedicated section below.

**Testing and validation infrastructure (all phases)**
- A backend suite of ~150 pytest files including dedicated adversarial suites for
  sandbox escape, MCP capability escalation, persistence security, and settings
  security.
- A scripted `FakeModelProvider` enabling deterministic, network-free testing of the
  entire orchestration/persistence/API stack.
- A manual live-run CLI script (`scripts/live_run.py`) and a manual live end-to-end
  test script for the extension, both exercising real Ollama models with no mocking.
- An empirical benchmark harness (`benchmark/`) comparing two model-role
  configurations on wall-clock time, model calls, and tool invocations (Phase 8).

### Security

The following properties were implemented and are covered by the current test suite;
this is a description of what is tested, not a claim that the system is completely
secure:

- Permission is evaluated per tool invocation with concrete arguments (role × operating
  mode × session-mode ceiling × resolved path) — never by tool name alone.
- `ABSOLUTE_DENY_TOOLS` (all git write operations, raw shell execution) are denied
  unconditionally, with no role, mode, or configuration path that can grant them.
- The filesystem sandbox denies by default on ambiguity: path traversal, sibling-prefix
  attacks, symlink/junction escapes (including the workspace root itself being a
  reparse point), UNC and device-namespace paths, drive-relative/root-relative
  ambiguity, and reserved Windows device names are all rejected, not best-effort
  resolved.
- MCP capability exposure is the intersection of live server discovery and trusted
  configuration; a compromised or malicious MCP server cannot get a tool registered for
  a capability trusted configuration didn't already permit.
- Credentials (MCP and settings-derived) are never serialized in any API response —
  omitted from the wire format entirely, not masked.
- A dedicated adversarial security campaign (Phase 7) reproduced and fixed two real
  exploits (test/lint executable substitution; git-config-driven code execution) and
  documented, rather than silently accepted, the residual gaps described below.
- **Known, documented security boundary:** `test.run`/`lint.run`/`typecheck.run` and
  git subprocess invocations are a *launch-control* boundary (fixed executable,
  argv-only, no shell, minimal environment, hard timeout, process-tree termination) —
  not an OS-level *containment* boundary. A process they launch runs with the same OS
  privileges as the backend itself; secret exfiltration and unauthorized network access
  by a launched process, and arbitrary code execution at test-collection time, are
  confirmed-real, unfixed gaps (Phase 7), because closing them requires OS-level
  process isolation, explicitly out of scope for this release.
- Sensitive-file exclusion from context retrieval is structural (a fixed filename/
  extension list), not content scanning; it is a context-*discovery* boundary, not a
  `ToolGateway` deny — an explicit, model-initiated read of an excluded file is not
  itself blocked.

### VS Code Extension

`agent-platform-vscode` v1.0.0 (publisher `agent-platform`) is a thin client over the
Python backend — it holds no permission, sandboxing, MCP, or persistence authority of
its own.

- **Installation** — built with `tsc`, packaged with `@vscode/vsce` into a VSIX
  (verified: packages cleanly, ~16 KB, 11 files, no dev/test sources) and installed
  locally via `code --install-extension`.
- **Backend connection** — two modes: managed (the extension spawns
  `python -m agent_platform.server --workspace-root <folder> --sandbox-root <folder>`
  and reads a one-line startup JSON protocol from stdout) or external (connects to an
  already-running backend given a URL and token via extension settings).
- **Sessions** — a native sidebar `TreeView` for creating, listing, resuming, and
  archiving sessions, backed entirely by the persistent backend session store.
- **Plan artifacts** — commands to open or reveal a session's Markdown plan artifact
  directly in the editor/OS file explorer.
- **Session panel** — one `WebviewPanel` per active session (chat/plan transcript,
  approve/revise/reject actions) with a strict, per-render-nonce Content Security
  Policy and a validated, discriminated-union message contract between the Webview and
  the extension host.
- **Live workflow support** — verified end-to-end against real Ollama models: create a
  Plan session, approve it, run a Code session against the same specification, confirm
  the resulting file is actually written to disk, stop and restart the backend, and
  resume the session with the backend's current authoritative state.

### Testing

Final result for this release (`python -m pytest tests/
--ignore=tests/test_ollama_integration.py --ignore=tests/test_mcp_real_integration.py
-q`):

```
1177 passed, 2 skipped, 0 failed
```

The 2 skips are pre-existing, environment-dependent cases (symlink-privilege tests)
present since Phase 0, not a regression introduced by this release. The two ignored
files require a real running Ollama instance / real MCP server and are run manually.

Growth across the release, as reported by each phase's own final test run:

| Phase | Focus | Final result |
|---|---|---|
| 0 | Sandbox + permission evaluator | 451 passed, 0 failed |
| 1 | Event system, model schemas, fake provider | 541 passed, 0 failed |
| 2 | Ollama model provider | 570 passed, 0 failed |
| 3 | Validation & execution tools | 600 passed, 0 failed |
| 4 | MCP gateway | 645 passed, 0 failed |
| 5 | Context retrieval | 685 passed, 0 failed |
| 6 | Autonomous stall detection | 711 passed, 0 failed |
| 7 | Adversarial security campaign | 745 passed, 0 failed |
| 8 | Empirical benchmark harness | (harness/results, not a suite-growth phase) |
| 9 | Backend & Plan Mode | 859 passed, 0 failed |
| 10 | Persistence & context management | 1049 passed, 0 failed, 2 skipped |
| 11 | Configuration & platform contracts | 1140 passed, 0 failed, 2 skipped |
| 12 | VS Code extension (final) | 1177 passed, 0 failed, 2 skipped |

VS Code extension suite (`node ./out/test/runTest.js`, Mocha via
`@vscode/test-electron`): **22 passing, 1 pending, 0 failing.** The 1 pending test is a
documented `@vscode/test-electron` environment quirk (workspace-folder detection could
not be reliably observed in this harness), independently covered by 8 other tests that
do pass a real workspace root end-to-end into a real backend process.

Live, non-scripted verification (real Ollama models, real backend subprocess, real
filesystem writes) passed: Plan → Approve → Code → file written to disk → backend
restart → session resume with correct authoritative state. Five real backend bugs
(missing CODE/EDIT HTTP route, missing sandbox-root pinning, a CLI entrypoint that
never constructed a model provider, `OllamaModelProvider` missing Plan Mode methods,
and auth checked after routing instead of before) were found and fixed specifically
because of this live testing — the deterministic, fake-model test suite alone did not
catch any of them.

### Known Limitations

- **Remote SSH is architecturally designed for but NOT VERIFIED in the current
  environment** — no second machine/SSH target was available to test against.
- **`test.run`/`lint.run`/`typecheck.run` and git subprocesses are a launch-control
  boundary, not an OS-level containment boundary** (see Security, above) — a launched
  process runs with the backend's own OS privileges.
- **CONFIRMATION/MANUAL session modes have no interactive resume path.** A tool call
  that comes back as `requires_confirmation` currently has nowhere to go except
  `BLOCKED`.
- **Exact mid-fix-loop resume for CODE/EDIT sessions is not implemented.** A resumed
  session restores full history, checkpoint, and specification state for inspection;
  continuing means a fresh implementation run, not resumption from the exact point in
  the fix loop.
- **MCP user preferences are in-memory only, not persisted** across a backend restart.
- **No live `PUT` for model or agent-behavior settings** — changing them requires
  editing the settings file and restarting the backend (only MCP server preferences are
  live-mutable).
- **Settings-derived MCP server configurations are not automatically wired into a live,
  connected MCP client** — `GET /configuration/mcp` reports configured policy;
  `GET /mcp/servers` reports only servers a caller has explicitly wired with a real
  transport.
- **CODE/EDIT in-progress events (e.g. "implementing", "testing") are not exposed**
  over the API or event stream — only the final result of a run is reported.
- **Credential resolution is environment-variable-only** — no OS keychain or other
  secret-store integration.
- **`.env`/credential-file exclusion is a context-retrieval boundary, not a
  `ToolGateway` deny** — an explicit, model-initiated read of an excluded file is not
  itself blocked.
- **No cross-project session search** — one SQLite database per project.
- **`pyproject.toml` does not declare its runtime dependencies** (`fastapi`,
  `uvicorn`, `pydantic`, `pyyaml`, `requests`) — they must be installed manually.
- **The global settings-file precedence layer has no default path wired into the CLI
  entrypoint** — in practice, only the workspace settings file loads automatically
  today.
- **One VS Code extension test is skipped, not passing** (workspace-folder detection
  under the test harness — see Testing, above).
- **The live end-to-end test is manual, not CI-wired** — it depends on locally
  installed Ollama models and real inference time.
- **The Phase 8 benchmark comparison is a small pilot** (20 total task runs across two
  configurations), not a statistically powered study.

### Removed / Not Included

- The VS Code extension is a v1.0 **thin client**: a native sidebar plus one Webview
  session panel. Visual/UX polish, richer plan-diff rendering, live-pushed event
  streaming (the current event route returns a batched response, not a persistent
  push connection), and additional in-editor workflow affordances are not part of this
  release.
- There is no cloud infrastructure, hosted service, or telemetry anywhere in this
  release — everything runs against a locally spawned backend and a local Ollama
  instance.

### Future Work

Phase 12 is the final phase of this release; there is no committed next phase. The
following are possibilities suggested by the limitations above, explicitly **not**
committed work:

- An interactive resume/approval flow for `CONFIRMATION`/`MANUAL` session modes'
  confirmation-gated tool calls.
- Declaring the backend's runtime dependencies in `pyproject.toml` instead of requiring
  a manual install step.
- Wiring a default global-settings path so the already-built global→workspace
  precedence is reachable without a caller passing an explicit path.
- Verifying the Remote SSH deployment path on an actual second machine.
- A larger-scale, statistically powered version of the Phase 8 benchmark comparison.
