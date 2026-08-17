import * as assert from "assert";
import * as http from "http";
import { waitUntilAcceptingConnections } from "../../src/backendProcess";

/**
 * Regression test for the race the live end-to-end test caught: the
 * backend's startup line is printed before uvicorn's socket is actually
 * listening. Reproduced deterministically here with a plain Node HTTP
 * server whose .listen() is deliberately delayed - a real server, a real
 * connection race, no Python/Ollama dependency needed to prove the retry
 * logic itself is correct.
 */
suite("waitUntilAcceptingConnections", () => {
  test("retries until a delayed server starts listening", async function () {
    this.timeout(5000);
    const server = http.createServer((_req, res) => res.end("ok"));
    const port = 34567 + Math.floor(Math.random() * 1000);
    setTimeout(() => server.listen(port, "127.0.0.1"), 200);

    try {
      await waitUntilAcceptingConnections(`http://127.0.0.1:${port}`, "unused-token", 3000, 20);
    } finally {
      server.close();
    }
  });

  test("throws after the timeout if nothing ever listens", async function () {
    this.timeout(3000);
    const port = 34567 + Math.floor(Math.random() * 1000) + 2000; // an address nothing is bound to
    await assert.rejects(() => waitUntilAcceptingConnections(`http://127.0.0.1:${port}`, "unused-token", 300, 20));
  });
});
