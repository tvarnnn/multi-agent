import pytest

from agent_platform.mcp.preferences import (
    MCPServerPreference,
    MCPUserPreferences,
    describe_server,
    effective_capabilities,
    narrow_capabilities,
)
from agent_platform.mcp.schemas import MCPServerConfig


class _StubClient:
    def __init__(self, discovered):
        self._discovered = discovered

    def discover(self):
        return self._discovered


# ------------------------------------------------------------- narrowing

def test_default_preference_is_enabled_with_no_overrides():
    prefs = MCPUserPreferences()
    assert prefs.get("github") == MCPServerPreference(enabled=True, capability_overrides={})


def test_narrow_capabilities_is_identity_when_no_preference_set():
    prefs = MCPUserPreferences()
    result = narrow_capabilities("github", {"repository_read", "issue_read"}, prefs)
    assert result == {"repository_read", "issue_read"}


def test_narrow_capabilities_can_only_remove_never_add():
    prefs = MCPUserPreferences()
    prefs.set_capability_enabled("github", "repository_read", False)
    # An override for a capability not in the discovered/trusted set must
    # be inert - it cannot conjure a new capability into existence.
    prefs.set_capability_enabled("github", "delete_repo", True)
    result = narrow_capabilities("github", {"repository_read", "issue_read"}, prefs)
    assert result == {"issue_read"}
    assert "delete_repo" not in result


def test_disabling_entire_server_yields_empty_capability_set():
    prefs = MCPUserPreferences()
    prefs.set_enabled("github", False)
    result = narrow_capabilities("github", {"repository_read", "issue_read"}, prefs)
    assert result == set()


def test_preferences_for_one_server_do_not_affect_another():
    prefs = MCPUserPreferences()
    prefs.set_enabled("github", False)
    result = narrow_capabilities("jira", {"issue_read"}, prefs)
    assert result == {"issue_read"}


def test_effective_capabilities_intersects_discovery_trusted_config_and_preference():
    server = MCPServerConfig(server_id="github", transport="stdio",
                              capabilities=("repository_read", "issue_read", "issue_write"))
    client = _StubClient(discovered=("repository_read", "issue_read", "commit"))
    prefs = MCPUserPreferences()
    prefs.set_capability_enabled("github", "issue_read", False)
    # discovered ∩ trusted = {repository_read, issue_read}; user disables issue_read.
    result = effective_capabilities(server, client, prefs)
    assert result == frozenset({"repository_read"})


def test_effective_capabilities_with_no_preferences_matches_plain_intersection():
    server = MCPServerConfig(server_id="github", transport="stdio",
                              capabilities=("repository_read", "issue_write"))
    client = _StubClient(discovered=("repository_read", "issue_write", "commit"))
    prefs = MCPUserPreferences()
    result = effective_capabilities(server, client, prefs)
    assert result == frozenset({"repository_read", "issue_write"})


# --------------------------------------------------------- credential omission

def test_describe_server_never_includes_credential_field():
    server = MCPServerConfig(server_id="github", transport="stdio",
                              capabilities=("repository_read",), credential="super-secret-token")
    client = _StubClient(discovered=("repository_read",))
    prefs = MCPUserPreferences()
    view = describe_server(server, client, prefs)
    assert "credential" not in view
    assert "super-secret-token" not in str(view)


def test_describe_server_reflects_enabled_state_and_capabilities():
    server = MCPServerConfig(server_id="github", transport="stdio",
                              capabilities=("repository_read", "issue_read"))
    client = _StubClient(discovered=("repository_read", "issue_read"))
    prefs = MCPUserPreferences()
    prefs.set_enabled("github", False)
    view = describe_server(server, client, prefs)
    assert view["enabled"] is False
    assert view["capabilities"] == []
