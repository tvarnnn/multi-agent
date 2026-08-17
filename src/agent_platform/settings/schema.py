"""Frozen dataclasses for the Phase 11 settings/preference layer. Every
field here is plain data (str/bool/tuple/Optional of the same) - none of
it is a permission grant, a role assignment, or anything
PermissionEvaluator/ToolGateway/FilesystemSandbox would ever consult.
This module has no behavior of its own, only shape.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ModelSettings:
    planner: Optional[str] = None
    coder: Optional[str] = None
    reviewer: Optional[str] = None


@dataclass(frozen=True)
class McpServerSettingsEntry:
    server_id: str
    enabled: bool = True
    transport: str = "stdio"
    capabilities: tuple = ()
    credential_reference: Optional[str] = None


@dataclass(frozen=True)
class AgentBehaviorSettings:
    """Every field is Optional - None means "inherit PlatformConfig's own
    default", never a second, competing default. Field names mirror
    config.py's PlatformConfig fields exactly so builder.py's mapping is
    a straight pass-through, not a translation layer."""
    session_mode: Optional[str] = None
    max_output_retries: Optional[int] = None
    max_clarification_rounds: Optional[int] = None
    max_fix_iterations: Optional[int] = None
    max_plan_research_rounds: Optional[int] = None
    review_mode_allows_test_run: Optional[bool] = None
    agent_data_dir: Optional[str] = None
    context_compaction_enabled: Optional[bool] = None
    context_compaction_threshold_percent: Optional[int] = None
    max_conversation_tokens_estimate: Optional[int] = None
    tool_observation_retention: Optional[int] = None
    recent_message_window: Optional[int] = None


@dataclass(frozen=True)
class WorkspaceSettings:
    models: ModelSettings = field(default_factory=ModelSettings)
    mcp: dict = field(default_factory=dict)  # server_id -> McpServerSettingsEntry
    agent_behavior: AgentBehaviorSettings = field(default_factory=AgentBehaviorSettings)
