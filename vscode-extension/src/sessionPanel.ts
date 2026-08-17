import * as vscode from "vscode";
import * as crypto from "crypto";
import { BackendClient, BackendError } from "./backendClient";
import type { PlanResult, SessionDetail, StreamEvent } from "./types";

/**
 * The one Webview this extension has. It never makes its own HTTP calls -
 * every backend interaction is Webview -> postMessage -> extension host
 * (this file) -> BackendClient -> backend. Webview-supplied content can
 * only ever request an operation; every message is shape-validated here
 * before anything happens, and the backend independently re-validates and
 * re-authorizes regardless of what this file asked for.
 */

type OutgoingMessage =
  | { type: "state"; session: SessionDetail; history: { seq: number; speaker: string; content: string }[]; plan: PlanResult | null; events: StreamEvent[] }
  | { type: "error"; message: string }
  | { type: "busy"; busy: boolean };

type IncomingMessage =
  | { type: "sendMessage"; text: string }
  | { type: "approvePlan" }
  | { type: "revisePlan"; text: string }
  | { type: "rejectPlan"; text: string }
  | { type: "openArtifact" }
  | { type: "revealArtifact" }
  | { type: "refresh" };

export function isIncomingMessage(value: unknown): value is IncomingMessage {
  if (typeof value !== "object" || value === null || !("type" in value)) {
    return false;
  }
  const v = value as { type: unknown };
  return typeof v.type === "string" &&
    ["sendMessage", "approvePlan", "revisePlan", "rejectPlan", "openArtifact", "revealArtifact", "refresh"].includes(v.type);
}

export class SessionPanel {
  static current: SessionPanel | undefined;

  private readonly panel: vscode.WebviewPanel;
  private disposables: vscode.Disposable[] = [];
  private lastArtifactPath: string | null = null;

  private constructor(
    panel: vscode.WebviewPanel,
    private readonly client: BackendClient,
    private readonly sessionId: string,
    private readonly workspaceRoot: vscode.Uri,
  ) {
    this.panel = panel;
    this.panel.webview.html = this.render();
    this.panel.onDidDispose(() => this.dispose(), null, this.disposables);
    this.panel.webview.onDidReceiveMessage((raw: unknown) => this.handleMessage(raw), null, this.disposables);
    void this.refresh();
  }

  static async open(client: BackendClient, sessionId: string, workspaceRoot: vscode.Uri): Promise<SessionPanel> {
    if (SessionPanel.current) {
      SessionPanel.current.dispose();
    }
    const panel = vscode.window.createWebviewPanel(
      "agentPlatform.session",
      `Agent Platform: ${sessionId.slice(0, 8)}`,
      vscode.ViewColumn.One,
      { enableScripts: true, retainContextWhenHidden: true },
    );
    const instance = new SessionPanel(panel, client, sessionId, workspaceRoot);
    SessionPanel.current = instance;
    return instance;
  }

  private post(message: OutgoingMessage): void {
    void this.panel.webview.postMessage(message);
  }

  private async refresh(): Promise<void> {
    this.post({ type: "busy", busy: true });
    try {
      const session = await this.client.getSession(this.sessionId);
      const { messages } = await this.client.getHistory(this.sessionId, 200);
      const { events } = { events: await this.client.getEvents(this.sessionId) };
      let plan: PlanResult | null = null;
      if (session.operating_mode === "PLAN") {
        try {
          plan = await this.client.getPlan(this.sessionId);
        } catch (err) {
          if (!(err instanceof BackendError && err.status === 404)) {
            throw err;
          }
        }
      }
      this.lastArtifactPath = plan?.artifact_path ?? null;
      this.post({ type: "state", session, history: messages, plan, events });
    } catch (err) {
      this.post({ type: "error", message: err instanceof Error ? err.message : String(err) });
    } finally {
      this.post({ type: "busy", busy: false });
    }
  }

  private async handleMessage(raw: unknown): Promise<void> {
    if (!isIncomingMessage(raw)) {
      // Malformed/unexpected shape from the Webview is simply ignored - never
      // interpreted as a command, never forwarded to the backend as-is.
      return;
    }
    try {
      switch (raw.type) {
        case "sendMessage":
          await this.client.postMessage(this.sessionId, raw.text);
          break;
        case "approvePlan":
          await this.client.approvePlan(this.sessionId);
          break;
        case "revisePlan":
          await this.client.revisePlan(this.sessionId, raw.text);
          break;
        case "rejectPlan":
          await this.client.rejectPlan(this.sessionId, raw.text);
          break;
        case "openArtifact":
          await this.openArtifact(false);
          return;
        case "revealArtifact":
          await this.openArtifact(true);
          return;
        case "refresh":
          break;
      }
      await this.refresh();
    } catch (err) {
      this.post({ type: "error", message: err instanceof Error ? err.message : String(err) });
    }
  }

  /**
   * Artifact paths come only from the backend's own PlanResult.artifact_path
   * (never from Webview-controlled state) and are joined against the known
   * workspace root Uri - never opened as a free-standing string.
   */
  private async openArtifact(reveal: boolean): Promise<void> {
    if (!this.lastArtifactPath) {
      this.post({ type: "error", message: "No plan artifact exists yet for this session." });
      return;
    }
    const uri = vscode.Uri.joinPath(this.workspaceRoot, this.lastArtifactPath);
    if (reveal) {
      await vscode.commands.executeCommand("revealFileInOS", uri);
    } else {
      const doc = await vscode.workspace.openTextDocument(uri);
      await vscode.window.showTextDocument(doc, vscode.ViewColumn.Beside);
    }
  }

  private dispose(): void {
    if (SessionPanel.current === this) {
      SessionPanel.current = undefined;
    }
    this.panel.dispose();
    for (const d of this.disposables.splice(0)) {
      d.dispose();
    }
  }

  private render(): string {
    const nonce = crypto.randomBytes(16).toString("hex");
    const csp = [
      "default-src 'none'",
      `script-src 'nonce-${nonce}'`,
      `style-src ${this.panel.webview.cspSource} 'unsafe-inline'`,
    ].join("; ");
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy" content="${csp}">
  <style>
    body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); padding: 0 12px; }
    #transcript { max-height: 45vh; overflow-y: auto; border: 1px solid var(--vscode-panel-border); padding: 8px; margin-bottom: 8px; }
    .msg-user { color: var(--vscode-textLink-foreground); font-weight: bold; }
    .msg-assistant { color: var(--vscode-foreground); }
    .event { color: var(--vscode-descriptionForeground); font-size: 0.85em; }
    #plan { border: 1px solid var(--vscode-panel-border); padding: 8px; margin-bottom: 8px; }
    textarea { width: 100%; box-sizing: border-box; }
    button { margin: 2px; }
    #errorBox { color: var(--vscode-errorForeground); }
  </style>
</head>
<body>
  <h2 id="title">Agent Platform Session</h2>
  <div id="errorBox"></div>
  <div id="plan"></div>
  <div id="transcript"></div>
  <textarea id="input" rows="3" placeholder="Type a message..."></textarea><br>
  <button id="sendBtn">Send</button>
  <button id="refreshBtn">Refresh</button>
  <button id="openArtifactBtn">Open Plan Artifact</button>
  <button id="revealArtifactBtn">Reveal Plan Artifact</button>
  <script nonce="${nonce}">
    const vscodeApi = acquireVsCodeApi();
    const transcript = document.getElementById('transcript');
    const planBox = document.getElementById('plan');
    const errorBox = document.getElementById('errorBox');
    const title = document.getElementById('title');

    function escapeHtml(text) {
      const div = document.createElement('div');
      div.textContent = text;
      return div.innerHTML;
    }

    function renderPlan(plan) {
      if (!plan || !plan.plan) {
        planBox.innerHTML = '<em>No plan drafted yet.</em>';
        return;
      }
      const p = plan.plan;
      planBox.innerHTML =
        '<b>Status:</b> ' + escapeHtml(plan.status) + '<br>' +
        '<b>Objective:</b> ' + escapeHtml(p.objective) + '<br>' +
        '<b>Requirements:</b><ul>' + p.requirements.map((r) => '<li>' + escapeHtml(r) + '</li>').join('') + '</ul>' +
        '<b>Acceptance Criteria:</b><ul>' + p.acceptance_criteria.map((r) => '<li>' + escapeHtml(r) + '</li>').join('') + '</ul>' +
        (p.reviewer_feedback.length ? '<b>Reviewer Feedback:</b><ul>' + p.reviewer_feedback.map((r) => '<li>' + escapeHtml(r) + '</li>').join('') + '</ul>' : '') +
        '<button id="approveBtn">Approve</button>' +
        '<button id="reviseBtn">Revise</button>' +
        '<button id="rejectBtn">Reject</button>';
      const approveBtn = document.getElementById('approveBtn');
      if (approveBtn) approveBtn.addEventListener('click', () => vscodeApi.postMessage({ type: 'approvePlan' }));
      const reviseBtn = document.getElementById('reviseBtn');
      if (reviseBtn) reviseBtn.addEventListener('click', () => {
        const text = document.getElementById('input').value;
        vscodeApi.postMessage({ type: 'revisePlan', text });
      });
      const rejectBtn = document.getElementById('rejectBtn');
      if (rejectBtn) rejectBtn.addEventListener('click', () => {
        const text = document.getElementById('input').value || 'not needed';
        vscodeApi.postMessage({ type: 'rejectPlan', text });
      });
    }

    function render(state) {
      title.textContent = 'Agent Platform: ' + state.session.operating_mode + ' (' + state.session.status + ')';
      const lines = [];
      for (const m of state.history) {
        const cls = m.speaker === 'user' ? 'msg-user' : 'msg-assistant';
        lines.push('<div class="' + cls + '">' + escapeHtml(m.speaker) + ': ' + escapeHtml(m.content) + '</div>');
      }
      for (const e of state.events) {
        lines.push('<div class="event">[' + escapeHtml(e.event_type) + ']</div>');
      }
      transcript.innerHTML = lines.join('') || '<em>No activity yet.</em>';
      transcript.scrollTop = transcript.scrollHeight;
      renderPlan(state.plan);
    }

    window.addEventListener('message', (event) => {
      const msg = event.data;
      if (msg.type === 'state') {
        errorBox.textContent = '';
        render(msg);
      } else if (msg.type === 'error') {
        errorBox.textContent = 'Error: ' + msg.message;
      }
    });

    document.getElementById('sendBtn').addEventListener('click', () => {
      const input = document.getElementById('input');
      if (input.value.trim()) {
        vscodeApi.postMessage({ type: 'sendMessage', text: input.value });
        input.value = '';
      }
    });
    document.getElementById('refreshBtn').addEventListener('click', () => vscodeApi.postMessage({ type: 'refresh' }));
    document.getElementById('openArtifactBtn').addEventListener('click', () => vscodeApi.postMessage({ type: 'openArtifact' }));
    document.getElementById('revealArtifactBtn').addEventListener('click', () => vscodeApi.postMessage({ type: 'revealArtifact' }));
  </script>
</body>
</html>`;
  }
}
