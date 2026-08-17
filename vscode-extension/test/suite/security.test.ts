import * as assert from "assert";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { BackendClient, BackendError } from "../../src/backendClient";
import { isIncomingMessage } from "../../src/sessionPanel";
import { startFakeBackend, StartedFakeBackend } from "./testBackend";

/**
 * Extension-side security tests. The backend is where authority actually
 * lives (PermissionEvaluator/FilesystemSandbox/ToolGateway - already
 * covered by an extensive adversarial suite in tests/), so these prove
 * the narrower, extension-specific claim: nothing in this extension's own
 * code can expand what the backend already grants, and malformed/hostile
 * input at the extension boundary is handled safely rather than crashing
 * or being blindly forwarded. Uses its own dedicated workspace fixture
 * (not sample-workspace) so it never shares persisted state with the
 * other suites.
 */

suite("Webview message validation", () => {
  test("well-formed messages are accepted", () => {
    assert.ok(isIncomingMessage({ type: "sendMessage", text: "hello" }));
    assert.ok(isIncomingMessage({ type: "approvePlan" }));
    assert.ok(isIncomingMessage({ type: "refresh" }));
  });

  test("malicious/unexpected shapes are rejected, never forwarded as a command", () => {
    assert.strictEqual(isIncomingMessage(null), false);
    assert.strictEqual(isIncomingMessage(undefined), false);
    assert.strictEqual(isIncomingMessage("approvePlan"), false);
    assert.strictEqual(isIncomingMessage({ type: "__proto__" }), false);
    assert.strictEqual(isIncomingMessage({ type: "executeShellCommand", cmd: "rm -rf /" }), false);
    assert.strictEqual(isIncomingMessage({}), false);
    assert.strictEqual(isIncomingMessage([]), false);
    assert.strictEqual(isIncomingMessage(42), false);
  });
});

suite("Security", () => {
  let backend: StartedFakeBackend;
  const workspaceRoot = fs.mkdtempSync(path.join(os.tmpdir(), "agent-platform-security-test-"));

  suiteSetup(async function () {
    this.timeout(20_000);
    backend = await startFakeBackend(workspaceRoot);
  });

  suiteTeardown(() => backend?.kill());

  test("invalid operating mode is rejected by the backend, not silently accepted", async () => {
    await assert.rejects(
      () => backend.client.createSession("NOT_A_REAL_MODE" as never),
      (err: unknown) => err instanceof BackendError && err.status === 400,
    );
  });

  test("unauthorized (unknown) session id is rejected, not defaulted to some other session", async () => {
    await assert.rejects(
      () => backend.client.getSession("aaaaaaaaaaaaaaaaaaaaaaaa"),
      (err: unknown) => err instanceof BackendError && err.status === 404,
    );
  });

  test("path-traversal-shaped session id is rejected, not resolved as a filesystem path", async () => {
    await assert.rejects(
      () => backend.client.getSession("..%2F..%2F..%2Fetc%2Fpasswd"),
      (err: unknown) => err instanceof BackendError && (err.status === 400 || err.status === 404),
    );
  });

  test("malformed API payload (missing required field) is rejected with 4xx, not a crash", async () => {
    await assert.rejects(
      () => backend.client.createSession(undefined as never),
      (err: unknown) => err instanceof BackendError && err.status >= 400 && err.status < 500,
    );
  });

  test("arbitrary/unknown endpoint access returns 401 before 404 - auth is checked first", async () => {
    // BackendClient only exposes known routes; simulate "arbitrary endpoint" via a raw fetch
    // through the same base URL/token the extension would use, proving auth-before-routing
    // holds even for a path this client never constructs itself.
    const anyClient = backend.client as unknown as { baseUrl: string };
    const resp = await fetch(`${anyClient.baseUrl}/totally/made/up/route`, {
      headers: { Authorization: "Bearer wrong-token" },
    });
    assert.strictEqual(resp.status, 401);
  });

  test("wrong bearer token cannot read configuration (no credential leak path exists to test around)", async () => {
    const anyClient = backend.client as unknown as { baseUrl: string };
    const wrongClient = new BackendClient(anyClient.baseUrl, "wrong-token");
    await assert.rejects(() => wrongClient.getConfiguration());
  });

  test("MCP preference update cannot request an unconfigured server (no capability escalation path)", async () => {
    await assert.rejects(
      () => backend.client.setMcpPreferences("server-that-does-not-exist", { enabled: true }),
      (err: unknown) => err instanceof BackendError && err.status === 404,
    );
  });
});
