from agent_platform.settings.credentials import resolve_credential_reference


def test_resolves_from_environment_variable(monkeypatch):
    monkeypatch.setenv("AGENT_PLATFORM_MCP_CREDENTIAL_GITHUB", "gh-token-value")
    assert resolve_credential_reference("github") == "gh-token-value"


def test_reference_is_uppercased_for_env_lookup(monkeypatch):
    monkeypatch.setenv("AGENT_PLATFORM_MCP_CREDENTIAL_MY_SERVER", "secret-value")
    assert resolve_credential_reference("my_server") == "secret-value"


def test_returns_none_when_env_var_absent(monkeypatch):
    monkeypatch.delenv("AGENT_PLATFORM_MCP_CREDENTIAL_UNSET_SERVER", raising=False)
    assert resolve_credential_reference("unset_server") is None


def test_returns_none_for_none_reference():
    assert resolve_credential_reference(None) is None


def test_raw_secret_looking_value_is_not_used_as_the_credential_itself(monkeypatch):
    """A settings file putting a raw secret directly where a reference name
    is expected must never work as a credential - it's treated purely as
    a (very unlikely to match) env-var-name lookup key, not as the secret
    value itself."""
    monkeypatch.delenv("AGENT_PLATFORM_MCP_CREDENTIAL_GHP_XXXXXXXXX", raising=False)
    assert resolve_credential_reference("ghp_xxxxxxxxx") is None
