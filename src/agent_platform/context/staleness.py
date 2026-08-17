"""Session-scoped staleness detection. Not a persistent index - Phase 5
concludes one isn't needed yet (see PHASE5_REPORT.md) - but this is
exactly the primitive a future persistent index would need: compare a
freshly-read file's content hash against what was last seen in this
session, report a mismatch as stale, and the caller always uses the
fresh read, never the cached view, regardless of the result.
"""
from __future__ import annotations

import hashlib


class ContextCache:
    def __init__(self) -> None:
        self._hashes: dict = {}

    def check_and_update(self, path: str, content: str) -> bool:
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        previous = self._hashes.get(path)
        is_stale = previous is not None and previous != content_hash
        self._hashes[path] = content_hash
        return is_stale
