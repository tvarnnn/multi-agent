"""Turns parsed WorkspaceSettings into the exact inputs the existing
trusted-config constructors already accept - PlatformConfig.load()'s
kwargs and a tuple[MCPServerConfig, ...]. Neither output is validated
here beyond type/shape checks already done in loader.py; the real
validation is PlatformConfig.load()'s own (unchanged) checks and
MCPServerConfig's own (unchanged) dataclass shape - this module never
duplicates that logic, only feeds it.
"""
from __future__ import annotations

from ..mcp.schemas import MCPServerConfig
from ..security.enums import SessionMode
from .credentials import resolve_credential_reference
from .loader import SettingsValidationError
from .schema import WorkspaceSettings

PASSTHROUGH_FIELDS = (
    "max_output_retries", "max_clarification_rounds", "max_fix_iterations",
    "max_plan_research_rounds", "review_mode_allows_test_run", "agent_data_dir",
    "context_compaction_enabled", "context_compaction_threshold_percent",
    "max_conversation_tokens_estimate", "tool_observation_retention", "recent_message_window",
)


def build_platform_config_kwargs(settings: WorkspaceSettings) -> dict:
    ab = settings.agent_behavior
    kwargs: dict = {}
    if ab.session_mode is not None:
        try:
            kwargs["session_mode"] = SessionMode(ab.session_mode)
        except ValueError as exc:
            raise SettingsValidationError(
                f"invalid agent_behavior.session_mode: {ab.session_mode!r}") from exc
    for field_name in PASSTHROUGH_FIELDS:
        value = getattr(ab, field_name)
        if value is not None:
            kwargs[field_name] = value
    return kwargs


def build_mcp_server_configs(settings: WorkspaceSettings) -> tuple:
    configs = []
    for server_id, entry in settings.mcp.items():
        if not entry.enabled:
            continue
        configs.append(MCPServerConfig(
            server_id=server_id, transport=entry.transport, capabilities=entry.capabilities,
            credential=resolve_credential_reference(entry.credential_reference),
        ))
    return tuple(configs)
