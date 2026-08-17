"""Secret redaction, applied to MCP response data and error text before
either becomes part of a tool observation - the one path MCP-sourced
content takes back into the system. A server's own credential never
reaches this path in the first place (it lives only in MCPServerConfig
and is used only inside the client/transport layer, never passed as a
caller argument) - this exists to also catch a response that happens to
echo something secret-shaped back.
"""
from __future__ import annotations

from typing import Optional

_REDACTED = "[REDACTED]"


def redact_secret_string(text: Optional[str], secrets: tuple[str, ...]) -> Optional[str]:
    if text is None:
        return None
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, _REDACTED)
    return redacted


def redact_secrets(value, secrets: tuple[str, ...]):
    if not secrets:
        return value
    if isinstance(value, str):
        return redact_secret_string(value, secrets)
    if isinstance(value, dict):
        return {k: redact_secrets(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_secrets(v, secrets) for v in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(v, secrets) for v in value)
    return value
