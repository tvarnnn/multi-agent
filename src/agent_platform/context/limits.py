"""Explicit, deterministic bounds on context construction. Exceeding any
of these degrades deterministically - excess files are recorded in
ContextBundle.excluded_paths and oversized individual files are
truncated with a flag, never a silent overflow of whatever consumes the
bundle.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextLimits:
    max_files: int = 20
    max_total_bytes: int = 200_000
    max_tokens_estimate: int = 50_000
    max_individual_file_bytes: int = 20_000
    max_retrieval_depth: int = 6
    max_search_results: int = 50


DEFAULT_LIMITS = ContextLimits()


def estimate_tokens(text: str) -> int:
    """A deterministic, dependency-free token estimate (~4 chars/token) -
    good enough to bound context size without a tokenizer dependency."""
    return max(1, len(text) // 4)
