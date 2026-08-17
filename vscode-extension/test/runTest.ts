import * as path from "path";
import { runTests } from "@vscode/test-electron";

async function main(): Promise<void> {
  const extensionDevelopmentPath = path.resolve(__dirname, "../../");
  const extensionTestsPath = path.resolve(__dirname, "./suite/index");
  const workspacePath = path.resolve(__dirname, "../test-fixtures/sample-workspace");

  try {
    await runTests({
      extensionDevelopmentPath,
      extensionTestsPath,
      launchArgs: [workspacePath, "--new-window", "--skip-welcome", "--skip-release-notes"],
    });
  } catch (err) {
    console.error("Failed to run extension tests:", err);
    process.exit(1);
  }
}

void main();
