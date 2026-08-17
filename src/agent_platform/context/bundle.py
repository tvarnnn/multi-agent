"""ContextBundle: the inspectable output of context retrieval. Every
field is plain data - file content is always a string, never anything
downstream interprets as an instruction.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextFile:
    path: str
    content: str
    category: str
    truncated: bool = False


@dataclass(frozen=True)
class ContextBundle:
    role: str
    files: tuple
    changed_files: tuple
    excluded_paths: tuple
    stale_paths: tuple
    total_bytes: int
    limit_exceeded: bool
