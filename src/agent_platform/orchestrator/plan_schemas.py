"""Structured output contracts for Planning Mode. Kept separate from
model_schemas.py, which stays scoped to the Code-mode Planner/Coder/
Reviewer contracts it already owns. Same validation style: a raw dict
must pass a parse function or raise SchemaValidationError, which the
orchestrator's existing retry/escalate handling already knows how to
deal with - no new error-handling concept is introduced.

spec_id validation here is deliberately a REJECT, never a sanitize: an
invalid spec_id raises InvalidSpecIdError and is refused outright. It is
never stripped, transformed, or otherwise "fixed" into something a
filesystem path would accept - the caller must supply a valid spec_id or
the operation does not proceed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Union

from .model_schemas import PlannerClarification, SchemaValidationError

__all__ = [
    "SchemaValidationError",
    "InvalidSpecIdError",
    "validate_spec_id",
    "ResearchRequest",
    "ResearchRequestBatch",
    "StructuredPlan",
    "PlannerPlanOutput",
    "parse_planner_plan_output",
    "PlanReview",
    "parse_reviewer_plan_output",
    "ChatReply",
    "parse_chat_output",
    "ReviewSessionOutput",
    "parse_review_session_output",
]


class InvalidSpecIdError(Exception):
    """Raised when a spec_id does not meet the strict validity rules.
    Never caught to retry with a "fixed" value - the caller must supply
    a valid spec_id."""


_SPEC_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def validate_spec_id(spec_id: str) -> str:
    """Return spec_id unchanged if valid, otherwise raise
    InvalidSpecIdError. Rejects, never normalizes: no stripping of
    whitespace, no character substitution, no truncation."""
    if not isinstance(spec_id, str) or not _SPEC_ID_PATTERN.match(spec_id):
        raise InvalidSpecIdError(f"invalid spec_id: {spec_id!r}")
    return spec_id


def _require_str(d: dict, key: str) -> str:
    value = d.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"missing or invalid required string field: {key}")
    return value


def _require_str_tuple(d: dict, key: str) -> tuple:
    value = d.get(key)
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise SchemaValidationError(f"missing or invalid required string-list field: {key}")
    return tuple(value)


def _require_dict(raw) -> dict:
    if not isinstance(raw, dict):
        raise SchemaValidationError("model output must be an object")
    return raw


# ------------------------------------------------------------- research

@dataclass(frozen=True)
class ResearchRequest:
    capability: str
    query: str


@dataclass(frozen=True)
class ResearchRequestBatch:
    requests: tuple[ResearchRequest, ...]


def _parse_research_request(raw) -> ResearchRequest:
    d = _require_dict(raw)
    return ResearchRequest(capability=_require_str(d, "capability"), query=_require_str(d, "query"))


# --------------------------------------------------------- structured plan

@dataclass(frozen=True)
class StructuredPlan:
    objective: str
    requirements: tuple[str, ...]
    existing_context: tuple[str, ...]
    proposed_architecture: str
    files_to_create: tuple[str, ...]
    files_to_modify: tuple[str, ...]
    dependencies: tuple[str, ...]
    implementation_steps: tuple[str, ...]
    validation_strategy: tuple[str, ...]
    risks: tuple[str, ...]
    unknowns: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    reviewer_feedback: tuple[str, ...] = ()
    target_spec_version_label: str = ""


PlannerPlanOutput = Union[StructuredPlan, PlannerClarification, ResearchRequestBatch]

_STRUCTURED_PLAN_STR_FIELDS = ("objective", "proposed_architecture")
_STRUCTURED_PLAN_TUPLE_FIELDS = (
    "requirements", "existing_context", "files_to_create", "files_to_modify",
    "dependencies", "implementation_steps", "validation_strategy", "risks",
    "unknowns", "acceptance_criteria",
)


def _parse_structured_plan(d: dict) -> StructuredPlan:
    fields = {name: _require_str(d, name) for name in _STRUCTURED_PLAN_STR_FIELDS}
    fields.update({name: _require_str_tuple(d, name) for name in _STRUCTURED_PLAN_TUPLE_FIELDS})
    return StructuredPlan(**fields)


def parse_planner_plan_output(raw) -> PlannerPlanOutput:
    d = _require_dict(raw)
    kind = d.get("kind")
    if kind == "plan":
        return _parse_structured_plan(d)
    if kind == "needs_user_input":
        return PlannerClarification(question=_require_str(d, "question"))
    if kind == "research_request":
        requests_raw = d.get("requests")
        if not isinstance(requests_raw, list):
            raise SchemaValidationError("requests must be a list")
        return ResearchRequestBatch(requests=tuple(_parse_research_request(r) for r in requests_raw))
    raise SchemaValidationError(f"unknown planner plan-mode output kind: {kind!r}")


# ---------------------------------------------------------------- review

@dataclass(frozen=True)
class PlanReview:
    comments: tuple[str, ...]
    missing_requirements: tuple[str, ...]
    security_concerns: tuple[str, ...]
    unnecessary_complexity: tuple[str, ...]


def parse_reviewer_plan_output(raw) -> PlanReview:
    d = _require_dict(raw)
    return PlanReview(
        comments=_require_str_tuple(d, "comments"),
        missing_requirements=_require_str_tuple(d, "missing_requirements"),
        security_concerns=_require_str_tuple(d, "security_concerns"),
        unnecessary_complexity=_require_str_tuple(d, "unnecessary_complexity"),
    )


# ------------------------------------------------------------------ chat

@dataclass(frozen=True)
class ChatReply:
    message: str


def parse_chat_output(raw) -> ChatReply:
    d = _require_dict(raw)
    return ChatReply(message=_require_str(d, "message"))


# -------------------------------------------------------------- review mode

@dataclass(frozen=True)
class ReviewSessionOutput:
    summary: str
    findings: tuple[str, ...]


def parse_review_session_output(raw) -> ReviewSessionOutput:
    d = _require_dict(raw)
    return ReviewSessionOutput(summary=_require_str(d, "summary"), findings=_require_str_tuple(d, "findings"))
