# Phase 9 Report

## Status

**COMPLETE — Backend Planning Mode (Spec A) is implemented, tested, and verified.**
This supersedes the earlier BLOCKED status recorded in this file. The
workspace patch-mechanism failure that blocked the first two attempts is no
longer relevant to the current state: all six planned tasks are implemented,
the full deterministic regression suite is green, and a live authenticated
loopback smoke test succeeded.

## Baseline vs. final test results

- Baseline (Phase 0-8, before Phase 9 work): **745 passed, 0 failed** in
  21.96s.
- Final: `python -m pytest tests/ --ignore=tests/test_ollama_integration.py --ignore=tests/test_mcp_real_integration.py -v --tb=short`
  → **859 passed, 0 failed, 5 warnings** in 26.83s.
- Net new tests: **114** (112 in the nine new Phase 9 test files, plus 2 new
  MCP-preference-narrowing tests added to the existing
  `tests/test_mcp_gateway_tools.py`).
- The 3 pre-existing `PytestCollectionWarning` messages for `TestRunValidator`
  are unchanged from baseline. The 2 additional warnings are
  `websockets`-library deprecation notices triggered only by
  `test_backend_server.py`'s live-server test; they are not failures and do
  not originate from Phase 9 code.
- Real Ollama and real MCP integration suites remained excluded exactly as
  required.

## Files created

- `src/agent_platform/security/mode_policy.py` — immutable per-`OperatingMode`
  policy table (role/tool narrowing + PLAN write-scope).
- `src/agent_platform/orchestrator/plan_schemas.py` — strict typed parsers for
  Planning Mode model output, plus `validate_spec_id`/`InvalidSpecIdError`
  (reject-only, never normalizing).
- `src/agent_platform/orchestrator/plan_markdown.py` — pure, deterministic
  Markdown rendering of a `StructuredPlan`.
- `src/agent_platform/orchestrator/plan_artifacts.py` — plan artifact path
  derivation and gateway-mediated writing.
- `src/agent_platform/mcp/preferences.py` — in-memory, narrowing-only MCP
  user preferences.
- `src/agent_platform/server.py` — loopback-only FastAPI/uvicorn process
  entrypoint, token generation, startup JSON line.
- `src/agent_platform/backend_api.py` — authenticated FastAPI route layer
  (sessions, messages, plan lifecycle, MCP preferences, SSE events).
- `src/agent_platform/api_serialization.py` — explicit field-by-field
  dataclass-to-dict serializers (no `vars()`/`__dict__` reflection).
- `tests/test_operating_mode_policy.py`
- `tests/test_orchestrator_operating_mode.py`
- `tests/test_plan_mode_sandbox.py`
- `tests/test_plan_schemas.py`
- `tests/test_plan_markdown.py`
- `tests/test_orchestrator_plan_mode.py`
- `tests/test_mcp_preferences.py`
- `tests/test_backend_api.py`
- `tests/test_backend_server.py`
- `docs/superpowers/plans/2026-08-16-phase-9-backend-planning-mode.md`
- `docs/superpowers/specs/2026-08-16-phase-9-planning-mode-vscode-client-design.md`

## Files modified

- `src/agent_platform/security/enums.py` — added `OperatingMode` enum
  (CHAT/PLAN/CODE/EDIT/REVIEW).
- `src/agent_platform/security/permission.py` — `PermissionEvaluator.evaluate`
  gained an explicit `operating_mode: OperatingMode = OperatingMode.CODE`
  keyword argument that consults `MODE_POLICIES` after the existing
  role/session/sandbox checks; CODE/EDIT are proven no-ops via
  `test_code_and_edit_preserve_existing_permission_behavior`.
- `src/agent_platform/tools/gateway.py` — `ToolGateway.invoke` gained the same
  explicit `operating_mode` keyword and forwards it to the evaluator.
- `src/agent_platform/orchestrator/core.py` — added `run_plan`, `revise_plan`,
  `approve_plan`, `reject_plan`, `plan_status`, `run_chat`, `run_review`, all
  of which explicitly pass `operating_mode=` on every gateway/context call
  they make; the Code/Edit state machine (`run`, `amend_requirements`, and
  everything downstream of `_implement`) is untouched in control flow.
- `src/agent_platform/orchestrator/fake_model.py` — added
  `plan_mode`/`review_plan`/`chat`/`review_session` scripted response queues
  and a `code_call_count` counter used to prove Coder is never invoked
  outside Code/Edit.
- `src/agent_platform/orchestrator/model_provider.py` — `ModelProvider`
  Protocol extended with the four Planning Mode methods.
- `src/agent_platform/context/bundle_builder.py`,
  `src/agent_platform/context/discovery.py`,
  `src/agent_platform/context/role_context.py` — every gateway call site
  gained a defaulted `operating_mode: OperatingMode = OperatingMode.CODE`
  parameter, threaded through to `gateway.invoke`; behavior is byte-for-byte
  identical when the caller omits the new argument.
- `src/agent_platform/events.py` — added `PLAN_CREATED`, `PLAN_REVISED`,
  `PLAN_APPROVED`, `PLAN_REJECTED`, `PLAN_RESEARCH_REQUESTED`,
  `PLAN_RESEARCH_COMPLETED`, `PLAN_REVIEWED`, `PLAN_ARTIFACT_WRITTEN`,
  `SPEC_VERSION_CREATED`, `SPEC_VERSION_MISMATCH` to `EventType`. No existing
  event type was removed or renamed.
- `src/agent_platform/mcp/gateway_tools.py` — `build_mcp_tool_specs` /
  `build_mcp_permission_grants` / `register_mcp_capabilities` gained an
  optional `preferences: Optional[MCPUserPreferences] = None` parameter that
  narrows the existing discovered-∩-trusted-config capability set; omitting
  it reproduces the prior behavior exactly.
- `src/agent_platform/config.py` — `PlatformConfig` gained
  `max_plan_research_rounds` and `review_mode_allows_test_run` fields with
  defaults, plus positive-integer validation for the new bound.
- `tests/test_context_bundle_builder.py` — the test-local fake gateway's
  `invoke` gained an `operating_mode=None` keyword so it accepts the new
  argument; no existing assertion was changed or removed.
- `tests/test_mcp_gateway_tools.py` — added
  `test_user_preferences_narrow_registered_tool_specs_never_expand` and
  `test_user_preferences_disabling_server_removes_all_grants`.

## Tests added

114 net new tests across 9 new files + 2 tests appended to an existing file.
Coverage includes: the immutable mode-policy matrix, CODE/EDIT no-op parity,
PLAN-scope sandbox containment (including junction/symlink/UNC/device-path
escape attempts on Windows), strict `spec_id` accept/reject (14 malformed
cases: empty, whitespace, `..`, path separators, NUL byte, 256-char
overlength, non-ASCII, UNC/drive-absolute), structured-plan/clarification/
research-batch parsing and malformed-input rejection, deterministic Markdown
snapshot rendering, the full plan lifecycle (draft → revise → approve/reject,
immutability after approval, amend-after-approval versioning, rejection never
touching `SpecStore`), bounded research loop with allow/deny observations fed
back to the Planner, one automatic reviewer critique pass per draft, Coder
non-participation (`code_call_count == 0`) asserted on every Plan/Chat/Review
path, Reviewer write-denial, MCP preference narrowing (intersection-only,
per-server isolation, credential omission), and the authenticated FastAPI/SSE
layer (401 before any session exists, per-session event isolation, 409s for
mode/state mismatches, loopback-only binding, single-JSON-line startup
output).

## Security tests

- `test_plan_coder_is_denied_every_tool` — Coder gets `DENY` for every tool in
  PLAN mode, with reason `"role not permitted in PLAN mode"`.
- `test_plan_reviewer_cannot_write` / `test_reviewer_cannot_write_plan_artifacts_even_if_attempted`
  — no `(REVIEWER, filesystem.write)` grant exists anywhere in the base table
  or PLAN's `mode_grants`.
- `test_plan_planner_can_write_only_under_plan_directory` — Planner writes
  outside `.agent/plans/**` are denied by the *existing*
  `FilesystemSandbox.authorize`, not a new containment check.
- `test_plan_scope_rejects_escape_and_special_paths` (parametrized over `..`
  traversal, sibling-prefix directories, drive-relative, UNC, device paths,
  `.git` targeting) and dedicated junction/symlink-escape tests.
- `test_invalid_spec_ids_are_rejected_not_normalized` (14 cases) and
  `test_run_plan_rejects_invalid_spec_id_without_normalizing` /
  `test_invalid_spec_id_is_400_not_normalized` — confirms rejection at both
  the Orchestrator and HTTP boundary, never sanitization.
- `test_missing_token_is_401_before_any_session_created`,
  `test_wrong_token_is_401` — auth is checked before any session/orchestrator
  state exists.
- `test_events_stream_excludes_internal_events`,
  `test_events_are_isolated_per_session` — internal reasoning/tool-arg traffic
  never reaches the SSE wire format; sessions cannot see each other's events.
- `test_mcp_servers_route_never_includes_credential`,
  `test_describe_server_never_includes_credential_field` — the credential
  field is omitted by construction, not masked.
- `test_narrow_capabilities_can_only_remove_never_add`,
  `test_effective_capabilities_intersects_discovery_trusted_config_and_preference`
  — preferences cannot escalate capability beyond discovery ∩ trusted config.
- `test_bind_loopback_socket_binds_127_0_0_1_never_0_0_0_0` — transport never
  binds a non-loopback interface.
- Live smoke test performed this session (see below) independently confirmed
  401-before-auth and reject-before-normalize behavior against a running
  process, not just in-process test doubles.

## Discovered vulnerabilities

None found. No new permission system, sandbox, or authority path was
introduced; every Planning Mode write and every MCP call re-enters the
existing `PermissionEvaluator` → `FilesystemSandbox` → `ToolGateway` pipeline
Phase 0 already established.

## Phase 0-8 behavior changed

None, functionally. All modifications to existing files are additive
defaulted parameters (`operating_mode: OperatingMode = OperatingMode.CODE`)
threaded through call sites already present; `test_code_and_edit_preserve_existing_permission_behavior`
and the unchanged 745 baseline tests (all still present, all still passing)
are the direct evidence. `EventType` gained new members; no existing member
was removed, renamed, or repurposed.

## Confirmations

- **Coder never participates in Plan Mode**: structurally impossible, not
  just untested — no code path in `run_plan`, `revise_plan`, `approve_plan`,
  `reject_plan`, `run_chat`, or `run_review` calls `self._model.code(...)`,
  and `FakeModelProvider.code_call_count == 0` is asserted after every one of
  those methods across `tests/test_orchestrator_plan_mode.py`.
- **Reviewer cannot write plan artifacts**: no `(Role.REVIEWER, "filesystem.write")`
  or `(Role.REVIEWER, "filesystem.create_directory")` grant exists in the base
  tool table or in `MODE_POLICIES[OperatingMode.PLAN].mode_grants`; proven by
  `test_plan_reviewer_cannot_write` and
  `test_reviewer_cannot_write_plan_artifacts_even_if_attempted`.
- **No Git command was run**: confirmed — this implementation session issued
  zero `git` invocations of any kind (no status/diff/add/commit/etc.);
  file-modification tracking above was produced entirely from direct
  filesystem reads.
- **No unnecessary dependencies installed**: `fastapi==0.119.1`,
  `uvicorn==0.38.0`, and `websockets==15.0.1` (a uvicorn transitive
  dependency, used only by the live-server test) were already present in the
  environment before this work began; nothing was installed.

## Exact final test command and result

```
python -m pytest tests/ --ignore=tests/test_ollama_integration.py --ignore=tests/test_mcp_real_integration.py -v --tb=short
```

```
859 passed, 5 warnings in 26.83s
```

## Live verification

Started the backend in-process via `agent_platform.server.build_server`,
bound to an OS-assigned `127.0.0.1` port, and issued real HTTP requests:

- Unauthenticated `POST /sessions` → `401`.
- Authenticated `POST /sessions` (`CHAT` mode) → `200`, session created.
- `POST /sessions/{id}/messages` → `200`, scripted chat reply returned.
- `POST /sessions` with `spec_id="bad id"` (contains a space) → `400`,
  `{"error": "invalid spec_id: 'bad id'", "code": "BAD_REQUEST"}` — rejected,
  not normalized.

## Scope confirmation

- No VS Code extension or other Spec B work was started.
- No real Ollama or real MCP suite was run.
- Work stopped at the end of Phase 9; nothing beyond it was attempted.
