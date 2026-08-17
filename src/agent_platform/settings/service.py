"""SettingsService: the single facade server.py/backend_api.py use for
the Phase 11 preference layer. Loads + merges global/workspace settings
once at startup; everything downstream (PlatformConfig.load() kwargs, the
trusted MCPServerConfig tuple, the safe API view) is derived from that one
merged WorkspaceSettings instance. Nothing here calls
PermissionEvaluator/ToolGateway/FilesystemSandbox - this module only ever
produces INPUTS to the existing trusted constructors, never a second
authority.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .builder import PASSTHROUGH_FIELDS, build_mcp_server_configs, build_platform_config_kwargs
from .loader import load_settings_file, merge_settings, parse_settings
from .model_discovery import describe_configured_models
from .schema import ModelSettings, WorkspaceSettings


class SettingsService:
    def __init__(self, *, settings: WorkspaceSettings, global_loaded: bool, workspace_loaded: bool):
        self._settings = settings
        self._global_loaded = global_loaded
        self._workspace_loaded = workspace_loaded
        self._platform_config = None

    @staticmethod
    def load(*, global_path: Optional[Path], workspace_path: Optional[Path]) -> "SettingsService":
        global_raw = load_settings_file(global_path) if global_path is not None else None
        workspace_raw = load_settings_file(workspace_path) if workspace_path is not None else None
        global_settings = parse_settings(global_raw) if global_raw is not None else None
        workspace_settings = parse_settings(workspace_raw) if workspace_raw is not None else None
        merged = merge_settings(global_settings, workspace_settings)
        return SettingsService(settings=merged, global_loaded=global_raw is not None,
                                workspace_loaded=workspace_raw is not None)

    @property
    def model_settings(self) -> ModelSettings:
        return self._settings.models

    @property
    def mcp_server_configs(self) -> tuple:
        return build_mcp_server_configs(self._settings)

    @property
    def platform_config_kwargs(self) -> dict:
        return build_platform_config_kwargs(self._settings)

    def bind_platform_config(self, platform_config) -> None:
        """Called once by server.py after PlatformConfig.load() succeeds,
        so safe_view() can report the values actually in force (post-
        validation) rather than a stale pre-validation copy."""
        self._platform_config = platform_config

    def safe_view(self) -> dict:
        mcp_view = {
            server_id: {"enabled": entry.enabled, "transport": entry.transport,
                        "capabilities": list(entry.capabilities)}
            for server_id, entry in self._settings.mcp.items()
        }
        agent_behavior_view = {}
        if self._platform_config is not None:
            for field_name in (*PASSTHROUGH_FIELDS, "session_mode"):
                value = getattr(self._platform_config, field_name)
                agent_behavior_view[field_name] = value.value if hasattr(value, "value") else value
        return {
            "models": describe_configured_models(self._settings.models, installed=None),
            "mcp": mcp_view,
            "agent_behavior": agent_behavior_view,
            "precedence": {"global_loaded": self._global_loaded, "workspace_loaded": self._workspace_loaded},
        }
