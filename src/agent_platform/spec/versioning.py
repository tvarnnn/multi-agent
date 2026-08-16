"""Immutable specification versioning primitives.

A task's requirements live in a SpecVersion. Amending requirements
creates a new SpecVersion; existing versions are never mutated - this is
enforced structurally (frozen dataclass, append-only store), not by
convention. Every Coder and Reviewer invocation is pinned to an exact
spec_id + version; SpecStore.assert_current deterministically rejects a
stale reference rather than silently operating against outdated
requirements.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SpecVersion:
    spec_id: str
    version: int
    goals: tuple[str, ...]
    constraints: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    created_at: float = field(default_factory=time.time)

    @property
    def version_label(self) -> str:
        return f"{self.spec_id}-v{self.version}"


class SpecVersionMismatchError(Exception):
    def __init__(self, expected: str, actual: str):
        super().__init__(
            f"specification version mismatch: expected {expected}, invocation pinned to {actual}"
        )
        self.expected = expected
        self.actual = actual


class SpecStore:
    """Append-only store of specification versions. Never mutates an
    existing version - amending requirements always creates version N+1."""

    def __init__(self) -> None:
        self._versions: dict[str, list[SpecVersion]] = {}

    def create(self, spec_id: str, *, goals, constraints, acceptance_criteria) -> SpecVersion:
        existing = self._versions.setdefault(spec_id, [])
        next_version = len(existing) + 1
        spec = SpecVersion(
            spec_id=spec_id,
            version=next_version,
            goals=tuple(goals),
            constraints=tuple(constraints),
            acceptance_criteria=tuple(acceptance_criteria),
        )
        existing.append(spec)
        return spec

    def latest(self, spec_id: str) -> SpecVersion:
        versions = self._versions.get(spec_id)
        if not versions:
            raise KeyError(f"no specification versions for {spec_id}")
        return versions[-1]

    def get(self, spec_id: str, version: int) -> SpecVersion:
        for v in self._versions.get(spec_id, []):
            if v.version == version:
                return v
        raise KeyError(f"{spec_id}-v{version} does not exist")

    def assert_current(self, spec_id: str, version_label: str) -> SpecVersion:
        current = self.latest(spec_id)
        if current.version_label != version_label:
            raise SpecVersionMismatchError(expected=current.version_label, actual=version_label)
        return current
