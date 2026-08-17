from agent_platform.mcp.secrets import redact_secret_string, redact_secrets


def test_redact_secret_string_replaces_exact_occurrences():
    result = redact_secret_string("the token is sk-abc123 in this response", ("sk-abc123",))
    assert "sk-abc123" not in result
    assert "[REDACTED]" in result


def test_redact_secret_string_with_no_secrets_is_a_passthrough():
    assert redact_secret_string("nothing to hide", ()) == "nothing to hide"


def test_redact_secret_string_handles_none():
    assert redact_secret_string(None, ("secret",)) is None


def test_redact_secrets_walks_nested_dicts_and_lists():
    value = {"outer": {"inner": ["prefix sk-abc123 suffix", "clean"]}, "top": "sk-abc123"}
    redacted = redact_secrets(value, ("sk-abc123",))
    assert "sk-abc123" not in str(redacted)
    assert redacted["outer"]["inner"][1] == "clean"


def test_redact_secrets_leaves_non_string_values_alone():
    value = {"count": 5, "flag": True, "nothing": None}
    assert redact_secrets(value, ("secret",)) == value


def test_redact_secrets_with_no_secrets_returns_value_unchanged():
    value = {"token": "sk-abc123"}
    assert redact_secrets(value, ()) == value
