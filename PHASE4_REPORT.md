# Phase 4 Report

## 1. Files created

All new — no existing Phase 0-3 production file was modified (this is
verified, not just claimed, in item 12's mirror-check below):

- `src/agent_platform/mcp/__init__.py`
- `src/agent_platform/mcp/schemas.py` — `MCPServerConfig`, `MCPResponse`
- `src/agent_platform/mcp/secrets.py` — `redact_secret_string`, `redact_secrets`
- `src/agent_platform/mcp/server_registry.py` — `MCPServerRegistry`
- `src/agent_platform/mcp/mock_transport.py` — `MockMCPTransport`, `TIMEOUT`, `MockServerFailure`
- `src/agent_platform/mcp/client.py` — `MCPClient`, `MCPTransport` protocol
- `src/agent_platform/mcp/gateway_tools.py` — `build_mcp_tool_specs`, `build_mcp_permission_grants`, `register_mcp_capabilities`
- `src/agent_platform/mcp/real_stdio_transport.py` — `RealMCPStdioTransport`
- `tests/test_mcp_schemas.py`, `test_mcp_secrets.py`, `test_mcp_server_registry.py`, `test_mcp_client.py`, `test_mcp_gateway_tools.py`, `test_mcp_adversarial.py`, `test_mcp_real_integration.py`
- `mcp_real_server_sandbox/sample.txt` — the isolated directory the real server was scoped to (not the real project workspace)

## 2. Files modified

**None.** Every piece of Phase 4 uses extension points that already
existed: `ToolRegistry.register()` and `PermissionEvaluator(sandbox,
tool_table=...)`. `orchestrator/core.py`, `tools/gateway.py`,
`tools/registry.py`, and `security/permission.py` are byte-for-byte
unchanged from Phase 3.

## 3. MCP architecture

`LLM → Orchestrator → MCP Gateway → MCP Client → MCP Server` is realized
as: **the MCP Gateway is the existing `ToolGateway`.** Every
`mcp.<server>.<capability>` call goes through the identical 6-step
pipeline `filesystem.write` and `test.run` already went through - schema
validation, permission evaluation via the same `PermissionEvaluator`,
precondition check, execute, structured observation, log. There is no
independent MCP authority. What's new sits entirely *behind* that
gateway, as the `execute` function a `ToolSpec` calls:
`MCPClient.call()` → the configured `MCPTransport` (mock or real). An
MCP response only ever leaves `MCPClient` as `MCPResponse.data`, a plain
dict; nothing in this codebase parses that content looking for
instructions.

`MCPServerConfig`/`MCPServerRegistry` hold trusted configuration only -
`MCPServerRegistry` has no `register`/`add`/`update` method at all
(verified by a test, not just documented). Registered tool capabilities
are the **intersection** of what a server's `discover()` claims and what
trusted config's `MCPServerConfig.capabilities` declares - discovery can
narrow, never expand, what gets registered.

## 4. Capability/role matrix

| Tool | Planner | Coder | Reviewer |
|---|---|---|---|
| `mcp.mock-docs.search` / `mcp.mock-docs.fetch` (mock, Task 4/5) | ALLOW | ALLOW | ALLOW |
| `mcp.real-fs.read_text_file` / `mcp.real-fs.list_directory` (real, Task 7) | ALLOW (grantable) | ALLOW | ALLOW |
| `mcp.real-fs.write_file` / `edit_file` / `move_file` / `create_directory` | **not registered** | **not registered** | **not registered** |

All three roles get identical grants for the read-only research/context
capabilities actually wired in this phase, matching the brief's "Planner:
approved research/context capabilities; Coder: approved implementation-
time research/context capabilities; Reviewer: approved read-only
research/context capabilities" - since every capability registered so
far is inherently read-only, there's no differentiation to make yet. The
real filesystem server's write-capable tools (`write_file`, `edit_file`,
`move_file`, `create_directory`) are **never included in trusted
config**, so they're never registered for any role, even though the real
server offers them and would execute them if called.

## 5. Mock MCP results

29 tests across Tasks 1-5, all passing, all deterministic, zero network:
- Schemas/secrets (9): immutability, redaction of exact-match secrets in nested structures.
- Server registry (5): get/list, empty registry, and the structural no-mutation-method proof.
- Client (8): discovery, successful call, malformed (non-dict) response, oversized response, timeout, server failure, unknown capability, discovery failure - every scenario the brief's MVP list named.
- Gateway tools (9): tool naming, discovery-vs-trusted-config intersection in both directions, per-role grants, reserved-argument rejection, non-serializable-argument rejection, credential redaction in a response, full registry+gateway wiring, unknown-capability handling.
- Adversarial (14): see item 7.

## 6. Real MCP integration results

Integrated exactly **one** real external server:
`@modelcontextprotocol/server-filesystem`, the official MCP reference
server, fetched via `npx -y` (the one network exception this phase, done
after explicit confirmation) and scoped to an **isolated sandbox
directory** (`mcp_real_server_sandbox/`), never the real project
workspace.

Verified empirically (not assumed from memory of the spec):
- Handshake: `initialize` → result with `protocolVersion`/`capabilities`/`serverInfo`, then `notifications/initialized`, then `tools/list`.
- The server exposes 14 tools total, including destructive ones (`write_file`, `edit_file`, `move_file`, `create_directory`) - all deliberately excluded from `MCPServerConfig.capabilities` for this integration; only `read_text_file` and `list_directory` were registered.
- **Application-level errors come back as a normal JSON-RPC result with `isError: true`**, not a JSON-RPC `error` field - a real protocol detail that would have been wrong to guess. `RealMCPStdioTransport` translates this correctly; `MCPClient` needed zero changes to handle it, since it already treats any raised exception from the transport as `status: "error"`.
- The real server independently enforces its own directory sandboxing (a path-traversal attempt to `../../../../Windows/win.ini` was rejected with `"Access denied - path outside allowed directories"`) - a nice defense-in-depth data point, though this architecture never relies on a third-party server's own sandboxing for safety.
- 5/5 real integration tests passed: tool discovery, curated-subset registration (proving write tools are excluded), a real read through the full gateway pipeline, a real application error (`ENOENT`) surfacing as a clean `status: "error"` rather than a crash, and git/shell tools confirmed still denied alongside the real server.

## 7. Adversarial test results

All 14 pass - every scenario the brief's "Security Tests" section named:

| Attempt | Result |
|---|---|
| Prompt injection ("ignore previous instructions...modify ~/.ssh...") | Inert - returned as plain text data, zero side effects, project directory unchanged |
| A downstream write "inspired by" injected text | Still denied by the real sandbox - no MCP fast path exists |
| Response claiming to change session mode / grant permissions | Inert - `git.commit` still denied afterward |
| Git write attempts (`add`/`commit`/`push`/`reset`/`rebase`/`init`) | All still denied, parametrized, 6/6 |
| Shell execution attempt | Denied |
| Response asking to register a new server / modify config | Inert - no such tool or method exists to call |
| Capability escalation via response content ("role: SYSTEM") | Inert - Planner still denied `filesystem.write` afterward |
| Secret extraction (response echoing a real credential value) | Redacted - `[REDACTED]` in the observation, raw value absent |
| Malformed arguments (reserved key `credential` from a caller) | Rejected at schema validation, before any MCP call was made |

## 8. Secret-redaction results

- `redact_secrets`/`redact_secret_string` (Task 1, 6 tests) walk nested
  dict/list/tuple structures and replace exact-match secret values with
  `[REDACTED]`.
- Applied at the MCP executor boundary (Task 4) to both `response.data`
  and `response.error` before either becomes part of an observation -
  proven with a real server credential value in Task 4's and Task 5's
  tests.
- **A server's own credential structurally never reaches caller-visible
  logging in the first place**: it lives only in `MCPServerConfig.credential`
  and is used only inside the client/transport layer, never passed as a
  caller argument, so it's never part of what the gateway logs as
  `arguments`.
- **Known gap, stated plainly**: argument-side redaction (a model typing
  a secret-looking string into, say, a search query) is not covered by
  this phase's code, since that would require touching `ToolGateway`'s
  logging in `_finish` - deliberately not done here to keep "no existing
  Phase 0-3 file modified" strictly true. This gap predates and extends
  beyond MCP (it would apply equally to a secret typed into a `git.log`
  argument or a `filesystem.write` content string), so it isn't
  MCP-specific and isn't solved by this phase.

## 9. Full deterministic test count

**645 passed, 0 failed, 0 skipped** (`python -m pytest tests/
--ignore=tests/test_ollama_integration.py
--ignore=tests/test_mcp_real_integration.py -q`) - 600 from Phase 0-3
plus 45 new deterministic MCP tests (Tasks 1-5), zero regressions. The
two pre-existing `PytestCollectionWarning`s (from Phase 3's
`TestRunValidator` naming) are unchanged and harmless.

Including the two real-network files (Ollama + real MCP), **650 passed**
in total across the whole project.

## 10. Known limitations

- Only one capability *type* is proven end-to-end: read-only research/
  context (mock `search`/`fetch`, real `read_text_file`/`list_directory`).
  No write-capable or credentialed-write MCP capability has been built or
  tested - none was requested this phase, and none should be added
  without a fresh, explicit review of what that would mean for the trust
  model.
- Real transport implementation covers exactly the stdio JSON-RPC shape
  `@modelcontextprotocol/server-filesystem` uses. Other transports (HTTP,
  SSE) or servers with different handshake quirks are not implemented -
  `MCPTransport` is a `Protocol`, so adding one is a new class, not a
  redesign, but it is not done here.
- Argument-side secret redaction gap - see item 8.
- The real server's own directory sandboxing was observed to work
  correctly, but this architecture never depends on it - if a future real
  server had weaker or no self-sandboxing, this design's guarantees would
  be unchanged, since containment here comes from curated trusted-config
  capabilities and the existing permission gateway, not from trusting the
  server.
- No orchestrator wiring was done (Phase 4's brief did not ask for it) -
  `register_mcp_capabilities` is ready to be called from wherever a
  future phase assembles the real orchestrator's registry/evaluator, but
  `orchestrator/core.py` does not currently call it.

## 11. Confirmation that MCP cannot bypass the orchestrator

Structural: there is no code path anywhere in `src/agent_platform/mcp/`
that touches the filesystem, git, or a subprocess directly - every MCP
capability's `execute` function does exactly one thing,
`client.call(capability, args)`, and returns the result as a plain dict.
Every one of those calls only happens after the exact same permission
check every other tool call goes through, in the same `ToolGateway`.

Adversarial (item 7): 14 tests attempting every listed bypass (filesystem
modification, shell execution, git commit/push, permission changes,
config modification, server registration, capability escalation, secret
extraction) via response *content* - all confirmed inert, subject to the
normal deterministic control plane.

## 12. Confirmation that no Git commands were run

No git command of any kind was run this session. The working tree
(Phase 0 through Phase 4, including this report) remains entirely
uncommitted and is the user's to review and commit at their discretion.
