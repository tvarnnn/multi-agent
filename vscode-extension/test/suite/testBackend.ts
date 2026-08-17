import * as cp from "child_process";
import * as path from "path";
import * as readline from "readline";
import { BackendClient } from "../../src/backendClient";
import { waitUntilAcceptingConnections } from "../../src/backendProcess";

/**
 * Shared helper for every test suite that needs a REAL backend process
 * (scripted FakeModelProvider) - reuses the real, fixed
 * waitUntilAcceptingConnections from backendProcess.ts instead of each
 * test file hand-duplicating spawn logic. A previous version of this
 * duplication is exactly how the startup race (backendProcess.ts's own
 * fix) went untested in two of the three places that needed it.
 */
export interface StartedFakeBackend {
  client: BackendClient;
  kill: () => void;
}

export function startFakeBackend(workspaceRoot: string): Promise<StartedFakeBackend> {
  const script = path.resolve(__dirname, "../../../test-fixtures/fake_model_server.py");
  const child = cp.spawn(
    "python",
    [script, "--workspace-root", workspaceRoot, "--sandbox-root", workspaceRoot, "--port", "0"],
    { windowsHide: true },
  );
  return new Promise((resolve, reject) => {
    const rl = readline.createInterface({ input: child.stdout });
    const timeout = setTimeout(() => {
      rl.close();
      reject(new Error("fake backend did not print a startup line within 15s"));
    }, 15_000);
    let stderrOutput = "";
    child.stderr.on("data", (chunk: Buffer) => {
      stderrOutput += chunk.toString("utf-8");
    });
    child.once("error", (err) => {
      clearTimeout(timeout);
      reject(err);
    });
    child.once("exit", (code) => {
      clearTimeout(timeout);
      if (code !== null && code !== 0) {
        reject(new Error(`fake backend exited early (code ${code}): ${stderrOutput.slice(0, 2000)}`));
      }
    });
    rl.once("line", (line) => {
      clearTimeout(timeout);
      rl.close();
      const { port, token } = JSON.parse(line) as { port: number; token: string };
      const baseUrl = `http://127.0.0.1:${port}`;
      waitUntilAcceptingConnections(baseUrl, token)
        .then(() => resolve({ client: new BackendClient(baseUrl, token), kill: () => child.kill() }))
        .catch(reject);
    });
  });
}
