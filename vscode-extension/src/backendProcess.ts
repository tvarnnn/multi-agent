/**
 * Spawns and manages the Python backend child process (managed connection
 * mode) or validates an already-configured external backend (external
 * mode). This is the ONLY module that touches child_process. Under VS
 * Code Remote-SSH the extension host - and therefore this spawn call -
 * already runs on the remote machine; no Remote-SSH-specific branching
 * is needed here (see design doc §7).
 */
import * as cp from "child_process";
import * as readline from "readline";

export interface BackendConnection {
  baseUrl: string;
  token: string;
}

export interface StartupLine {
  port: number;
  token: string;
}

export function parseStartupLine(line: string): StartupLine {
  const parsed = JSON.parse(line) as Partial<StartupLine>;
  if (typeof parsed.port !== "number" || typeof parsed.token !== "string") {
    throw new Error(`malformed backend startup line: ${line}`);
  }
  return { port: parsed.port, token: parsed.token };
}

/**
 * The startup JSON line is printed before uvicorn's socket is actually
 * listening (bind_loopback_socket() only binds; server.run(sockets=...)
 * is what starts listening) - a real, pre-existing race the Python test
 * suite already works around by polling `server.started` directly. This
 * extension has no access to that in-process flag, so it polls the one
 * thing it can observe: a real HTTP request actually succeeding.
 */
export async function waitUntilAcceptingConnections(
  baseUrl: string,
  token: string,
  timeoutMs = 5_000,
  intervalMs = 50,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastError: unknown;
  while (Date.now() < deadline) {
    try {
      await fetch(`${baseUrl}/sessions`, { headers: { Authorization: `Bearer ${token}` } });
      return;
    } catch (err) {
      lastError = err;
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
  }
  throw new Error(
    `backend did not start accepting connections at ${baseUrl} within ${timeoutMs}ms: ${
      lastError instanceof Error ? lastError.message : String(lastError)
    }`,
  );
}

export class ManagedBackendProcess {
  private child: cp.ChildProcess | undefined;

  get isRunning(): boolean {
    return this.child !== undefined && this.child.exitCode === null;
  }

  async start(pythonPath: string, workspaceRoot: string, cwd: string): Promise<BackendConnection> {
    if (this.isRunning) {
      throw new Error("backend process is already running");
    }
    // --sandbox-root is set equal to --workspace-root so the backend's
    // FilesystemSandbox boundary is exactly the folder the user opened in
    // VS Code - never widened to its sibling directories (see
    // server.py::main()'s --sandbox-root flag, added for this purpose).
    const child = cp.spawn(
      pythonPath,
      [
        "-m",
        "agent_platform.server",
        "--workspace-root",
        workspaceRoot,
        "--sandbox-root",
        workspaceRoot,
        "--port",
        "0",
      ],
      { cwd, windowsHide: true },
    );
    this.child = child;

    const startupLine = await new Promise<string>((resolve, reject) => {
      const rl = readline.createInterface({ input: child.stdout! });
      const timeout = setTimeout(() => {
        rl.close();
        reject(new Error("backend did not print a startup line within 15s"));
      }, 15_000);
      let stderrOutput = "";
      child.stderr?.on("data", (chunk: Buffer) => {
        stderrOutput += chunk.toString("utf-8");
      });
      rl.once("line", (line) => {
        clearTimeout(timeout);
        rl.close();
        resolve(line);
      });
      child.once("error", (err) => {
        clearTimeout(timeout);
        reject(err);
      });
      child.once("exit", (code) => {
        clearTimeout(timeout);
        reject(new Error(`backend process exited early (code ${code}): ${stderrOutput.slice(0, 2000)}`));
      });
    });

    const { port, token } = parseStartupLine(startupLine);
    const baseUrl = `http://127.0.0.1:${port}`;
    await waitUntilAcceptingConnections(baseUrl, token);
    return { baseUrl, token };
  }

  stop(): void {
    if (this.child && this.child.exitCode === null) {
      this.child.kill();
    }
    this.child = undefined;
  }
}
