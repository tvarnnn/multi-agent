"""In-memory, backend-owned MCP user preferences - a narrowing-only
overlay on top of trusted configuration and live discovery. This is
never a grant of authority: the effective capability set this module
computes is always a subset of what trusted config + discovery already
established (gateway_tools.py's discovered ∩ trusted-config-capabilities
intersection) - a user can disable a permitted capability, never enable
one trusted config/discovery didn't already permit. There is no code
path from a user preference to an ALLOW that trusted config/discovery
didn't already establish (design §12).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .schemas import MCPServerConfig


@dataclass(frozen=True)
class MCPServerPreference:
    enabled: bool = True
    capability_overrides: dict = field(default_factory=dict)  # capability -> bool


class MCPUserPreferences:
    """Only ever written by the authenticated `/mcp/servers/{id}/preferences`
    route (Task 5) - never by model output or an MCP server's own
    response. Unset servers/capabilities default to enabled=True, so
    "no preference recorded" behaves identically to "not narrowed"."""

    def __init__(self) -> None:
        self._preferences: dict[str, MCPServerPreference] = {}

    def get(self, server_id: str) -> MCPServerPreference:
        return self._preferences.get(server_id, MCPServerPreference())

    def set_enabled(self, server_id: str, enabled: bool) -> None:
        current = self.get(server_id)
        self._preferences[server_id] = MCPServerPreference(
            enabled=enabled, capability_overrides=dict(current.capability_overrides))

    def set_capability_enabled(self, server_id: str, capability: str, enabled: bool) -> None:
        current = self.get(server_id)
        overrides = dict(current.capability_overrides)
        overrides[capability] = enabled
        self._preferences[server_id] = MCPServerPreference(enabled=current.enabled, capability_overrides=overrides)


def narrow_capabilities(server_id: str, capabilities, preferences: MCPUserPreferences) -> set:
    """Return the subset of `capabilities` that remains after applying
    user preferences for `server_id`. Pure narrowing: the result is
    always a subset of `capabilities` - an override for a capability not
    already in `capabilities` is inert, never additive."""
    pref = preferences.get(server_id)
    if not pref.enabled:
        return set()
    return {cap for cap in capabilities if pref.capability_overrides.get(cap, True)}


def effective_capabilities(server_config: MCPServerConfig, client,
                            preferences: MCPUserPreferences) -> frozenset:
    """discovered ∩ trusted_config.capabilities ∩ user preference - the
    same discovery-can-only-narrow intersection gateway_tools.py already
    performs, with the user-preference narrowing layered on top."""
    discovered = set(client.discover())
    trusted = set(server_config.capabilities)
    base = discovered & trusted
    return frozenset(narrow_capabilities(server_config.server_id, base, preferences))


def describe_server(server_config: MCPServerConfig, client, preferences: MCPUserPreferences) -> dict:
    """Serializable view for the API layer. Deliberately omits the
    `credential` field entirely rather than masking it, so there is no
    redaction bug surface in the wire format at all (design §12)."""
    return {
        "server_id": server_config.server_id,
        "transport": server_config.transport,
        "enabled": preferences.get(server_config.server_id).enabled,
        "capabilities": sorted(effective_capabilities(server_config, client, preferences)),
    }
