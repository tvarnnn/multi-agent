/**
 * The ONLY module in this extension that makes HTTP/SSE calls to the
 * Agent Platform backend. Every other module goes through this client -
 * no other file imports "http"/"https"/fetch. The bearer token lives
 * only here (in memory) and in vscode.SecretStorage; it is never placed
 * into a Webview message or logged.
 */
import type {
  AvailableModels,
  ChatResult,
  CheckpointSummary,
  ConfigurationView,
  McpServerView,
  OperatingMode,
  OrchestratorResult,
  PlanApprovalResult,
  PlanResult,
  ReconstructedContextView,
  ReviewResult,
  SessionDetail,
  SessionSummary,
  StreamEvent,
} from "./types";

export class BackendError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code: string | undefined,
  ) {
    super(message);
    this.name = "BackendError";
  }
}

export class BackendClient {
  constructor(
    private baseUrl: string,
    private token: string,
  ) {}

  updateConnection(baseUrl: string, token: string): void {
    this.baseUrl = baseUrl;
    this.token = token;
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        headers: {
          Authorization: `Bearer ${this.token}`,
          "Content-Type": "application/json",
          ...(init?.headers ?? {}),
        },
      });
    } catch (err) {
      throw new BackendError(
        `Could not reach the Agent Platform backend at ${this.baseUrl}: ${(err as Error).message}`,
        0,
        "CONNECTION_FAILED",
      );
    }
    const text = await response.text();
    let body: unknown = undefined;
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        // non-JSON body - leave body undefined, still surface the status code below
      }
    }
    if (!response.ok) {
      const detail = (body as { detail?: { error?: string; code?: string } } | undefined)?.detail;
      const message = detail?.error ?? `Backend request failed with status ${response.status}`;
      throw new BackendError(message, response.status, detail?.code);
    }
    return body as T;
  }

  // ---------------------------------------------------------------- sessions

  createSession(operatingMode: OperatingMode, specId?: string): Promise<{ session_id: string }> {
    return this.request("/sessions", {
      method: "POST",
      body: JSON.stringify({ operating_mode: operatingMode, spec_id: specId ?? null }),
    });
  }

  listSessions(): Promise<{ sessions: SessionSummary[] }> {
    return this.request("/sessions");
  }

  getSession(sessionId: string): Promise<SessionDetail> {
    return this.request(`/sessions/${encodeURIComponent(sessionId)}`);
  }

  getHistory(sessionId: string, limit = 50): Promise<{ messages: { seq: number; speaker: string; content: string; created_at: number }[] }> {
    return this.request(`/sessions/${encodeURIComponent(sessionId)}/history?limit=${limit}`);
  }

  getCheckpoints(sessionId: string): Promise<{ checkpoints: CheckpointSummary[] }> {
    return this.request(`/sessions/${encodeURIComponent(sessionId)}/checkpoints`);
  }

  resumeSession(sessionId: string): Promise<ReconstructedContextView> {
    return this.request(`/sessions/${encodeURIComponent(sessionId)}/resume`, { method: "POST" });
  }

  archiveSession(sessionId: string): Promise<{ session_id: string; status: string }> {
    return this.request(`/sessions/${encodeURIComponent(sessionId)}/archive`, { method: "POST" });
  }

  getState(sessionId: string): Promise<{ state: string; operating_mode: OperatingMode }> {
    return this.request(`/sessions/${encodeURIComponent(sessionId)}/state`);
  }

  // ---------------------------------------------------------------- messages

  postMessage(
    sessionId: string,
    message: string,
  ): Promise<ChatResult | PlanResult | ReviewResult | OrchestratorResult> {
    return this.request(`/sessions/${encodeURIComponent(sessionId)}/messages`, {
      method: "POST",
      body: JSON.stringify({ message }),
    });
  }

  // -------------------------------------------------------------------- plan

  getPlan(sessionId: string): Promise<PlanResult> {
    return this.request(`/sessions/${encodeURIComponent(sessionId)}/plan`);
  }

  revisePlan(sessionId: string, revisionRequest: string): Promise<PlanResult> {
    return this.request(`/sessions/${encodeURIComponent(sessionId)}/plan/revise`, {
      method: "POST",
      body: JSON.stringify({ revision_request: revisionRequest }),
    });
  }

  approvePlan(sessionId: string): Promise<PlanApprovalResult> {
    return this.request(`/sessions/${encodeURIComponent(sessionId)}/plan/approve`, { method: "POST" });
  }

  rejectPlan(sessionId: string, reason: string): Promise<PlanResult> {
    return this.request(`/sessions/${encodeURIComponent(sessionId)}/plan/reject`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
  }

  // --------------------------------------------------------- configuration

  getConfiguration(): Promise<ConfigurationView> {
    return this.request("/configuration");
  }

  getAvailableModels(): Promise<AvailableModels> {
    return this.request("/configuration/models");
  }

  getConfigurationMcp(): Promise<{ mcp: ConfigurationView["mcp"] }> {
    return this.request("/configuration/mcp");
  }

  listMcpServers(): Promise<{ servers: McpServerView[] }> {
    return this.request("/mcp/servers");
  }

  setMcpPreferences(
    serverId: string,
    body: { enabled?: boolean; capability_overrides?: Record<string, boolean> },
  ): Promise<McpServerView> {
    return this.request(`/mcp/servers/${encodeURIComponent(serverId)}/preferences`, {
      method: "PUT",
      body: JSON.stringify(body),
    });
  }

  // --------------------------------------------------------------------- SSE

  /**
   * The backend's /events route replays everything emitted so far as one
   * response, not a live push (see backend_api.py::get_events) - fetched
   * and parsed as a batch of `data: <json>\n\n` frames, no EventSource
   * dependency needed for that shape.
   */
  async getEvents(sessionId: string): Promise<StreamEvent[]> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}/sessions/${encodeURIComponent(sessionId)}/events`, {
        headers: { Authorization: `Bearer ${this.token}` },
      });
    } catch (err) {
      throw new BackendError(
        `Could not reach the Agent Platform backend: ${(err as Error).message}`,
        0,
        "CONNECTION_FAILED",
      );
    }
    if (!response.ok) {
      throw new BackendError(`Event stream request failed with status ${response.status}`, response.status, undefined);
    }
    const text = await response.text();
    const events: StreamEvent[] = [];
    for (const line of text.split("\n")) {
      if (line.startsWith("data: ")) {
        try {
          events.push(JSON.parse(line.slice("data: ".length)) as StreamEvent);
        } catch {
          // malformed frame - skip it rather than crash the whole stream render
        }
      }
    }
    return events;
  }
}
