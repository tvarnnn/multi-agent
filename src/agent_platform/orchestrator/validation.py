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


class TestRunValidator:
    """Deterministic validator that actually runs the project's tests
    via the test.run typed tool, instead of only checking that files
    exist. This is what makes COMPLETE actually require passing tests -
    Orchestrator._final_validation ANDs this result with reviewer
    approval, unchanged since Phase 1, so a reviewer APPROVE can never
    override a real test failure here.
    """

    def __init__(self, gateway, role, session_mode) -> None:
        self._gateway = gateway
        self._role = role
        self._session_mode = session_mode

    def validate(self, project_root: Path, spec: SpecVersion) -> ValidationResult:
        obs = self._gateway.invoke(
            role=self._role, tool_name="test.run", arguments={},
            session_mode=self._session_mode, project_root=project_root,
        )
        if obs.status != "ok":
            return ValidationResult(
                passed=False,
                details=(f"test.run could not execute: {obs.status} - {obs.error}",),
            )
        result = obs.result
        detail = f"test.run exit_code={result['exit_code']} passed={result['passed']}"
        if result.get("timed_out"):
            detail += " (TIMED OUT)"
        return ValidationResult(passed=result["passed"], details=(detail,))


class CompositeValidator:
    """ANDs multiple validators together - COMPLETE requires every one
    of them to pass, not just the last one checked."""

    def __init__(self, validators: tuple) -> None:
        self._validators = validators

    def validate(self, project_root: Path, spec: SpecVersion) -> ValidationResult:
        all_details: list = []
        all_passed = True
        for validator in self._validators:
            result = validator.validate(project_root, spec)
            all_details.extend(result.details)
            all_passed = all_passed and result.passed
        return ValidationResult(passed=all_passed, details=tuple(all_details))
