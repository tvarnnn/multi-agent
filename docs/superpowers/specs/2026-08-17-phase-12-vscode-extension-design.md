# Phase 12 Design: VS Code Agent Platform Extension

Status: APPROVED (brief mandates proceeding directly to implementation — see "Do not stop here")

## 0. Audit summary (what actually exists, verified against current source, not the Phase 11 report)

Route inventory confirmed by grepping `backend_api.py` directly (19 routes):
`POST /sessions`, `POST /sessions/{id}/messages`, `GET /sessions/{id}/events` (SSE),
`GET /sessions/{id}/plan`, `POST /sessions/{id}/plan/revise`, `POST /sessions/{id}/plan/approve`,
`POST /sessions/{id}/plan/reject`, `GET /sessions/{id}/state`, `GET /sessions`,
`GET /sessions/{id}`, `GET /sessions/{id}/history`, `GET /sessions/{id}/checkpoints`,
`POST /sessions/{id}/resume`, `POST /sessions/{id}/archive`, `GET /configuration`,
`GET /configuration/models`, `GET /configuration/mcp`, `GET /mcp/servers`,
`PUT /mcp/servers/{server_id}/preferences`.

Every response shape used below is copied directly from the current `api_serialization.py` (read
in full this session), not inferred from documentation. `server.py::run()` already spawns a
loopback-only uvicorn process and prints exactly one JSON line to stdout,
`{"port": <int>, "token": "<32-byte urlsafe>"}` — this was *designed* for exactly the "VS Code
extension spawns this process" use case (see `server.py`'s own module docstring, written in
Phase 9). **Existing capability confirmed, not assumed:** CODE/EDIT sessions still have no HTTP
route (`POST /sessions/{id}/messages` 409s for them) — a pre-existing, documented gap from Phase
10/11, unchanged by this phase per "no backend rewrite unless a contract is genuinely missing and
the smallest additive fix is made" (§ below resolves this with the smallest viable addition).

Environment audit performed before any code was written: Node v24.14.0, npm 11.9.0, VS Code CLI
1.133.0, all present; npm registry reachable (166ms ping). No missing prerequisite blocks this
phase.

## 1. Goals

A real, installable VS Code extension that is a thin client over the existing Python backend:
workspace detection, backend lifecycle (spawn-or-connect), a sidebar for session/mode navigation,
one Webview panel for rich session content (chat/plan/events), full Plan Mode integration
(draft/revise/approve/reject, open/reveal the Markdown artifact), session management
(create/list/resume/archive), read-only configuration/model/MCP visibility plus the one existing
safe mutation (MCP preference narrowing), and packaging as a locally-installable VSIX.

## 2. Non-goals

A second orchestrator, permission system, sandbox, MCP gateway, persistence layer, or
configuration authority. Marketplace publication. Cloud infrastructure. A TypeScript re-
implementation of Coder/Reviewer. Model download/installation. The "giant stress test" project
(explicitly deferred). React or any bundler — the Webview is plain HTML/CSS/vanilla JS.

## 3. Existing architecture (reused, not rebuilt)

Everything in §0. The extension is a pure HTTP/SSE client of the FastAPI backend; Python remains
the sole authority for permissions, sandboxing, MCP, persistence, and configuration.

## 4. Extension architecture — chosen: Hybrid (Option C)

**Compared:**
- **Option A (Webview-only sidebar):** maximum visual flexibility, but a Webview-hosted sidebar
  has weaker keyboard/accessibility integration than native `TreeView`, and CSP/message-passing
  discipline has to be re-litigated for the *entire* UI surface, not just the rich content areas.
- **Option B (native views only):** best VS Code integration and lowest risk, but Markdown plan
  rendering and a scrolling chat/event transcript are legitimately awkward to build well as pure
  `TreeItem`s.
- **Option C (chosen):** a native `TreeView` (Activity Bar container) for structural
  navigation/state (workspace, session, mode, session list) — fast, accessible, zero CSP surface
  — plus exactly **one** Webview panel ("Agent Platform Session") for the content that genuinely
  needs rich rendering (chat transcript, plan Markdown preview, live event log, mode-specific
  action buttons). This minimizes Webview attack surface (one panel, one message contract) while
  still getting a real chat/plan experience. Settings are exposed via native `QuickPick`/
  `InputBox` flows, not a second Webview — the backend has exactly one live-mutable setting (MCP
  preference narrowing) plus read-only views, which don't justify a dedicated Webview's CSP
  surface and message-validation cost.

## 5. Backend communication

`src/backendClient.ts` is the **only** module that makes HTTP/SSE calls. Uses Node 24's native
`fetch` (no new HTTP dependency). Every request sends `Authorization: Bearer <token>`. SSE is
consumed by reading `GET /sessions/{id}/events`'s response body as a stream and parsing
`data: <json>\n\n` frames manually (the backend's SSE format is a fixed, already-known shape —
a full EventSource polyfill dependency isn't justified for it). All request/response shapes are
typed in `src/types.ts`, copied field-for-field from `api_serialization.py` — if a field isn't in
the Python serializer, it isn't in the TypeScript type either.

## 6. Local deployment

`src/backendProcess.ts` spawns `python -m agent_platform.server --workspace-root <detected
workspace> --port 0` via `child_process.spawn`, reads the single startup JSON line
(`{port, token}`) from stdout, stores the token in `vscode.SecretStorage` (never in a webview,
never logged), and builds `http://127.0.0.1:<port>` as the base URL. `agentPlatform.pythonPath`
(default `"python"`) is configurable for environments where `python` isn't the right interpreter
name.

## 7. Remote SSH deployment

**Design, not yet verified in this environment (no second machine reachable) — see §29 for the
explicit VERIFIED/NOT VERIFIED split.** The architecture requires no Remote-SSH-specific code:
when VS Code Remote-SSH is active, the *extension host* — and therefore any `child_process` it
spawns — already runs on the remote machine, not the local client. `backendProcess.ts`'s
`child_process.spawn` call is unaware of Remote-SSH entirely; it just spawns "python" in whatever
process the extension host is running in, which Remote-SSH has already relocated. Workspace
detection uses `vscode.workspace.workspaceFolders[0].uri.fsPath`, which VS Code itself resolves
to the remote filesystem path under Remote-SSH — no local/remote branching needed in extension
code. An **External** connection mode (`agentPlatform.backendUrl` +
`agentPlatform.backendToken` settings, non-empty) is also provided as an escape hatch for a
backend started manually/out-of-band on the remote host.

## 8. Sidebar architecture

One Activity Bar container ("Agent Platform"), one `TreeView` with sections: Workspace (current
folder name), Session (id/status/mode of the active session, or "No active session"), Mode
(current mode + a command to change it), a `---` separator, Sessions (a live list from
`GET /sessions`, each a `TreeItem` with commands: Resume, Archive, Open), and Settings (opens the
QuickPick-based settings flow). Selecting a session (or creating one) opens the one Webview panel.

## 9. Mode switching

Mode is chosen via `QuickPick` (`Chat`/`Plan`/`Code`/`Edit`/`Review`) and only ever takes effect
by creating a **new** session with that `operating_mode` — matching the backend's own Phase 9
design (`OperatingMode` immutable per session). The extension never assumes a selected mode
implies any permission; every request still goes through the backend's own validation, and a 409
`WRONG_MODE`/`NOT_FOUND` response is surfaced as a normal error, not swallowed.

## 10. Session management

Create (`POST /sessions`), list (`GET /sessions`), select (loads detail via `GET /sessions/{id}`
+ history via `GET /sessions/{id}/history`, opens the Webview), resume
(`POST /sessions/{id}/resume`), archive (`POST /sessions/{id}/archive`). Only safe fields
(`session_id`, `operating_mode`, `status`, `spec_id`, `updated_at`, ...) are ever displayed —
exactly the fields `serialize_session_summary`/`serialize_session_detail` already expose; no
SQLite access, no raw persistence internals.

## 11. Plan integration

Full workflow per the brief's diagram, all backed by existing routes: draft
(`POST /messages` on a PLAN session), inspect (`GET /sessions/{id}/plan`), revise
(`POST .../plan/revise`), approve (`POST .../plan/approve`), reject (`POST .../plan/reject`). The
Webview renders `StructuredPlan` fields directly (objective, requirements, steps, acceptance
criteria, reviewer feedback) — never re-parses the Markdown artifact as data, matching the
backend's own "Markdown is never authoritative" principle. `Open Plan`/`Reveal Plan` use the
`artifact_path` string the backend already returns in `PlanResult`/`PlanApprovalResult` —
resolved against the *known, extension-detected* workspace root via `vscode.Uri.joinPath`, never
treated as a free-standing absolute path from untrusted input (see §21).

## 12–14. Code / Edit / Review integration

**Contract gap found and resolved with the smallest additive backend change** (per "no backend
rewrite" — identify the gap, verify Phase 11 doesn't already cover it, make the smallest additive
fix, test it): CODE/EDIT sessions have no HTTP route to actually run. Adding one is required for
Code/Edit to be reachable from the UI at all. The smallest additive fix: extend the *existing*
`POST /sessions/{session_id}/messages` handler with two more branches
(`OperatingMode.CODE`/`OperatingMode.EDIT` → call `Orchestrator.run()`/`amend_requirements()`),
mirroring the CHAT/PLAN/REVIEW branches already there byte-for-byte in structure, plus a new
`serialize_orchestrator_result()` in `api_serialization.py` for `OrchestratorResult`
(`final_state`, `spec_id`, `summary`) — a fourth explicit-field serializer next to the three that
already exist for the other three result types. No change to `Orchestrator`, `ToolGateway`,
`PermissionEvaluator`, or the state machine — this only adds a transport branch, exactly like the
three branches already there. Tested exactly like the other three (existing
`test_backend_api.py` conventions). REVIEW mode already has a full route
(`run_review`/`ReviewResult`) — no gap there. The extension surfaces `final_state`/`summary`
safely; per the Phase 10 known limitation, restarting mid-Code-loop still isn't resumable to an
exact position — the UI reflects that honestly (resume shows history/checkpoint, "continue" means
a fresh follow-up request, not silently pretending otherwise).

## 15. Configuration UI

`QuickPick` reading `GET /configuration` (models, agent-behavior effective values, MCP policy) —
read-only, since the backend has no live-mutation route for those (Phase 11 known limitation,
unchanged). The one live-mutable setting, MCP capability/enablement narrowing, is exposed via
`QuickPick` + `PUT /mcp/servers/{id}/preferences` — the existing, unmodified route.

## 16. Model management

`GET /configuration/models` rendered read-only (identifier, availability). No install/download
affordance exists anywhere in the UI — there is no backend route for it either.

## 17. MCP management

`GET /configuration/mcp` (policy: enabled/transport/capabilities, no credential field — the
Python serializer already omits it, so there is nothing for the extension to accidentally
display) plus `GET /mcp/servers` (live/connected view, unchanged Phase 9 route) and the existing
preference-narrowing mutation.

## 18. Event streaming

Consumes the Phase 11-enriched `GET /sessions/{id}/events` stream as-is
(`{session_id, event_type, timestamp, payload, spec_version_label}`). The Webview switches on
`event_type` for icon/styling but renders **unknown** event types generically (raw `event_type` +
`payload` as text) rather than dropping them — satisfies "tolerate unknown future event types"
without a second event system.

## 19. Error handling

A single `BackendError` type from `backendClient.ts` (status code + parsed `{error, code}` body
where available) is caught at every call site and shown via `vscode.window.showErrorMessage` with
the backend's own message text — never a raw stack trace, never swallowed silently. Distinct
handling for: connection refused (backend not running → offer to start it), 401 (token
mismatch/stale → offer to restart the managed backend), 404 (session not found/archived), 409
(wrong mode/lifecycle conflict), and SSE stream drop (offer to reconnect/re-fetch events).

## 20. Authentication

The bearer token lives only in `vscode.SecretStorage` and in-memory in `backendClient.ts`; it is
never included in any Webview `postMessage`, never logged, never written to a workspace file.

## 21. Webview security

Strict CSP (`default-src 'none'; script-src 'nonce-<random>'; style-src <webview.cspSource>`), a
fresh nonce per render, no remote script/style sources, no inline `onclick` handlers (all
listeners attached in the bundled script). The Webview **never** makes its own HTTP calls — every
backend interaction goes `Webview → postMessage → extension host → backendClient.ts → backend`,
so Webview-supplied content can only ever *request* an operation, never perform one; the extension
host re-validates the message shape (a small discriminated-union `WebviewMessage` type) before
acting on it, and the backend independently re-validates and authorizes everything regardless of
what the extension host asked for. Artifact paths from the backend are joined against the known
workspace `Uri`, never opened as a raw string from Webview state (§11).

## 22. Workspace handling

`vscode.workspace.workspaceFolders` — zero folders → sidebar shows "No workspace open" and
disables session creation; exactly one → used directly; more than one → the first root is used
and a visible warning is shown that multi-root isn't safely supported yet (the backend binds one
process to one `project_root`; picking the "active" root among several bidirectionally would need
new backend-side multi-workspace routing that doesn't exist and is out of scope — documented
honestly in §31, not silently ignored).

## 23. Packaging

`@vscode/vsce package` → `agent-platform-vscode-<version>.vsix`. `.vscodeignore` excludes
`src/**/*.ts`, `test/**`, `node_modules/**` except what's needed at runtime (none — no runtime
npm dependencies, only devDependencies, since the extension uses only Node/VS Code built-ins).

## 24. Testing

`@vscode/test-electron` launches a **real** VS Code instance and runs Mocha suites against the
actual Extension API (`vscode.extensions`, `vscode.commands.executeCommand`, etc.) — not a mock
of the API. Suites cover activation, command registration, workspace detection, and (using a
**real** spawned Python backend with `FakeModelProvider`, exactly like every Python-side
deterministic test) session creation → plan draft → revise → approve → resume, proving the
TypeScript client and the Python backend actually agree on the wire contract, not just that each
side's own mocks are internally consistent.

## 25. Known limitations

CODE/EDIT resume still can't restore exact mid-loop position (Phase 10, unchanged, now reachable
from the UI via §12–14's new route branch but honestly labeled). No live mutation of
models/agent-behavior settings (Phase 11, unchanged). Multi-root workspaces use only the first
root (§22). Remote SSH is architecturally supported but not verified in this environment (§7, §29).

## 26. Self-review gate (performed before implementation began)

**Architecture.** Extension-only-a-client: confirmed — `backendClient.ts` is the sole HTTP/SSE
call site; nothing else in the extension reaches the network. Python authoritative: confirmed —
every mutating action is a backend call, none are computed locally. Existing APIs reused:
confirmed — 19 of 20 required operations map to existing routes; exactly one gap (CODE/EDIT) gets
the smallest additive fix (§12–14), not a rewrite. No duplicate systems: confirmed by design (no
local session store, no local permission logic, no local MCP client).

**Security.** UI state cannot bypass authorization — every request is independently
authenticated/authorized by the backend regardless of what the UI believes the current mode/
session is. Webview messages cannot trigger privileged behavior without validation — the
extension host validates message shape before translating to a backend call, and the backend
re-validates independently of that. Credentials cannot reach the UI — the Python serializers
already omit them at the source (verified in §0's audit), and the bearer token itself never
enters Webview state. Workspace selection cannot bypass sandboxing — the extension only ever
passes the VS Code-resolved workspace path as `--workspace-root`; `FilesystemSandbox` (unchanged,
Python-side) still enforces containment independent of what the extension claims. Configuration
cannot bypass permissions — no settings UI exists for anything beyond the existing narrowing-only
MCP preference route. MCP capabilities cannot be expanded through UI input — same route, same
narrowing-only guarantee, unchanged.

**API.** All required UI operations supported after the one additive fix (§12–14). Serializers
safe — audited directly from source in §0, no credential field exists to leak. Events sufficient
— §18. New endpoint genuinely necessary — yes, exactly one, justified and minimal.

**UX.** Plan → Review → Approve → Code → Test → Review → Fix → Complete is reachable end to end
once §12–14's fix lands (verified live in §29, not just asserted here).

**Persistence.** Sessions resumable — `POST /sessions/{id}/resume`, unchanged Phase 10 route.
UI recovers after backend restart — the Sessions list is re-fetched from `GET /sessions` on
reconnect, not cached client-side authority. Plan/spec state displayed accurately — read directly
from `GET /sessions/{id}/plan`/`GET /sessions/{id}` on each view, never inferred.

**Remote.** Architecturally compatible per §7; empirically not verified in this environment — see
§29, reported as NOT VERIFIED, not claimed.

**Scope.** Nothing beyond Phase 12's stated surface was added; the one backend change is the
minimum needed to make an already-designed capability (Code/Edit) reachable, not a new capability.
No stress-test scaffolding was started.

**Testing.** `@vscode/test-electron` real-instance tests are feasible in this environment (Node/
npm/VS Code CLI confirmed present, npm registry reachable) and packaging via `@vscode/vsce` needs
no new justification beyond "this is how VS Code extensions are packaged" — there is no
alternative stdlib/existing-dependency path for it.
