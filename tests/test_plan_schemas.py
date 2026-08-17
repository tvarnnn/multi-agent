import pytest

from agent_platform.orchestrator.model_schemas import PlannerClarification
from agent_platform.orchestrator.plan_schemas import (
    InvalidSpecIdError,
    PlanReview,
    ResearchRequest,
    ResearchRequestBatch,
    SchemaValidationError,
    StructuredPlan,
    parse_planner_plan_output,
    parse_reviewer_plan_output,
    validate_spec_id,
)


def _valid_plan_dict(**overrides):
    d = {
        "kind": "plan",
        "objective": "Build the widget",
        "requirements": ["req1"],
        "existing_context": ["ctx1"],
        "proposed_architecture": "single module",
        "files_to_create": ["widget.py"],
        "files_to_modify": [],
        "dependencies": [],
        "implementation_steps": ["step1"],
        "validation_strategy": ["test1"],
        "risks": [],
        "unknowns": [],
        "acceptance_criteria": ["file:widget.py"],
    }
    d.update(overrides)
    return d


# ---------------------------------------------------------------- spec_id

@pytest.mark.parametrize("spec_id", ["widget-1", "Widget_2", "a", "spec123"])
def test_valid_spec_ids_are_returned_unchanged(spec_id):
    assert validate_spec_id(spec_id) == spec_id


@pytest.mark.parametrize("spec_id", [
    "", "   ", "../escape", "a/b", "a\\b", "..", ".",
    "spec id with spaces", "spec/../id", "C:\\evil", "\\\\server\\share",
    "spec\x00id", "a" * 200, "спец",
])
def test_invalid_spec_ids_are_rejected_not_normalized(spec_id):
    # The approved substitution: invalid spec_ids are REJECTED outright,
    # never stripped/sanitized/transformed into something valid.
    with pytest.raises(InvalidSpecIdError):
        validate_spec_id(spec_id)


# ------------------------------------------------------------ planner plan

def test_parse_valid_structured_plan():
    result = parse_planner_plan_output(_valid_plan_dict())
    assert isinstance(result, StructuredPlan)
    assert result.objective == "Build the widget"
    assert result.requirements == ("req1",)
    assert result.reviewer_feedback == ()
    assert result.target_spec_version_label == ""


def test_parse_planner_clarification_is_reused_as_is():
    result = parse_planner_plan_output({"kind": "needs_user_input", "question": "which db?"})
    assert isinstance(result, PlannerClarification)
    assert result.question == "which db?"


def test_parse_research_request_batch():
    result = parse_planner_plan_output({
        "kind": "research_request",
        "requests": [{"capability": "mcp.github.repository_read", "query": "find auth code"}],
    })
    assert isinstance(result, ResearchRequestBatch)
    assert result.requests == (ResearchRequest(capability="mcp.github.repository_read", query="find auth code"),)


def test_parse_malformed_plan_missing_field_raises():
    bad = _valid_plan_dict()
    del bad["objective"]
    with pytest.raises(SchemaValidationError):
        parse_planner_plan_output(bad)


def test_parse_unknown_kind_raises():
    with pytest.raises(SchemaValidationError):
        parse_planner_plan_output({"kind": "nonsense"})


def test_parse_research_request_with_non_string_capability_raises():
    with pytest.raises(SchemaValidationError):
        parse_planner_plan_output({
            "kind": "research_request",
            "requests": [{"capability": 123, "query": "x"}],
        })


def test_parse_plan_output_requires_dict():
    with pytest.raises(SchemaValidationError):
        parse_planner_plan_output("not a dict")


# ----------------------------------------------------------- reviewer plan

def test_parse_valid_plan_review():
    result = parse_reviewer_plan_output({
        "comments": ["looks good"],
        "missing_requirements": [],
        "security_concerns": [],
        "unnecessary_complexity": [],
    })
    assert isinstance(result, PlanReview)
    assert result.comments == ("looks good",)


def test_parse_malformed_plan_review_raises():
    with pytest.raises(SchemaValidationError):
        parse_reviewer_plan_output({"comments": ["ok"]})
