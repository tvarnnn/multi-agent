import * as assert from "assert";
import * as fs from "fs";
import * as path from "path";
import { BackendClient } from "../../src/backendClient";
import { startFakeBackend, StartedFakeBackend } from "./testBackend";

/**
 * Spawns the REAL Python backend (test-fixtures/fake_model_server.py - a
 * real backend process, scripted FakeModelProvider instead of a real
 * Ollama connection, identical pattern to every deterministic test in the
 * Python suite) and drives it through the compiled BackendClient exactly
 * as the extension itself would. This is the test that actually proves
 * the TypeScript client and the Python backend agree on the wire
 * contract, not just that each side's own mocks are internally
 * consistent.
 */

suite("Backend integration (real process, scripted model)", () => {
  let backend: StartedFakeBackend;
  const workspaceRoot = path.resolve(__dirname, "../../../test-fixtures/sample-workspace");

  suiteSetup(async function () {
    this.timeout(20_000);
    // Phase 10 persistence is real and durable across processes (that's the
    // point) - this test fixture folder is reused across test runs, so its
    // .agent/agent.db (and any .agent/plans and .agent/context artifacts)
    // must be cleared first, or spec-version predictions from a PRIOR run
    // would still be rehydrated here.
    const agentDir = path.join(workspaceRoot, ".agent");
    fs.rmSync(agentDir, { recursive: true, force: true });
    backend = await startFakeBackend(workspaceRoot);
  });

  suiteTeardown(() => {
    backend?.kill();
  });

  test("create CHAT session and send a message", async () => {
    const { session_id } = await backend.client.createSession("CHAT");
    assert.ok(session_id);
    const result = await backend.client.postMessage(session_id, "hello");
    assert.strictEqual((result as { message: string }).message, "Hello from the test backend!");
  });

  test("list sessions includes the created session", async () => {
    const { session_id } = await backend.client.createSession("CHAT");
    const { sessions } = await backend.client.listSessions();
    assert.ok(sessions.some((s) => s.session_id === session_id));
  });

  test("PLAN workflow: draft -> revise -> approve", async () => {
    const { session_id } = await backend.client.createSession("PLAN", "spec-vscode-1");
    const drafted = await backend.client.postMessage(session_id, "build a widget");
    assert.strictEqual((drafted as { status: string }).status, "DRAFT");

    const revised = await backend.client.revisePlan(session_id, "add a second widget");
    assert.strictEqual(revised.status, "REVISED");

    const approved = await backend.client.approvePlan(session_id);
    assert.strictEqual(approved.spec_version_label, "spec-vscode-1-v1");
  });

  test("plan artifact_path is returned for Open/Reveal Plan", async () => {
    const { session_id } = await backend.client.createSession("PLAN", "spec-vscode-2");
    const drafted = await backend.client.postMessage(session_id, "build a gadget");
    assert.ok((drafted as { artifact_path: string | null }).artifact_path);
  });

  test("session resume returns reconstructed context with authoritative mode", async () => {
    const { session_id } = await backend.client.createSession("CHAT");
    await backend.client.postMessage(session_id, "hello");
    const resumed = await backend.client.resumeSession(session_id);
    assert.strictEqual(resumed.operating_mode, "CHAT");
  });

  test("archive session marks it archived", async () => {
    const { session_id } = await backend.client.createSession("CHAT");
    const result = await backend.client.archiveSession(session_id);
    assert.strictEqual(result.status, "ARCHIVED");
  });

  test("configuration and MCP routes return safe data with no credential field", async () => {
    const config = await backend.client.getConfiguration();
    assert.ok(config.models);
    assert.ok(!JSON.stringify(config).includes("credential"));
  });

  test("wrong token is rejected", async () => {
    const baseUrl = (backend.client as unknown as { baseUrl: string }).baseUrl;
    const wrongClient = new BackendClient(baseUrl, "wrong-token");
    await assert.rejects(() => wrongClient.listSessions());
  });
});
