"""JSON Schema objects passed as Ollama's `format` parameter to
grammar-constrain each role's output at the model layer (architecture-
review-v2.md section 1.11). Field sets here are deliberately kept in
lockstep with orchestrator/model_schemas.py's parse functions - this is
the syntactic half of structured output; the semantic half (are the
right fields present for this "kind"/"status"/"decision") is still
enforced there, independently.
"""
from __future__ import annotations

PLANNER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["spec", "needs_user_input"]},
        "goals": {"type": "array", "items": {"type": "string"}},
        "constraints": {"type": "array", "items": {"type": "string"}},
        "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
        "question": {"type": "string"},
    },
    "required": ["kind"],
}

CODER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["completed", "blocked"]},
        "spec_version_label": {"type": "string"},
        "summary": {"type": "string"},
        "file_writes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        },
        "reason": {"type": "string"},
        "attempted": {"type": "string"},
        "blocking_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status", "spec_version_label"],
}

REVIEWER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "spec_version_label": {"type": "string"},
        "decision": {"type": "string", "enum": ["APPROVE", "REJECT"]},
        "requirements_met": {"type": "boolean"},
        "security_ok": {"type": "boolean"},
        "validation_ok": {"type": "boolean"},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string"}, "file": {"type": "string"},
                    "description": {"type": "string"}, "required_fix": {"type": "string"},
                },
                "required": ["severity", "file", "description", "required_fix"],
            },
        },
    },
    "required": ["spec_version_label", "decision", "requirements_met", "security_ok", "validation_ok"],
}

# Phase 12: Planning Mode schemas - added when a real live end-to-end test
# discovered OllamaModelProvider never got these four methods when Phase 9
# added them to the ModelProvider protocol. Same flat-object-with-optional-
# fields pattern as the three schemas above; parse_planner_plan_output/
# parse_reviewer_plan_output/parse_chat_output/parse_review_session_output
# (plan_schemas.py) still independently enforce which fields are actually
# required for a given "kind" - this is the syntactic half only.

PLANNER_PLAN_MODE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["plan", "needs_user_input", "research_request"]},
        "objective": {"type": "string"},
        "requirements": {"type": "array", "items": {"type": "string"}},
        "existing_context": {"type": "array", "items": {"type": "string"}},
        "proposed_architecture": {"type": "string"},
        "files_to_create": {"type": "array", "items": {"type": "string"}},
        "files_to_modify": {"type": "array", "items": {"type": "string"}},
        "dependencies": {"type": "array", "items": {"type": "string"}},
        "implementation_steps": {"type": "array", "items": {"type": "string"}},
        "validation_strategy": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "unknowns": {"type": "array", "items": {"type": "string"}},
        "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
        "question": {"type": "string"},
        "requests": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"capability": {"type": "string"}, "query": {"type": "string"}},
                "required": ["capability", "query"],
            },
        },
    },
    "required": ["kind"],
}

REVIEWER_PLAN_CRITIQUE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "comments": {"type": "array", "items": {"type": "string"}},
        "missing_requirements": {"type": "array", "items": {"type": "string"}},
        "security_concerns": {"type": "array", "items": {"type": "string"}},
        "unnecessary_complexity": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["comments", "missing_requirements", "security_concerns", "unnecessary_complexity"],
}

CHAT_SCHEMA: dict = {
    "type": "object",
    "properties": {"message": {"type": "string"}},
    "required": ["message"],
}

REVIEW_SESSION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "findings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "findings"],
}
