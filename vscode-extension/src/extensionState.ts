import type { BackendClient } from "./backendClient";
import type { ManagedBackendProcess } from "./backendProcess";

/**
 * Shared, in-memory extension state - not a second persistence layer.
 * Nothing here is authoritative; it only tracks what the UI currently
 * believes, which every backend call independently re-validates.
 */
export class ExtensionState {
  client: BackendClient | undefined;
  connected = false;
  workspaceName: string | undefined;
  workspaceRoot: string | undefined;
  activeSessionId: string | undefined;
  managedProcess: ManagedBackendProcess | undefined;
}
