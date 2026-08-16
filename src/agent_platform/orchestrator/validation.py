"""Deterministic validation interface. Phase 1 doesn't execute generated
code (no test.run/lint.run/typecheck.run tool exists yet - see the plan's
Global Constraints), so the one thing checkable without running arbitrary
code is file existence: an acceptance criterion of the form
'file:<relative-path>' is a real, working deterministic gate. Any other
criterion is recorded as advisory - honestly labeled as something this
phase cannot verify, rather than silently claiming a pass it can't back
up.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..spec.versioning import SpecVersion


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    details: tuple[str, ...]


class Validator(Protocol):
    def validate(self, project_root: Path, spec: SpecVersion) -> ValidationResult: ...


class AcceptanceCriteriaFileValidator:
    def validate(self, project_root: Path, spec: SpecVersion) -> ValidationResult:
        details = []
        passed = True
        for criterion in spec.acceptance_criteria:
            if criterion.startswith("file:"):
                rel = criterion[len("file:"):]
                if (project_root / rel).is_file():
                    details.append(f"OK: {criterion}")
                else:
                    details.append(f"MISSING: {criterion}")
                    passed = False
            else:
                details.append(f"ADVISORY (not deterministically checkable in Phase 1): {criterion}")
        return ValidationResult(passed=passed, details=tuple(details))
