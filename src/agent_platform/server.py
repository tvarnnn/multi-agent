"""Local FastAPI + uvicorn transport for Planning Mode (design §9). Binds
to 127.0.0.1 only - never 0.0.0.0 - on an OS-assigned port by default
(--port 0), and prints exactly one JSON line to stdout on startup:
{"port": <int>, "token": "<32-byte urlsafe random>"}. The VS Code
extension that spawns this process reads that line to learn where to
connect and what bearer token to present. The token is generated fresh
per process launch, lives only in memory and that one stdout line, and
is never written to disk or logged.
"""
from __future__ import annotations

import argparse
import json
import secrets
import socket
from pathlib import Path
from typing import Optional

import uvicorn

from .backend_api import BackendServices, create_app
from .config import PlatformConfig
from .events import EventLog
from .mcp.preferences import MCPUserPreferences
from .orchestrator.ollama_provider import OllamaModelProvider
from .orchestrator.validation import AcceptanceCriteriaFileValidator
from .persistence.db import ensure_schema, resolve_agent_paths
from .persistence.service import SessionPersistenceService
from .security.permission import PermissionEvaluator
from .security.sandbox import FilesystemSandbox
from .settings.service import SettingsService
from .spec.versioning import SpecStore
from .tools.gateway import ToolGateway
from .tools.registry import build_default_registry

HOST = "127.0.0.1"
TOKEN_BYTES = 32

# Phase 11: hardcoded fallbacks used only when neither an explicit
# build_services() kwarg nor a loaded settings file specifies a value -
# identical to Phase 10's previous literal defaults, so "no settings file
# present" behaves byte-for-byte like before Phase 11 existed.
# Phase 12: hardcoded fallback model names used only when a real model
# provider must be constructed by default (model=None) and neither a
# settings file nor the caller specifies one. Same names already used by
# tests/test_ollama_integration.py and scripts/live_run.py - kept
# identical so "what model runs by default" is answered consistently in
# exactly one place across this project, not three slightly different ones.
DEFAULT_PLANNER_MODEL = "phi4-reasoning:plus"
DEFAULT_CODER_MODEL = "qwen2.5-coder:14b"
DEFAULT_REVIEWER_MODEL = "phi4-reasoning:plus"

_DEFAULT_AGENT_DATA_DIR = ".agent"
_DEFAULT_CONTEXT_COMPACTION_ENABLED = True
_DEFAULT_CONTEXT_COMPACTION_THRESHOLD_PERCENT = 85
_DEFAULT_MAX_CONVERSATION_TOKENS_ESTIMATE = 20_000
_DEFAULT_TOOL_OBSERVATION_RETENTION = 200
_DEFAULT_RECENT_MESSAGE_WINDOW = 20


def generate_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def bind_loopback_socket(port: int = 0) -> socket.socket:
    """Binds a real socket to 127.0.0.1 (never 0.0.0.0) so the OS-assigned
    port is known before uvicorn starts serving - no bind/release race
    between "ask the OS for a port" and "actually listen on it"."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((HOST, port))
    return sock


def startup_line(port: int, token: str) -> str:
    return json.dumps({"port": port, "token": token})


def build_services(project_root: Path, model, *, workspace_root: Optional[Path] = None,
                    global_settings_path: Optional[Path] = None,
                    workspace_settings_path: Optional[Path] = None,
                    agent_data_dir: Optional[str] = None, context_compaction_enabled: Optional[bool] = None,
                    context_compaction_threshold_percent: Optional[int] = None,
                    max_conversation_tokens_estimate: Optional[int] = None,
                    tool_observation_retention: Optional[int] = None,
                    recent_message_window: Optional[int] = None) -> BackendServices:
    """Constructs one process-lifetime BackendServices, including opening/
    creating the project's .agent/agent.db and replaying every persisted
    SpecVersion into a fresh SpecStore (Phase 10) before any session can
    be created. Rehydration failure (SpecRehydrationError, on a corrupted
    spec_versions sequence) and schema-binding failure
    (SchemaVersionMismatchError/ProjectRootMismatchError) are deliberately
    NOT caught here - they propagate and stop the backend from starting,
    per the confirmed fail-loud decision: never serve a backend against
    possibly-wrong spec/session history.

    Phase 11: also loads global/workspace settings.yaml (preference layer,
    never authority - see settings/service.py). An explicit keyword
    argument here always wins over a settings-file value, which in turn
    wins over the hardcoded fallback above; with no settings file present,
    behavior is byte-for-byte identical to Phase 10 (see
    test_no_settings_file_behaves_identically_to_before_phase_11).
    """
    root = workspace_root if workspace_root is not None else project_root.parent

    resolved_workspace_settings_path = (
        workspace_settings_path if workspace_settings_path is not None
        else project_root / ".agent" / "settings.yaml"
    )
    settings_service = SettingsService.load(global_path=global_settings_path,
                                             workspace_path=resolved_workspace_settings_path)
    settings_kwargs = settings_service.platform_config_kwargs

    # Phase 12: model=None constructs a real OllamaModelProvider (Phase 2, unmodified) using
    # Phase 11's settings-derived model names, falling back to the hardcoded defaults above for
    # any role the settings file doesn't specify. An explicitly-passed model (every existing
    # test's FakeModelProvider(), or any other caller-supplied provider) is used exactly as
    # before - this is purely additive for the previously-broken "model omitted" case.
    if model is None:
        model_settings = settings_service.model_settings
        model = OllamaModelProvider(
            planner_model=model_settings.planner or DEFAULT_PLANNER_MODEL,
            coder_model=model_settings.coder or DEFAULT_CODER_MODEL,
            reviewer_model=model_settings.reviewer or DEFAULT_REVIEWER_MODEL,
        )

    def _resolve(name: str, explicit, hardcoded_default):
        if explicit is not None:
            return explicit
        return settings_kwargs.get(name, hardcoded_default)

    agent_data_dir = _resolve("agent_data_dir", agent_data_dir, _DEFAULT_AGENT_DATA_DIR)
    context_compaction_enabled = _resolve(
        "context_compaction_enabled", context_compaction_enabled, _DEFAULT_CONTEXT_COMPACTION_ENABLED)
    context_compaction_threshold_percent = _resolve(
        "context_compaction_threshold_percent", context_compaction_threshold_percent,
        _DEFAULT_CONTEXT_COMPACTION_THRESHOLD_PERCENT)
    max_conversation_tokens_estimate = _resolve(
        "max_conversation_tokens_estimate", max_conversation_tokens_estimate,
        _DEFAULT_MAX_CONVERSATION_TOKENS_ESTIMATE)
    tool_observation_retention = _resolve(
        "tool_observation_retention", tool_observation_retention, _DEFAULT_TOOL_OBSERVATION_RETENTION)
    recent_message_window = _resolve(
        "recent_message_window", recent_message_window, _DEFAULT_RECENT_MESSAGE_WINDOW)

    sandbox = FilesystemSandbox(root)
    evaluator = PermissionEvaluator(sandbox)
    registry = build_default_registry()
    spec_store = SpecStore()

    # Reporting only (SettingsService.safe_view()'s agent_behavior section) - PlatformConfig's
    # own validation still runs here for free, so a settings file producing an invalid
    # combination (e.g. context_compaction_threshold_percent=150) fails backend startup loudly,
    # exactly like any other ConfigurationError.
    platform_config = PlatformConfig.load(str(project_root), **settings_kwargs)
    settings_service.bind_platform_config(platform_config)

    paths = resolve_agent_paths(sandbox, project_root, agent_data_dir)
    ensure_schema(paths.db_path, project_root)
    persistence_gateway = ToolGateway(registry, evaluator, EventLog())
    persistence = SessionPersistenceService(
        db_path=paths.db_path, sandbox=sandbox, project_root=project_root,
        checkpoints_relative_dir=f"{agent_data_dir}/context/checkpoints", gateway=persistence_gateway,
        spec_store=spec_store, compaction_enabled=context_compaction_enabled,
        compaction_threshold_percent=context_compaction_threshold_percent,
        max_conversation_tokens_estimate=max_conversation_tokens_estimate,
        recent_message_window=recent_message_window, tool_observation_retention=tool_observation_retention,
    )
    persistence.rehydrate()

    return BackendServices(
        project_root=project_root, spec_store=spec_store, model=model,
        validator=AcceptanceCriteriaFileValidator(), registry=registry, evaluator=evaluator,
        sandbox=sandbox, persistence=persistence, settings=settings_service,
        mcp_preferences=MCPUserPreferences(),
    )


def build_server(project_root: Path, model, *, port: int = 0, workspace_root: Optional[Path] = None):
    """Constructs (but does not run) a uvicorn.Server bound to a real
    loopback socket, plus the bearer token callers must present. Split
    out from run() so tests can start/stop the server explicitly instead
    of blocking on the CLI entrypoint.

    workspace_root (Phase 12): the FilesystemSandbox boundary. Defaults to
    project_root's parent (existing Projects/MyProj test convention,
    unchanged) when omitted. A caller that wants the sandbox to be
    exactly project_root - e.g. the VS Code extension, spawning this
    process against exactly the folder the user opened, which should
    never widen into that folder's siblings - passes workspace_root
    explicitly equal to project_root.
    """
    services = build_services(project_root, model, workspace_root=workspace_root)
    token = generate_token()
    sock = bind_loopback_socket(port)
    app = create_app(services, token)
    config = uvicorn.Config(app, log_level="warning")
    server = uvicorn.Server(config)
    return server, sock, token


def run(project_root: str, *, port: int = 0, model=None, workspace_root: Optional[str] = None) -> None:
    resolved_workspace_root = Path(workspace_root).resolve() if workspace_root is not None else None
    server, sock, token = build_server(Path(project_root).resolve(), model, port=port,
                                        workspace_root=resolved_workspace_root)
    assigned_port = sock.getsockname()[1]
    print(startup_line(assigned_port, token), flush=True)
    server.run(sockets=[sock])


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="python -m agent_platform.server")
    parser.add_argument("--workspace-root", required=True, help="active project root the backend serves")
    parser.add_argument("--sandbox-root", default=None,
                         help="FilesystemSandbox boundary; defaults to --workspace-root's parent directory if "
                              "omitted (existing behavior, unchanged). Pass the same value as --workspace-root "
                              "to sandbox exactly that directory with no widening to sibling directories - this "
                              "is what the VS Code extension uses.")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)
    run(args.workspace_root, port=args.port, workspace_root=args.sandbox_root)


if __name__ == "__main__":
    main()
