# Phase 11 Report — Configuration, Platform Contracts & Integration Layer

## 1. Phase 11 Status

**COMPLETE.** A YAML-based preference layer (global → workspace precedence), model/MCP
configuration visibility, a read-mostly `/configuration*` API surface, and an enriched
structured event contract are implemented, tested, and verified — all explicitly a **preference
layer**, never a second authority. Nothing built this phase can grant a permission, expand
filesystem access, bypass `ToolGateway`, expand MCP capabilities, or change `OperatingMode`
security policy; every claim below is backed by a test, not just an assertion.

## 2. Baseline

Reconfirmed at the start of this phase, exactly as instructed (not assumed from documentation):
`python -m pytest tests/ --ignore=tests/test_ollama_integration.py --ignore=tests/test_mcp_real_integration.py -q`
→ **1049 passed, 0 failed, 2 skipped** — matched the documented Phase 10 final exactly, no drift.

## 3. Final Test Count

`python -m pytest tests/ --ignore=tests/test_ollama_integration.py --ignore=tests/test_mcp_real_integration.py -v --tb=short`
→ **1140 passed, 0 failed, 2 skipped** in 30.99s.

## 4. New Tests

**91 net new tests.** `test_settings_loader.py` 20, `test_settings_credentials.py` 5,
`test_settings_builder.py` 11, `test_settings_model_discovery.py` 6, `test_settings_service.py` 6,
`test_settings_security_adversarial.py` 22, `test_backend_server_settings.py` 7,
`test_configuration_api.py` 9, `test_event_contract.py` 5.

## 5. Configuration Architecture

New package `src/agent_platform/settings/` — seven single-purpose modules, one facade
(`SettingsService`) that `server.py`/`backend_api.py` are the only callers of:

| Module | Purpose |
|---|---|
| `schema.py` | Frozen dataclasses: `ModelSettings`, `McpServerSettingsEntry`, `AgentBehaviorSettings` (every field `Optional`, mirrors `PlatformConfig`'s own field names exactly), `WorkspaceSettings`. |
| `loader.py` | `yaml.safe_load` only (never `yaml.load`/an unsafe Loader), strict unknown-key rejection at every nesting level, `merge_settings()`. |
| `credentials.py` | The one place a credential *reference* becomes a credential *value* — environment-variable lookup only. |
| `builder.py` | Turns parsed settings into `PlatformConfig.load()` kwargs and a `tuple[MCPServerConfig, ...]` — the exact inputs the existing trusted constructors already accepted, never a new authority. |
| `model_discovery.py` | Optional, injectable, network-failure-tolerant Ollama `/api/tags` query. |
| `service.py` | `SettingsService` — the facade; `.model_settings`, `.mcp_server_configs`, `.platform_config_kwargs`, `.safe_view()`. |

One config format only (YAML, via already-installed PyYAML — `import yaml` → 6.0.3 present in
this environment before this phase started; **no `pip install` was run**). No parallel
configuration system was created — `PlatformConfig` (`config.py`) remains the sole authority for
trusted, security-adjacent settings; `settings/` only produces its constructor inputs.

## 6. Configuration Precedence

```
GLOBAL DEFAULTS (an explicit global_settings_path, e.g. a per-user file; None = skip)
        ↓  per-top-level-section wholesale override (models / mcp / agent_behavior each
        ↓  replaced entirely if the workspace file specifies anything in that section,
        ↓  never deep-merged field-by-field — deterministic, no partial-override ambiguity)
WORKSPACE CONFIGURATION (<project_root>/.agent/settings.yaml, auto-discovered)
        ↓  explicit build_services() keyword argument always wins over either file
SESSION PREFERENCES (OperatingMode/SessionMode fixed at session creation via the existing
        POST /sessions body — Phase 9, unchanged; MCPUserPreferences narrowing via the
        existing PUT /mcp/servers/{id}/preferences — Phase 9, unchanged)
```

Neither settings file is required to exist; with neither present, every value falls back to the
exact hardcoded defaults Phase 10 already had — proven by a dedicated regression test
(`test_no_settings_file_behaves_identically_to_before_phase_11`).

## 7. Workspace Profiles

Workspace settings are auto-discovered at `<project_root>/.agent/settings.yaml` (same directory
convention as `.agent/plans/`, `.agent/context/`, `.agent/agent.db` — Phase 9/10). Cannot escape
the workspace boundary: the only path-shaped value it can influence is `agent_data_dir`, which
flows through `PlatformConfig.load()`'s existing (Phase 10) traversal/UNC validation, reused not
duplicated. Cannot modify global security policy or inject credentials — see §11.

## 8. Model Management

`GET /configuration/models` reports the configured planner/coder/reviewer model identifiers plus
availability. Availability uses an **optional, injectable** discovery function
(`model_discovery.py`); the real default queries Ollama's `/api/tags` but is wrapped so it never
raises and never blocks startup — any network failure degrades to "availability unknown," not an
error. The entire deterministic test suite injects a fake (`BackendServices.model_discovery_query_fn`)
and **never touches the real network** — confirmed by measuring the suite's runtime before/after
this route existed (no change) and by a dedicated test proving the injected fn, not the network,
is what gets called. No model download/install functionality was added, per the explicit
instruction. An invalid/uninstalled model identifier reports `available: False`, never raises.

## 9. MCP Preferences

`GET /configuration/mcp` reports the settings-derived **trusted capability policy** per server
(`enabled`, `transport`, `capabilities` — never a credential). This is a different, complementary
view from the existing `GET /mcp/servers` (Phase 9, unchanged): that route reports *live,
connected* servers (needs a real `MCPClient`); `/configuration/mcp` reports *configured* servers
from the settings file, independent of whether a live connection exists. Settings-sourced
`MCPServerConfig` objects are still subject to the exact same Phase 4 discovery-intersection gate
as any other trusted config — a settings file declaring a capability the server doesn't actually
support is never registered (`test_mcp_capabilities_still_gated_by_discovery_intersection_not_settings_alone`).
Disabled servers (`enabled: false`) are excluded from the trusted config tuple entirely — no
capability path exists for them at all, not even a denied one.

## 10. Credential Handling

`credential: github` in a settings file is a **reference name**, resolved once, at settings-load
time, via `AGENT_PLATFORM_MCP_CREDENTIAL_<NAME>` (environment variable — no new secret-storage
mechanism was built). A raw-looking secret placed where a reference was expected is never used as
the credential itself — it's just a (near-certainly non-matching) environment-variable-name
lookup key (tested explicitly, attack 8). The resolved value flows straight into the existing,
unmodified `MCPServerConfig.credential` field, which was already never serialized anywhere
(Phase 4/9/10). Verified this phase: credentials never appear in `GET /configuration`,
`/configuration/mcp`, or `/mcp/servers` response bodies (checked as full-response substring
absence, not a masked-placeholder check) — `test_no_route_ever_returns_a_credential_value`.

## 11. Platform API Contract

Audited, not rewritten. Sessions/Modes/Plans (list, retrieve, history, checkpoints, resume,
archive, revise/approve/reject) were already stable, tested contracts from Phase 9/10 — no
changes. "Change mode" and "validate mode transitions" have no new code because none is needed:
`OperatingMode` is immutable per session by explicit Phase 9 design (switching modes means
creating a new session), so there is nothing to mutate or validate beyond the existing
`OperatingMode(body.operating_mode)` check at session creation.

New this phase: `GET /configuration`, `GET /configuration/models`, `GET /configuration/mcp` — all
read-only, all behind the existing bearer-auth dependency, all delegating to `SettingsService`.
**No new mutation route was added.** The existing `PUT /mcp/servers/{server_id}/preferences`
(Phase 9, untouched) remains the only safe live-update path; broader configuration changes
(models, agent-behavior limits) require editing the settings file and restarting the backend —
stated plainly in §18, not silently omitted.

## 12. Serialization Contract

New serializers (`api_serialization.py`, same explicit-field-by-field discipline as every
existing one — never `vars()`/reflection): `serialize_configuration_view`,
`serialize_model_settings`, `serialize_available_models`, `serialize_stream_event`. Stable
representations already existed from Phase 9/10 for Session, Message, Plan, Checkpoint (and
"Specification" is deliberately represented by reference — `spec_version_label` embedded in
Plan/Checkpoint/Event payloads — never as a standalone resource, since no route needs one
independent of the plan/session it belongs to). Model/MCP Server/Configuration/Event are new or
extended this phase.

## 13. Event Contract

**Audited and found genuinely incomplete, then fixed additively.** `GET /sessions/{id}/events`
previously replayed only `EventLog.user_stream()` — plain conversational text
(`USER_REQUEST_RECEIVED`/`USER_MESSAGE`), because every structured event type
(`STATE_TRANSITION`, `PLAN_CREATED`, `SPEC_VERSION_CREATED`, ...) is emitted on the `"internal"`
stream in `orchestrator/core.py` (confirmed by reading every `_event_log.emit(...)` call site).
That stream assignment is **unchanged** — `orchestrator/core.py` was not touched, per the explicit
"do not redesign the Orchestrator" instruction. Instead, the route now additionally merges in
Phase 10's already-persisted `decisions` table (`PLAN_CREATED`/`PLAN_REVISED`/`PLAN_APPROVED`/
`PLAN_REJECTED`/`SPEC_VERSION_CREATED`/`PLAN_ARTIFACT_WRITTEN`/`PLAN_REVIEWED`) — itself only ever
recorded from already-typed route-handler results, never drained from internal reasoning — sorted
by timestamp alongside the plain-text events, normalized to one stable shape:
`{session_id, event_type, timestamp, payload, spec_version_label}`. `STATE_TRANSITION`/
`TOOL_INVOKED`/`MODEL_OUTPUT_INVALID`/internal reasoning remain excluded (regression-tested).
Session isolation is preserved (unchanged mechanism, re-tested).

## 14. Security Tests

All 16 attacks from the brief's list, split across two files:

- **`test_settings_security_adversarial.py`** (settings-layer, attacks 1–8, 10–12, 15–16): a
  12-way parametrized sweep proving no settings key can express a permission/role/security/spec/
  mode-policy change (structural absence, not a runtime check); an integration test proving
  settings-sourced MCP capabilities are still gated by live discovery intersection; path
  traversal/UNC via `agent_data_dir` rejected by `PlatformConfig`'s existing validation; a raw
  credential-shaped value never used as the actual secret; malformed YAML and unknown nested keys
  fail closed; invalid model identifiers degrade gracefully; and a structural AST-based test
  proving the `settings` package's own source **has no import** of `ToolGateway`/
  `PermissionEvaluator`/`FilesystemSandbox` at all — not just untested, structurally absent.
- **`test_configuration_api.py`** (API-layer, attacks 9, 13, 14): no route ever returns a
  credential value (checked across all four configuration/MCP routes); wrong bearer token is
  401 on every new route; no route parameter exists that could select a different workspace's
  configuration (a query-string injection attempt is simply ignored, the process stays bound to
  its one `project_root`).

## 15. Files Created

`src/agent_platform/settings/{__init__,schema,loader,credentials,builder,model_discovery,service}.py`
(7 modules) + 9 test files: `test_settings_loader.py`, `test_settings_credentials.py`,
`test_settings_builder.py`, `test_settings_model_discovery.py`, `test_settings_service.py`,
`test_settings_security_adversarial.py`, `test_backend_server_settings.py`,
`test_configuration_api.py`, `test_event_contract.py`.

## 16. Files Modified

| File | Nature of change |
|---|---|
| `backend_api.py` | `BackendServices` +2 fields (`settings`, `model_discovery_query_fn`); 3 new GET routes; `get_events` rewritten to merge structured decisions into the stream (§13). |
| `api_serialization.py` | +4 serializers. Zero changes to existing ones. |
| `server.py` | `build_services()` loads/merges settings, resolves effective values (explicit kwarg > settings file > hardcoded default), constructs and binds a real `PlatformConfig` for the first time (closes a Phase 10 gap — `PlatformConfig` was previously never actually constructed by the backend), passes `SettingsService` through. Regression-tested to be byte-identical with no settings file present. |
| `persistence/service.py` | +1 method, `get_decisions()` (read-back for §13's event merge). Zero changes to any existing method. |
| `tests/test_backend_api.py`, `tests/test_backend_api_persistence.py` | Fixture-only updates (`settings=` field added). No existing assertion changed. |

Zero changes to: `config.py`'s validation logic, every file under `security/`, `tools/gateway.py`,
`mcp/schemas.py`, `mcp/server_registry.py`, `mcp/gateway_tools.py`, `mcp/preferences.py`,
`orchestrator/core.py` and every other orchestrator module, `spec/versioning.py`, every
`persistence/*_store.py` module, `context/*.py`.

## 17. Phase 0–10 Regression Status

**Zero regressions.** All 1049 baseline tests pass unmodified in assertion content; the two
skips are the same pre-existing, environment-dependent (symlink-creation privilege) cases. Every
production-file modification in §16 is additive: a new optional field with a safe default, a new
route, a new method with no existing call sites, or (for `server.py`) a change proven
behaviorally identical when no settings file is present.

## 18. Known Limitations

- **No live PUT for models/agent-behavior settings** — a confirmed, deliberate scope decision
  (see §11). Changing them requires editing the settings file and restarting the backend.
- **Settings-derived MCP server configs are not automatically wired into a live, connected
  `MCPClient`.** `SettingsService.mcp_server_configs` produces trusted `MCPServerConfig` objects,
  but `BackendServices.mcp_servers`/`mcp_clients` are not auto-populated from them in this phase —
  doing so needs a real transport per server (command/args for stdio), which is schema not built
  here. `GET /configuration/mcp` reports configured policy; `GET /mcp/servers` (unchanged) reports
  only servers a caller explicitly wired with a real client, exactly as before this phase.
- **"Specification" has no standalone serializer/route** — represented by reference
  (`spec_version_label`) inside Plan/Checkpoint/Event payloads only, matching how `SpecStore`
  itself has never had a direct API-facing route.
- **CODE/EDIT progress events (Planning.../Implementing.../Testing...) are still not exposed** —
  those states transition on the `"internal"` `EventLog` stream inside `orchestrator/core.py`,
  which this phase deliberately did not touch (explicit "do not redesign the Orchestrator"
  instruction). This is a pre-existing gap, not introduced or worsened this phase, and is
  independent of Phase 10's separate finding that CODE/EDIT has no HTTP route at all yet.
- **Credential resolution is environment-variable-only** — no support for an OS keychain or
  another secret store; explicitly in scope per "do not build a custom secret-management system."

## 19. Exact Final Test Command

```
python -m pytest tests/ --ignore=tests/test_ollama_integration.py --ignore=tests/test_mcp_real_integration.py -v --tb=short
```

## 20. Exact Final Result

```
1140 passed, 2 skipped, 5 warnings in 30.99s
```

0 failed.

## 21. Git Confirmation

**No `git` command of any kind was run** at any point during this phase. Every file in §15/§16
was created or modified directly via file-editing tools only. Git remains entirely
human-controlled.

---

## CONFIGURATION IS PREFERENCE, NOT AUTHORITY

This is the one property every other claim in this report rests on, so it is stated once,
explicitly, here:

**Configuration cannot expand permissions or bypass security policy.** The `settings/` package's
own source code has no import of `ToolGateway`, `PermissionEvaluator`, or `FilesystemSandbox` —
not "doesn't call them in the paths we tested," but structurally absent from every module in the
package, verified by static AST analysis in a dedicated test. Everything `settings/` produces is
one of exactly two things: (1) inputs to `PlatformConfig.load()` and `MCPServerConfig`'s
constructor — the same trusted-configuration inputs a human editing Python literals would have
produced before this phase, still validated by those objects' own unmodified logic — or (2) a
read-only, credential-free dict for the new `GET /configuration*` routes. There is no third code
path. The full authority chain (`HARD SECURITY POLICY → OPERATING MODE → ROLE → TOOL PERMISSIONS
→ MCP CAPABILITY POLICY → USER CONFIGURATION/PREFERENCES`) is unchanged from Phase 0–10;
configuration sits at the very bottom, and every layer above it — all of `security/*.py`,
`tools/gateway.py`, `mcp/gateway_tools.py`'s discovery-intersection gate — was not modified by a
single line this phase. A settings file can narrow what's already permitted (disable an MCP
server, lower an iteration cap) and can never grant anything the layers above it didn't already
establish.
