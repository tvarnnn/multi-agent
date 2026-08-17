"""Trusted configuration loading. The workspace root and orchestrator-
level session settings are read from here only - never from LLM output,
never inferred at runtime from something a model said."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from .security.enums import SessionMode


class ConfigurationError(Exception):
    pass


@dataclass(frozen=True)
class PlatformConfig:
    workspace_root: Path
    session_mode: SessionMode = SessionMode.AUTO
    max_output_retries: int = 3
    max_clarification_rounds: int = 3
    max_fix_iterations: int = 3
    max_plan_research_rounds: int = 3
    review_mode_allows_test_run: bool = False
    # Phase 10 - persistence/context-management. Configuration only ever
    # narrows what gets retained/reconstructed; it has no path to
    # permissions, roles, OperatingMode, or SpecStore - those stay
    # entirely owned by security/permission.py, security/mode_policy.py,
    # and spec/versioning.py respectively.
    agent_data_dir: str = ".agent"
    context_compaction_enabled: bool = True
    context_compaction_threshold_percent: int = 85
    max_conversation_tokens_estimate: int = 20_000
    tool_observation_retention: int = 200
    recent_message_window: int = 20

    @staticmethod
    def load(workspace_root: str, *, session_mode: SessionMode = SessionMode.AUTO,
              max_output_retries: int = 3, max_clarification_rounds: int = 3,
              max_fix_iterations: int = 3, max_plan_research_rounds: int = 3,
              review_mode_allows_test_run: bool = False, agent_data_dir: str = ".agent",
              context_compaction_enabled: bool = True, context_compaction_threshold_percent: int = 85,
              max_conversation_tokens_estimate: int = 20_000, tool_observation_retention: int = 200,
              recent_message_window: int = 20) -> "PlatformConfig":
        root = Path(workspace_root)
        if not root.is_absolute():
            raise ConfigurationError(f"workspace_root must be an absolute path, got: {workspace_root}")
        if not root.exists():
            raise ConfigurationError(f"workspace_root does not exist: {root}")
        if not root.is_dir():
            raise ConfigurationError(f"workspace_root is not a directory: {root}")
        for name, value in (
            ("max_output_retries", max_output_retries),
            ("max_clarification_rounds", max_clarification_rounds),
            ("max_fix_iterations", max_fix_iterations),
            ("max_plan_research_rounds", max_plan_research_rounds),
            ("max_conversation_tokens_estimate", max_conversation_tokens_estimate),
            ("tool_observation_retention", tool_observation_retention),
            ("recent_message_window", recent_message_window),
        ):
            if value <= 0:
                raise ConfigurationError(f"{name} must be a positive integer, got: {value}")
        if not 1 <= context_compaction_threshold_percent <= 100:
            raise ConfigurationError(
                f"context_compaction_threshold_percent must be in [1, 100], "
                f"got: {context_compaction_threshold_percent}"
            )
        stripped = agent_data_dir.strip() if agent_data_dir else ""
        if (not stripped or stripped.startswith(("/", "\\")) or ":" in stripped
                or PureWindowsPath(agent_data_dir).is_absolute()
                or ".." in PureWindowsPath(agent_data_dir).parts):
            raise ConfigurationError(f"agent_data_dir must be a non-empty relative path, got: {agent_data_dir!r}")
        return PlatformConfig(
            workspace_root=root.resolve(strict=True), session_mode=session_mode,
            max_output_retries=max_output_retries, max_clarification_rounds=max_clarification_rounds,
            max_fix_iterations=max_fix_iterations, max_plan_research_rounds=max_plan_research_rounds,
            review_mode_allows_test_run=review_mode_allows_test_run, agent_data_dir=agent_data_dir,
            context_compaction_enabled=context_compaction_enabled,
            context_compaction_threshold_percent=context_compaction_threshold_percent,
            max_conversation_tokens_estimate=max_conversation_tokens_estimate,
            tool_observation_retention=tool_observation_retention,
            recent_message_window=recent_message_window,
        )
