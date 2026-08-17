import * as vscode from "vscode";
import { BackendClient, BackendError } from "./backendClient";
import { ManagedBackendProcess } from "./backendProcess";
import { ExtensionState } from "./extensionState";
import { SidebarProvider } from "./sidebarProvider";
import { SessionPanel } from "./sessionPanel";
import type { OperatingMode } from "./types";

const MODES: OperatingMode[] = ["CHAT", "PLAN", "CODE", "EDIT", "REVIEW"];
const MODES_REQUIRING_SPEC_ID: OperatingMode[] = ["PLAN", "CODE", "EDIT"];

let state: ExtensionState;
let sidebarProvider: SidebarProvider;
let workspaceUri: vscode.Uri | undefined;

function showBackendError(err: unknown): void {
  if (err instanceof BackendError) {
    void vscode.window.showErrorMessage(`Agent Platform: ${err.message}`);
  } else {
    void vscode.window.showErrorMessage(`Agent Platform: ${err instanceof Error ? err.message : String(err)}`);
  }
}

function detectWorkspace(): vscode.Uri | undefined {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders || folders.length === 0) {
    return undefined;
  }
  if (folders.length > 1) {
    void vscode.window.showWarningMessage(
      "Agent Platform: multiple workspace folders are open. Only the first (" +
        folders[0].name +
        ") is used - multi-root workspaces are not yet safely supported (the backend binds one process to one project root).",
    );
  }
  return folders[0].uri;
}

async function ensureConnected(context: vscode.ExtensionContext): Promise<boolean> {
  if (state.connected && state.client) {
    return true;
  }
  return startBackend(context);
}

async function startBackend(context: vscode.ExtensionContext): Promise<boolean> {
  workspaceUri = detectWorkspace();
  if (!workspaceUri) {
    void vscode.window.showErrorMessage("Agent Platform: open a folder/workspace first.");
    return false;
  }
  state.workspaceName = vscode.workspace.workspaceFolders?.[0]?.name;
  state.workspaceRoot = workspaceUri.fsPath;

  const config = vscode.workspace.getConfiguration("agentPlatform");
  const externalUrl = config.get<string>("backendUrl", "");

  try {
    if (externalUrl) {
      const externalToken = config.get<string>("backendToken", "");
      state.client = new BackendClient(externalUrl, externalToken);
      // Prove the connection actually works before declaring success.
      await state.client.listSessions();
    } else {
      const pythonPath = config.get<string>("pythonPath", "python");
      const managed = new ManagedBackendProcess();
      const connection = await managed.start(pythonPath, workspaceUri.fsPath, workspaceUri.fsPath);
      state.managedProcess = managed;
      state.client = new BackendClient(connection.baseUrl, connection.token);
      await context.secrets.store("agentPlatform.token", connection.token);
    }
    state.connected = true;
    sidebarProvider.refresh();
    return true;
  } catch (err) {
    state.connected = false;
    showBackendError(err);
    return false;
  }
}

function stopBackend(): void {
  state.managedProcess?.stop();
  state.managedProcess = undefined;
  state.client = undefined;
  state.connected = false;
  state.activeSessionId = undefined;
  sidebarProvider.refresh();
}

async function pickMode(): Promise<OperatingMode | undefined> {
  return vscode.window.showQuickPick(MODES, { placeHolder: "Select Agent Platform mode" }) as Promise<
    OperatingMode | undefined
  >;
}

async function createSession(context: vscode.ExtensionContext): Promise<void> {
  if (!(await ensureConnected(context))) {
    return;
  }
  const mode = await pickMode();
  if (!mode) {
    return;
  }
  let specId: string | undefined;
  if (MODES_REQUIRING_SPEC_ID.includes(mode)) {
    specId = await vscode.window.showInputBox({
      prompt: `spec_id is required for ${mode} mode sessions`,
      placeHolder: "e.g. add-health-check-endpoint",
    });
    if (!specId) {
      return;
    }
  }
  try {
    const { session_id } = await state.client!.createSession(mode, specId);
    state.activeSessionId = session_id;
    sidebarProvider.refresh();
    await SessionPanel.open(state.client!, session_id, workspaceUri!);
  } catch (err) {
    showBackendError(err);
  }
}

async function openSession(sessionIdArg?: string): Promise<void> {
  if (!state.connected || !state.client) {
    void vscode.window.showErrorMessage("Agent Platform: not connected to a backend.");
    return;
  }
  let sessionId = sessionIdArg;
  if (!sessionId) {
    const { sessions } = await state.client.listSessions();
    const pick = await vscode.window.showQuickPick(
      sessions.map((s) => ({ label: `${s.operating_mode} · ${s.status} · ${s.session_id.slice(0, 8)}`, sessionId: s.session_id })),
      { placeHolder: "Select a session" },
    );
    sessionId = pick?.sessionId;
  }
  if (!sessionId || !workspaceUri) {
    return;
  }
  state.activeSessionId = sessionId;
  sidebarProvider.refresh();
  await SessionPanel.open(state.client, sessionId, workspaceUri);
}

async function resumeSession(sessionIdArg?: string): Promise<void> {
  if (!state.connected || !state.client || !workspaceUri) {
    return;
  }
  const sessionId = sessionIdArg ?? state.activeSessionId;
  if (!sessionId) {
    return;
  }
  try {
    await state.client.resumeSession(sessionId);
    state.activeSessionId = sessionId;
    sidebarProvider.refresh();
    await SessionPanel.open(state.client, sessionId, workspaceUri);
  } catch (err) {
    showBackendError(err);
  }
}

async function archiveSession(sessionIdArg?: string): Promise<void> {
  if (!state.connected || !state.client) {
    return;
  }
  const sessionId = sessionIdArg ?? state.activeSessionId;
  if (!sessionId) {
    return;
  }
  const confirmed = await vscode.window.showWarningMessage(
    `Archive session ${sessionId.slice(0, 8)}?`,
    { modal: true },
    "Archive",
  );
  if (confirmed !== "Archive") {
    return;
  }
  try {
    await state.client.archiveSession(sessionId);
    if (state.activeSessionId === sessionId) {
      state.activeSessionId = undefined;
    }
    sidebarProvider.refresh();
  } catch (err) {
    showBackendError(err);
  }
}

async function openConfiguration(): Promise<void> {
  if (!(await ensureConnected(await getContext()))) {
    return;
  }
  try {
    const view = await state.client!.getConfiguration();
    const doc = await vscode.workspace.openTextDocument({
      content: JSON.stringify(view, null, 2),
      language: "json",
    });
    await vscode.window.showTextDocument(doc, { preview: true });
  } catch (err) {
    showBackendError(err);
  }
}

async function editMcpPreferences(): Promise<void> {
  if (!state.connected || !state.client) {
    void vscode.window.showErrorMessage("Agent Platform: not connected to a backend.");
    return;
  }
  try {
    const { mcp } = await state.client.getConfigurationMcp();
    const serverIds = Object.keys(mcp);
    if (serverIds.length === 0) {
      void vscode.window.showInformationMessage("Agent Platform: no MCP servers are configured.");
      return;
    }
    const serverId = await vscode.window.showQuickPick(serverIds, { placeHolder: "Select an MCP server" });
    if (!serverId) {
      return;
    }
    const enabledChoice = await vscode.window.showQuickPick(["Enable", "Disable"], {
      placeHolder: `Server "${serverId}" is currently ${mcp[serverId].enabled ? "enabled" : "disabled"}`,
    });
    if (!enabledChoice) {
      return;
    }
    await state.client.setMcpPreferences(serverId, { enabled: enabledChoice === "Enable" });
    void vscode.window.showInformationMessage(`Agent Platform: ${serverId} preferences updated.`);
  } catch (err) {
    showBackendError(err);
  }
}

let extensionContext: vscode.ExtensionContext;
async function getContext(): Promise<vscode.ExtensionContext> {
  return extensionContext;
}

export function activate(context: vscode.ExtensionContext): void {
  extensionContext = context;
  state = new ExtensionState();
  sidebarProvider = new SidebarProvider(state);
  workspaceUri = detectWorkspace();
  state.workspaceName = vscode.workspace.workspaceFolders?.[0]?.name;
  state.workspaceRoot = workspaceUri?.fsPath;

  context.subscriptions.push(vscode.window.registerTreeDataProvider("agentPlatform.sidebar", sidebarProvider));

  context.subscriptions.push(
    vscode.commands.registerCommand("agentPlatform.startBackend", () => startBackend(context)),
    vscode.commands.registerCommand("agentPlatform.stopBackend", () => stopBackend()),
    vscode.commands.registerCommand("agentPlatform.createSession", () => createSession(context)),
    vscode.commands.registerCommand("agentPlatform.openSession", (id?: string) => openSession(id)),
    vscode.commands.registerCommand("agentPlatform.resumeSession", (id?: string) => resumeSession(id)),
    vscode.commands.registerCommand("agentPlatform.archiveSession", (id?: string) => archiveSession(id)),
    vscode.commands.registerCommand("agentPlatform.refreshSessions", () => sidebarProvider.refresh()),
    vscode.commands.registerCommand("agentPlatform.openConfiguration", () => openConfiguration()),
    vscode.commands.registerCommand("agentPlatform.editMcpPreferences", () => editMcpPreferences()),
    vscode.commands.registerCommand("agentPlatform.openPlanArtifact", () =>
      vscode.commands.executeCommand("agentPlatform.openSession", state.activeSessionId),
    ),
    vscode.commands.registerCommand("agentPlatform.revealPlanArtifact", () =>
      vscode.commands.executeCommand("agentPlatform.openSession", state.activeSessionId),
    ),
    vscode.workspace.onDidChangeWorkspaceFolders(() => {
      workspaceUri = detectWorkspace();
      state.workspaceName = vscode.workspace.workspaceFolders?.[0]?.name;
      sidebarProvider.refresh();
    }),
  );
}

export function deactivate(): void {
  state?.managedProcess?.stop();
}

// Exported for tests only - not part of the public extension API.
export const __test__ = { detectWorkspace };
