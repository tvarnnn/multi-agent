"""Trusted configuration loading. The workspace root and orchestrator-
level session settings are read from here only - never from LLM output,
never inferred at runtime from something a model said."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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

    @staticmethod
    def load(workspace_root: str, *, session_mode: SessionMode = SessionMode.AUTO,
              max_output_retries: int = 3, max_clarification_rounds: int = 3,
              max_fix_iterations: int = 3) -> "PlatformConfig":
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
        ):
            if value <= 0:
                raise ConfigurationError(f"{name} must be a positive integer, got: {value}")
        return PlatformConfig(
            workspace_root=root.resolve(strict=True), session_mode=session_mode,
            max_output_retries=max_output_retries, max_clarification_rounds=max_clarification_rounds,
            max_fix_iterations=max_fix_iterations,
        )
