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
