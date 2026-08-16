"""Structured output contracts for Planner, Coder, and Reviewer.

Every model output is a raw dict (standing in for parsed JSON from a real
model) and must pass one of these parse functions before it can influence
a state transition. Unconstrained model prose never controls the state
machine - a dict that doesn't match its schema raises
SchemaValidationError, which the orchestrator treats as a bounded-retry-
then-escalate case (see orchestrator/core.py), never as free-form input
to interpret.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Union


class SchemaValidationError(Exception):
    pass


def _require_str(d: dict, key: str) -> str:
    value = d.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"missing or invalid required string field: {key}")
    return value


def _require_str_allow_empty(d: dict, key: str) -> str:
    value = d.get(key)
    if not isinstance(value, str):
        raise SchemaValidationError(f"missing or invalid required string field: {key}")
    return value


def _require_bool(d: dict, key: str) -> bool:
    value = d.get(key)
    if not isinstance(value, bool):
        raise SchemaValidationError(f"missing or invalid required boolean field: {key}")
    return value


def _require_str_tuple(d: dict, key: str, *, allow_empty_list: bool = True) -> tuple:
    value = d.get(key)
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise SchemaValidationError(f"missing or invalid required string-list field: {key}")
    if not allow_empty_list and not value:
        raise SchemaValidationError(f"required string-list field must not be empty: {key}")
    return tuple(value)


def _require_dict(raw) -> dict:
    if not isinstance(raw, dict):
        raise SchemaValidationError("model output must be an object")
    return raw


# ---------------------------------------------------------------- Planner

@dataclass(frozen=True)
class PlannerSpec:
    goals: tuple[str, ...]
    constraints: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]


@dataclass(frozen=True)
class PlannerClarification:
    question: str


PlannerOutput = Union[PlannerSpec, PlannerClarification]


def parse_planner_output(raw) -> PlannerOutput:
    d = _require_dict(raw)
    kind = d.get("kind")
    if kind == "spec":
        return PlannerSpec(
            goals=_require_str_tuple(d, "goals"),
            constraints=_require_str_tuple(d, "constraints"),
            acceptance_criteria=_require_str_tuple(d, "acceptance_criteria"),
        )
    if kind == "needs_user_input":
        return PlannerClarification(question=_require_str(d, "question"))
    raise SchemaValidationError(f"unknown planner output kind: {kind!r}")


# ------------------------------------------------------------------ Coder

@dataclass(frozen=True)
class CoderFileWrite:
    path: str
    content: str


@dataclass(frozen=True)
class CoderCompleted:
    spec_version_label: str
    summary: str
    file_writes: tuple[CoderFileWrite, ...]


@dataclass(frozen=True)
class CoderBlocked:
    spec_version_label: str
    reason: str
    attempted: str
    blocking_questions: tuple[str, ...]


CoderOutput = Union[CoderCompleted, CoderBlocked]


def _parse_file_write(raw) -> CoderFileWrite:
    d = _require_dict(raw)
    return CoderFileWrite(path=_require_str(d, "path"), content=_require_str_allow_empty(d, "content"))


def parse_coder_output(raw) -> CoderOutput:
    d = _require_dict(raw)
    status = d.get("status")
    if status == "completed":
        writes_raw = d.get("file_writes")
        if not isinstance(writes_raw, list):
            raise SchemaValidationError("file_writes must be a list")
        return CoderCompleted(
            spec_version_label=_require_str(d, "spec_version_label"),
            summary=_require_str(d, "summary"),
            file_writes=tuple(_parse_file_write(w) for w in writes_raw),
        )
    if status == "blocked":
        return CoderBlocked(
            spec_version_label=_require_str(d, "spec_version_label"),
            reason=_require_str(d, "reason"),
            attempted=_require_str(d, "attempted"),
            blocking_questions=_require_str_tuple(d, "blocking_questions", allow_empty_list=False),
        )
    raise SchemaValidationError(f"unknown coder output status: {status!r}")


# --------------------------------------------------------------- Reviewer

@dataclass(frozen=True)
class ReviewerIssue:
    severity: str
    file: str
    description: str
    required_fix: str


@dataclass(frozen=True)
class ReviewerOutput:
    spec_version_label: str
    decision: str
    requirements_met: bool
    security_ok: bool
    validation_ok: bool
    issues: tuple[ReviewerIssue, ...]


def _parse_issue(raw) -> ReviewerIssue:
    d = _require_dict(raw)
    return ReviewerIssue(
        severity=_require_str(d, "severity"),
        file=_require_str(d, "file"),
        description=_require_str(d, "description"),
        required_fix=_require_str(d, "required_fix"),
    )


def parse_reviewer_output(raw) -> ReviewerOutput:
    d = _require_dict(raw)
    decision = d.get("decision")
    if decision not in ("APPROVE", "REJECT"):
        raise SchemaValidationError(f"invalid reviewer decision: {decision!r}")
    issues_raw = d.get("issues", [])
    if not isinstance(issues_raw, list):
        raise SchemaValidationError("issues must be a list")
    return ReviewerOutput(
        spec_version_label=_require_str(d, "spec_version_label"),
        decision=decision,
        requirements_met=_require_bool(d, "requirements_met"),
        security_ok=_require_bool(d, "security_ok"),
        validation_ok=_require_bool(d, "validation_ok"),
        issues=tuple(_parse_issue(i) for i in issues_raw),
    )
