from agent_platform.orchestrator.plan_markdown import render_plan_markdown
from agent_platform.orchestrator.plan_schemas import StructuredPlan


def _plan(**overrides):
    fields = dict(
        objective="Build the widget",
        requirements=("req1", "req2"),
        existing_context=("ctx1",),
        proposed_architecture="single module",
        files_to_create=("widget.py",),
        files_to_modify=("app.py",),
        dependencies=("requests",),
        implementation_steps=("step1", "step2"),
        validation_strategy=("run pytest",),
        risks=("risk1",),
        unknowns=("unknown1",),
        acceptance_criteria=("file:widget.py",),
    )
    fields.update(overrides)
    return StructuredPlan(**fields)


EXPECTED = """# Implementation Plan

Specification Version: widget-v1
Status: DRAFT

## Objective

Build the widget

## Requirements

- req1
- req2

## Existing Context

- ctx1

## Proposed Architecture

single module

## Files to Create

- widget.py

## Files to Modify

- app.py

## Dependencies

- requests

## Implementation Steps

1. step1
2. step2

## Validation Strategy

- run pytest

## Risks

- risk1

## Unknowns

- unknown1

## Acceptance Criteria

- file:widget.py

## Reviewer Feedback

_No reviewer feedback yet._

## Specification
"""


def test_render_plan_markdown_is_deterministic_and_matches_expected_bytes():
    rendered = render_plan_markdown(_plan(), status="DRAFT", spec_version_label="widget-v1")
    assert rendered == EXPECTED


def test_render_plan_markdown_is_stable_across_repeated_calls():
    plan = _plan()
    first = render_plan_markdown(plan, status="DRAFT", spec_version_label="widget-v1")
    second = render_plan_markdown(plan, status="DRAFT", spec_version_label="widget-v1")
    assert first == second


def test_render_plan_markdown_includes_reviewer_feedback_when_present():
    plan = _plan(reviewer_feedback=("Consider edge case X", "Missing test for Y"))
    rendered = render_plan_markdown(plan, status="REVISED", spec_version_label="widget-v2")
    assert "Status: REVISED" in rendered
    assert "Specification Version: widget-v2" in rendered
    assert "- Consider edge case X" in rendered
    assert "- Missing test for Y" in rendered
    assert "_No reviewer feedback yet._" not in rendered
