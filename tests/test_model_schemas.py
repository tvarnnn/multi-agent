import pytest

from agent_platform.orchestrator.model_schemas import (
    CoderBlocked,
    CoderCompleted,
    PlannerClarification,
    PlannerSpec,
    ReviewerOutput,
    SchemaValidationError,
    parse_coder_output,
    parse_planner_output,
    parse_reviewer_output,
)


def test_parse_planner_spec():
    raw = {"kind": "spec", "goals": ["build a thing"], "constraints": ["no network"],
           "acceptance_criteria": ["file:app.py"]}
    result = parse_planner_output(raw)
    assert isinstance(result, PlannerSpec)
    assert result.goals == ("build a thing",)
    assert result.constraints == ("no network",)
    assert result.acceptance_criteria == ("file:app.py",)


def test_parse_planner_clarification():
    raw = {"kind": "needs_user_input", "question": "OAuth or API keys?"}
    result = parse_planner_output(raw)
    assert isinstance(result, PlannerClarification)
    assert result.question == "OAuth or API keys?"


@pytest.mark.parametrize("raw", [
    {},
    {"kind": "spec"},
    {"kind": "spec", "goals": "not-a-list", "constraints": [], "acceptance_criteria": []},
    {"kind": "spec", "goals": [1, 2], "constraints": [], "acceptance_criteria": []},
    {"kind": "needs_user_input"},
    {"kind": "needs_user_input", "question": ""},
    {"kind": "unknown_kind"},
    "not a dict",
    None,
])
def test_malformed_planner_output_is_rejected(raw):
    with pytest.raises(SchemaValidationError):
        parse_planner_output(raw)


def test_parse_coder_completed():
    raw = {
        "status": "completed", "spec_version_label": "task-1-v1",
        "summary": "wrote the app", "file_writes": [
            {"path": "app.py", "content": "print('hi')"},
        ],
    }
    result = parse_coder_output(raw)
    assert isinstance(result, CoderCompleted)
    assert result.spec_version_label == "task-1-v1"
    assert result.file_writes[0].path == "app.py"
    assert result.file_writes[0].content == "print('hi')"


def test_parse_coder_completed_allows_empty_file_content():
    raw = {"status": "completed", "spec_version_label": "task-1-v1", "summary": "s",
           "file_writes": [{"path": "empty.py", "content": ""}]}
    result = parse_coder_output(raw)
    assert result.file_writes[0].content == ""


def test_parse_coder_blocked():
    raw = {"status": "blocked", "spec_version_label": "task-1-v1", "reason": "ambiguous auth",
           "attempted": "looked at existing code", "blocking_questions": ["OAuth or API keys?"]}
    result = parse_coder_output(raw)
    assert isinstance(result, CoderBlocked)
    assert result.blocking_questions == ("OAuth or API keys?",)


@pytest.mark.parametrize("raw", [
    {},
    {"status": "completed"},
    {"status": "completed", "spec_version_label": "v1", "summary": "s", "file_writes": "not-a-list"},
    {"status": "completed", "spec_version_label": "v1", "summary": "s",
     "file_writes": [{"path": "x.py"}]},
    {"status": "blocked", "spec_version_label": "v1"},
    {"status": "unknown"},
    "not a dict",
])
def test_malformed_coder_output_is_rejected(raw):
    with pytest.raises(SchemaValidationError):
        parse_coder_output(raw)


def test_parse_reviewer_approve():
    raw = {"spec_version_label": "task-1-v1", "decision": "APPROVE", "requirements_met": True,
           "security_ok": True, "validation_ok": True, "issues": []}
    result = parse_reviewer_output(raw)
    assert isinstance(result, ReviewerOutput)
    assert result.decision == "APPROVE"
    assert result.issues == ()


def test_parse_reviewer_reject_with_issues():
    raw = {"spec_version_label": "task-1-v1", "decision": "REJECT", "requirements_met": False,
           "security_ok": True, "validation_ok": True,
           "issues": [{"severity": "high", "file": "app.py", "description": "missing auth",
                       "required_fix": "add auth check"}]}
    result = parse_reviewer_output(raw)
    assert result.decision == "REJECT"
    assert len(result.issues) == 1
    assert result.issues[0].severity == "high"


@pytest.mark.parametrize("raw", [
    {},
    {"spec_version_label": "v1", "decision": "MAYBE", "requirements_met": True,
     "security_ok": True, "validation_ok": True, "issues": []},
    {"spec_version_label": "v1", "decision": "APPROVE", "requirements_met": "yes",
     "security_ok": True, "validation_ok": True, "issues": []},
    {"spec_version_label": "v1", "decision": "REJECT", "requirements_met": False,
     "security_ok": True, "validation_ok": True,
     "issues": [{"severity": "high", "file": "app.py"}]},
    "not a dict",
])
def test_malformed_reviewer_output_is_rejected(raw):
    with pytest.raises(SchemaValidationError):
        parse_reviewer_output(raw)
