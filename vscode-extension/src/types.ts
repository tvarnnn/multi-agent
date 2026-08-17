/**
 * TypeScript types mirroring the Python backend's actual JSON wire shapes,
 * copied field-for-field from api_serialization.py (read directly from
 * source, not inferred). If a field isn't in the Python serializer, it
 * isn't here either - this file is the single source of truth for what
 * the extension is allowed to assume the backend returns.
 */

export type OperatingMode = "CHAT" | "PLAN" | "CODE" | "EDIT" | "REVIEW";
export type SessionMode = "AUTO" | "CONFIRMATION" | "MANUAL";

export interface SessionSummary {
  session_id: string;
  operating_mode: OperatingMode;
  status: string;
  spec_id: string | null;
  updated_at: number;
}

export interface SessionDetail {
  session_id: string;
  operating_mode: OperatingMode;
  session_mode: SessionMode;
  spec_id: string | null;
  status: string;
  active_spec_version: number | null;
  active_plan_id: number | null;
  current_checkpoint_id: number | null;
  fix_iteration_count: number;
  clarification_round_count: number;
  created_at: number;
  updated_at: number;
  archived_at: number | null;
}

export interface MessageRecord {
  seq: number;
  speaker: "user" | "assistant";
  content: string;
  created_at: number;
}

export interface StructuredPlan {
  objective: string;
  requirements: string[];
  existing_context: string[];
  proposed_architecture: string;
  files_to_create: string[];
  files_to_modify: string[];
  dependencies: string[];
  implementation_steps: string[];
  validation_strategy: string[];
  risks: string[];
  unknowns: string[];
  acceptance_criteria: string[];
  reviewer_feedback: string[];
  target_spec_version_label: string;
}

export interface PlanResult {
  status: "DRAFT" | "REVISED" | "APPROVED" | "REJECTED" | "NEEDS_INPUT" | "FAILED";
  spec_id: string;
  message: string;
  artifact_path: string | null;
  plan: StructuredPlan | null;
}

export interface PlanApprovalResult {
  spec_id: string;
  spec_version_label: string;
  artifact_path: string;
}

export interface ChatResult {
  session_id: string;
  message: string;
}

export interface ReviewResult {
  session_id: string;
  summary: string;
  findings: unknown[];
}

export interface OrchestratorResult {
  final_state: string;
  spec_id: string;
  summary: string;
}

export interface CheckpointSummary {
  id: number;
  seq: number;
  reason: string;
  objective: string;
  spec_version_label: string | null;
  created_at: number;
}

export interface StreamEvent {
  session_id: string;
  event_type: string;
  timestamp: number;
  payload: Record<string, unknown>;
  spec_version_label: string | null;
}

export interface ModelInfo {
  model_id: string | null;
  available: boolean | null;
}

export interface ConfigurationView {
  models: { planner: ModelInfo; coder: ModelInfo; reviewer: ModelInfo };
  mcp: Record<string, { enabled: boolean; transport: string; capabilities: string[] }>;
  agent_behavior: Record<string, unknown>;
  precedence: { global_loaded: boolean; workspace_loaded: boolean };
}

export interface AvailableModels {
  models: { planner: ModelInfo; coder: ModelInfo; reviewer: ModelInfo };
  installed: string[];
}

export interface McpServerView {
  server_id: string;
  transport: string;
  enabled: boolean;
  capabilities: string[];
}

export interface ReconstructedContextView {
  operating_mode: OperatingMode;
  session_mode: SessionMode;
  spec_id: string | null;
  spec_version_label: string | null;
  checkpoint: Record<string, unknown> | null;
  stale: boolean;
  stale_reasons: string[];
  recent_messages: MessageRecord[];
  project_files: { path: string; category: string; truncated: boolean }[];
  messages_dropped_for_budget: number;
}

export interface ErrorBody {
  error: string;
  code: string;
}
