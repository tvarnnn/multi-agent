import json

from agent_platform.orchestrator.ollama_schemas import (
    CODER_SCHEMA,
    PLANNER_SCHEMA,
    REVIEWER_SCHEMA,
)


def test_all_schemas_are_json_serializable():
    for schema in (PLANNER_SCHEMA, CODER_SCHEMA, REVIEWER_SCHEMA):
        json.dumps(schema)  # raises if not serializable


def test_planner_schema_covers_every_field_the_parser_reads():
    props = set(PLANNER_SCHEMA["properties"])
    assert props == {"kind", "goals", "constraints", "acceptance_criteria", "question"}
    assert PLANNER_SCHEMA["required"] == ["kind"]


def test_coder_schema_covers_every_field_the_parser_reads():
    props = set(CODER_SCHEMA["properties"])
    assert props == {"status", "spec_version_label", "summary", "file_writes",
                      "reason", "attempted", "blocking_questions"}
    assert set(CODER_SCHEMA["required"]) == {"status", "spec_version_label"}


def test_coder_schema_file_writes_items_require_path_and_content():
    item_schema = CODER_SCHEMA["properties"]["file_writes"]["items"]
    assert set(item_schema["required"]) == {"path", "content"}


def test_reviewer_schema_covers_every_field_the_parser_reads():
    props = set(REVIEWER_SCHEMA["properties"])
    assert props == {"spec_version_label", "decision", "requirements_met",
                      "security_ok", "validation_ok", "issues"}
    assert set(REVIEWER_SCHEMA["required"]) == {
        "spec_version_label", "decision", "requirements_met", "security_ok", "validation_ok"
    }


def test_reviewer_schema_issue_items_require_all_four_fields():
    item_schema = REVIEWER_SCHEMA["properties"]["issues"]["items"]
    assert set(item_schema["required"]) == {"severity", "file", "description", "required_fix"}
