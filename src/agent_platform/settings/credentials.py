"""The one place a credential *reference* (a name in a settings file)
becomes a credential *value*. Resolves via environment variable only - no
new secret-storage mechanism is introduced. A settings file can never
carry a raw secret through this function "by accident": the input is
always treated as a lookup key, never as the value itself.
"""
from __future__ import annotations

import os
from typing import Optional

_ENV_PREFIX = "AGENT_PLATFORM_MCP_CREDENTIAL_"


def resolve_credential_reference(reference: Optional[str]) -> Optional[str]:
    if reference is None:
        return None
    return os.environ.get(f"{_ENV_PREFIX}{reference.upper()}")
