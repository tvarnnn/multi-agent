"""Deterministic, pure rendering of a StructuredPlan to Markdown. One
field, one section, no model-authored Markdown structure - the model
never controls formatting, only the typed content that gets slotted in.

This Markdown is audit documentation only, never read back as an
authority - see orchestrator/plan_artifacts.py. The renderer takes no
I/O dependency and has no side effects, so "same rendering in, same
bytes out, every time" is a property this module's own tests check
directly (test_plan_markdown.py).
"""
from __future__ import annotations

from .plan_schemas import StructuredPlan


def _bullet_section(title: str, items: tuple[str, ...]) -> str:
    body = "\n".join(f"- {item}" for item in items)
    return f"## {title}\n\n{body}\n"


def _numbered_section(title: str, items: tuple[str, ...]) -> str:
    body = "\n".join(f"{i}. {item}" for i, item in enumerate(items, start=1))
    return f"## {title}\n\n{body}\n"


def _text_section(title: str, text: str) -> str:
    return f"## {title}\n\n{text}\n"


def render_plan_markdown(plan: StructuredPlan, *, status: str, spec_version_label: str) -> str:
    sections = [
        f"# Implementation Plan\n\nSpecification Version: {spec_version_label}\nStatus: {status}\n",
        _text_section("Objective", plan.objective),
        _bullet_section("Requirements", plan.requirements),
        _bullet_section("Existing Context", plan.existing_context),
        _text_section("Proposed Architecture", plan.proposed_architecture),
        _bullet_section("Files to Create", plan.files_to_create),
        _bullet_section("Files to Modify", plan.files_to_modify),
        _bullet_section("Dependencies", plan.dependencies),
        _numbered_section("Implementation Steps", plan.implementation_steps),
        _bullet_section("Validation Strategy", plan.validation_strategy),
        _bullet_section("Risks", plan.risks),
        _bullet_section("Unknowns", plan.unknowns),
        _bullet_section("Acceptance Criteria", plan.acceptance_criteria),
        _reviewer_feedback_section(plan.reviewer_feedback),
        "## Specification\n",
    ]
    return "\n".join(sections)


def _reviewer_feedback_section(reviewer_feedback: tuple[str, ...]) -> str:
    if not reviewer_feedback:
        return "## Reviewer Feedback\n\n_No reviewer feedback yet._\n"
    return _bullet_section("Reviewer Feedback", reviewer_feedback)
