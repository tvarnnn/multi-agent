# Phase 9 Backend Planning Mode Implementation Plan

> **For agentic workers:** Execute inline with strict red-green-refactor cycles. Git commands are prohibited for this project.

**Goal:** Implement Backend Spec A for authenticated, sandboxed Planning Mode without changing the Phase 0-8 Code/Edit state machine.

**Architecture:** Add `OperatingMode` as an immutable Orchestrator session dimension enforced by the existing `PermissionEvaluator` and propagated through the existing `ToolGateway`. Planning state, artifacts, MCP research preferences, and the local FastAPI transport remain additive adapters around the existing Orchestrator, sandbox, MCP registry, and SpecStore authorities.

**Tech Stack:** Python 3.12, dataclasses, FastAPI 0.119.1, uvicorn 0.38.0, pytest.

## Global Constraints

- Backend Spec A only; no VS Code implementation.
- Do not run Git commands.
- Reject invalid `spec_id` values without normalization or transformation.
- Every Orchestrator-owned gateway invocation explicitly passes its immutable `OperatingMode`.
- Reuse `FilesystemSandbox.authorize`; do not add path-prefix containment logic.
- Draft/revised plans do not touch `SpecStore`; only explicit user approval creates a version.
- Markdown is audit documentation and is never read as authority.
- Coder never participates in Plan Mode; Reviewer cannot write plan artifacts.

---

### Task 1: Operating-mode authority and propagation

**Files:**
- Create: `src/agent_platform/security/mode_policy.py`
- Modify: `src/agent_platform/security/enums.py`, `src/agent_platform/security/permission.py`, `src/agent_platform/tools/gateway.py`, `src/agent_platform/orchestrator/core.py`
- Test: `tests/test_operating_mode_policy.py`, `tests/test_orchestrator_operating_mode.py`, `tests/test_plan_mode_sandbox.py`

- [ ] Write policy-matrix, compatibility, explicit propagation, role-denial, and scoped-plan-path tests.
- [ ] Run targeted tests and confirm failures identify missing `OperatingMode` behavior.
- [ ] Implement the enum, immutable policies, evaluator gate, gateway forwarding, and explicit Orchestrator arguments.
- [ ] Re-run targeted tests and the deterministic regression suite.

### Task 2: Structured planning contracts and rendering

**Files:**
- Create: `src/agent_platform/orchestrator/plan_schemas.py`, `src/agent_platform/orchestrator/plan_markdown.py`
- Test: `tests/test_plan_schemas.py`, `tests/test_plan_markdown.py`

- [ ] Write valid/malformed parser tests, strict `spec_id` tests, and a literal deterministic Markdown snapshot.
- [ ] Run targeted tests and confirm expected missing-contract failures.
- [ ] Implement strict typed parsers, structured errors, exact identifier validation, and pure rendering.
- [ ] Re-run targeted tests and regressions.

### Task 3: Plan lifecycle and bounded research

**Files:**
- Create: `src/agent_platform/orchestrator/plan_artifacts.py`
- Modify: `src/agent_platform/orchestrator/core.py`, model provider/fake provider contracts, context integration, events, config
- Test: `tests/test_orchestrator_plan_mode.py`

- [ ] Write failing tests for draft, clarification, malformed output, allowed/denied/bounded research, one reviewer pass, revision, explicit approval, rejection, immutability, history, and Markdown non-authority.
- [ ] Implement the smallest Orchestrator additions using the existing gateway, sandbox, event log, context builder, and SpecStore.
- [ ] Prove Coder is structurally unused and Reviewer writes are denied.
- [ ] Run targeted and full deterministic suites.

### Task 4: MCP preference narrowing

**Files:**
- Create: `src/agent_platform/mcp/preferences.py`
- Modify: `src/agent_platform/mcp/gateway_tools.py`
- Test: `tests/test_mcp_preferences.py`

- [ ] Write failing intersection-only and credential-omission tests.
- [ ] Implement in-memory preferences whose effective capabilities are discovered intersect trusted intersect enabled.
- [ ] Run targeted and full deterministic suites.

### Task 5: Authenticated localhost API and SSE

**Files:**
- Create: `src/agent_platform/server.py`, `src/agent_platform/backend_api.py`, `src/agent_platform/api_serialization.py`
- Test: `tests/test_backend_api.py`, `tests/test_backend_server.py`

- [ ] Write failing auth-before-state, route/mode, error-envelope, explicit serialization, SSE isolation, and MCP settings tests.
- [ ] Implement a thin FastAPI session adapter that calls only Orchestrator/state services and binds uvicorn to `127.0.0.1` with port `0` and an in-memory random token.
- [ ] Verify startup output, authenticated communication, and absence of secrets/private/internal events.
- [ ] Run targeted and full deterministic suites.

### Task 6: Final verification

- [ ] Run all Phase 9 targeted tests.
- [ ] Run `python -m pytest tests/ --ignore=tests/test_ollama_integration.py --ignore=tests/test_mcp_real_integration.py -v --tb=short` and record exact totals.
- [ ] Start the backend and verify authenticated loopback communication.
- [ ] Audit created/modified files through filesystem inspection only and confirm no Git command was run.
