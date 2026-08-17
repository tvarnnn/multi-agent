import * as vscode from "vscode";
import type { ExtensionState } from "./extensionState";

type TreeNodeKind =
  | "workspaceInfo"
  | "backendInfo"
  | "sessionInfo"
  | "modeInfo"
  | "sessionsRoot"
  | "sessionItem"
  | "settingsItem"
  | "message";

export class AgentPlatformTreeItem extends vscode.TreeItem {
  constructor(
    label: string,
    collapsibleState: vscode.TreeItemCollapsibleState,
    public readonly kind: TreeNodeKind,
    public readonly sessionId?: string,
  ) {
    super(label, collapsibleState);
  }
}

export class SidebarProvider implements vscode.TreeDataProvider<AgentPlatformTreeItem> {
  private readonly _onDidChangeTreeData = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  constructor(private readonly state: ExtensionState) {}

  refresh(): void {
    this._onDidChangeTreeData.fire();
  }

  getTreeItem(element: AgentPlatformTreeItem): vscode.TreeItem {
    return element;
  }

  async getChildren(element?: AgentPlatformTreeItem): Promise<AgentPlatformTreeItem[]> {
    if (!element) {
      return this.getRootItems();
    }
    if (element.kind === "sessionsRoot") {
      return this.getSessionItems();
    }
    return [];
  }

  private getRootItems(): AgentPlatformTreeItem[] {
    const items: AgentPlatformTreeItem[] = [];

    const workspaceLabel = this.state.workspaceName
      ? `Workspace: ${this.state.workspaceName}`
      : "Workspace: (none open)";
    items.push(new AgentPlatformTreeItem(workspaceLabel, vscode.TreeItemCollapsibleState.None, "workspaceInfo"));

    const backendLabel = this.state.connected ? "Backend: Connected" : "Backend: Disconnected";
    const backendItem = new AgentPlatformTreeItem(backendLabel, vscode.TreeItemCollapsibleState.None, "backendInfo");
    backendItem.iconPath = new vscode.ThemeIcon(this.state.connected ? "pass-filled" : "circle-slash");
    items.push(backendItem);

    const sessionLabel = this.state.activeSessionId
      ? `Active Session: ${this.state.activeSessionId.slice(0, 12)}`
      : "Active Session: (none)";
    items.push(new AgentPlatformTreeItem(sessionLabel, vscode.TreeItemCollapsibleState.None, "sessionInfo"));

    items.push(
      new AgentPlatformTreeItem(
        "Sessions",
        this.state.connected ? vscode.TreeItemCollapsibleState.Expanded : vscode.TreeItemCollapsibleState.Collapsed,
        "sessionsRoot",
      ),
    );

    const settingsItem = new AgentPlatformTreeItem("Settings", vscode.TreeItemCollapsibleState.None, "settingsItem");
    settingsItem.command = { command: "agentPlatform.openConfiguration", title: "Show Configuration" };
    settingsItem.iconPath = new vscode.ThemeIcon("gear");
    items.push(settingsItem);

    return items;
  }

  private async getSessionItems(): Promise<AgentPlatformTreeItem[]> {
    if (!this.state.connected || !this.state.client) {
      return [
        new AgentPlatformTreeItem(
          "(backend not connected)",
          vscode.TreeItemCollapsibleState.None,
          "message",
        ),
      ];
    }
    try {
      const { sessions } = await this.state.client.listSessions();
      if (sessions.length === 0) {
        return [new AgentPlatformTreeItem("(no sessions yet)", vscode.TreeItemCollapsibleState.None, "message")];
      }
      return sessions.map((s) => {
        const label = `${s.operating_mode} · ${s.status} · ${s.session_id.slice(0, 8)}`;
        const item = new AgentPlatformTreeItem(label, vscode.TreeItemCollapsibleState.None, "sessionItem", s.session_id);
        item.contextValue = "session";
        item.command = {
          command: "agentPlatform.openSession",
          title: "Open Session",
          arguments: [s.session_id],
        };
        item.tooltip = `${s.session_id}\nspec: ${s.spec_id ?? "(none)"}\nupdated: ${new Date(s.updated_at * 1000).toLocaleString()}`;
        return item;
      });
    } catch (err) {
      return [
        new AgentPlatformTreeItem(`(failed to list sessions: ${(err as Error).message})`,
          vscode.TreeItemCollapsibleState.None, "message"),
      ];
    }
  }
}
