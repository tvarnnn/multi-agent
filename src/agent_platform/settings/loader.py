"""YAML settings-file loading and strict parsing. yaml.safe_load only -
never yaml.load/an unsafe Loader - so a settings file can never construct
an arbitrary Python object, just plain dict/list/str/int/bool/None data.
Unknown keys at any level are a hard SettingsValidationError, never
silently ignored - a typo or an attempted new field never gets guessed at
or defaulted into something that "happens to work".
"""
from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Optional

import yaml

from .schema import AgentBehaviorSettings, McpServerSettingsEntry, ModelSettings, WorkspaceSettings

_ALLOWED_TOP_LEVEL_KEYS = {"models", "mcp", "agent_behavior"}
_ALLOWED_MODEL_KEYS = {"planner", "coder", "reviewer"}
_ALLOWED_MCP_ENTRY_KEYS = {"enabled", "transport", "capabilities", "credential"}
_ALLOWED_AGENT_BEHAVIOR_KEYS = {f.name for f in fields(AgentBehaviorSettings)}


class SettingsValidationError(Exception):
    pass


def load_settings_file(path: Path) -> Optional[dict]:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SettingsValidationError(f"malformed YAML in {path}: {exc}") from exc


def _parse_models(section) -> ModelSettings:
    if section is None:
        return ModelSettings()
    if not isinstance(section, dict):
        raise SettingsValidationError("models section must be a mapping")
    unknown = set(section.keys()) - _ALLOWED_MODEL_KEYS
    if unknown:
        raise SettingsValidationError(f"unknown models key(s): {sorted(unknown)}")
    for key, value in section.items():
        if value is not None and not isinstance(value, str):
            raise SettingsValidationError(f"models.{key} must be a string")
    return ModelSettings(planner=section.get("planner"), coder=section.get("coder"),
                          reviewer=section.get("reviewer"))


def _parse_mcp(section) -> dict:
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise SettingsValidationError("mcp section must be a mapping")
    result: dict = {}
    for server_id, entry in section.items():
        if not isinstance(entry, dict):
            raise SettingsValidationError(f"mcp.{server_id} must be a mapping")
        unknown = set(entry.keys()) - _ALLOWED_MCP_ENTRY_KEYS
        if unknown:
            raise SettingsValidationError(f"unknown mcp.{server_id} key(s): {sorted(unknown)}")
        capabilities = entry.get("capabilities", ())
        if not isinstance(capabilities, (list, tuple)):
            raise SettingsValidationError(f"mcp.{server_id}.capabilities must be a list")
        result[server_id] = McpServerSettingsEntry(
            server_id=server_id, enabled=bool(entry.get("enabled", True)),
            transport=str(entry.get("transport", "stdio")), capabilities=tuple(capabilities),
            credential_reference=entry.get("credential"),
        )
    return result


def _parse_agent_behavior(section) -> AgentBehaviorSettings:
    if section is None:
        return AgentBehaviorSettings()
    if not isinstance(section, dict):
        raise SettingsValidationError("agent_behavior section must be a mapping")
    unknown = set(section.keys()) - _ALLOWED_AGENT_BEHAVIOR_KEYS
    if unknown:
        raise SettingsValidationError(f"unknown agent_behavior key(s): {sorted(unknown)}")
    return AgentBehaviorSettings(**section)


def parse_settings(raw: Optional[dict]) -> WorkspaceSettings:
    if raw is None:
        return WorkspaceSettings()
    if not isinstance(raw, dict):
        raise SettingsValidationError("settings file root must be a mapping")
    unknown = set(raw.keys()) - _ALLOWED_TOP_LEVEL_KEYS
    if unknown:
        raise SettingsValidationError(f"unknown top-level settings key(s): {sorted(unknown)}")
    return WorkspaceSettings(
        models=_parse_models(raw.get("models")),
        mcp=_parse_mcp(raw.get("mcp")),
        agent_behavior=_parse_agent_behavior(raw.get("agent_behavior")),
    )


def merge_settings(global_: Optional[WorkspaceSettings],
                    workspace: Optional[WorkspaceSettings]) -> WorkspaceSettings:
    """Per-top-level-section wholesale override: if workspace specifies
    anything in a section (models/mcp/agent_behavior), that section wins
    entirely; otherwise global's value for that section is used. Never
    field-by-field deep merged - deterministic and simple to reason about."""
    g = global_ if global_ is not None else WorkspaceSettings()
    w = workspace if workspace is not None else WorkspaceSettings()
    models = w.models if w.models != ModelSettings() else g.models
    mcp = w.mcp if w.mcp else g.mcp
    agent_behavior = w.agent_behavior if w.agent_behavior != AgentBehaviorSettings() else g.agent_behavior
    return WorkspaceSettings(models=models, mcp=mcp, agent_behavior=agent_behavior)
