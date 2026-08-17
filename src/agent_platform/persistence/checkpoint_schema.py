"""Deterministic, pure rendering of a CheckpointRecord to Markdown - one
field, one section, no model-authored formatting, mirroring
orchestrator/plan_markdown.py's pattern exactly. This Markdown is a
human-readable mirror only: checkpoint_store.py verifies its hash on
load but never re-parses its content as structured data - the DB row's
typed columns are the only thing reconstruction.py ever reads back. File
hashes are deliberately never rendered into the body (integrity-only,
DB-internal), only the file paths.
"""
from __future__ import annotations

from .records import CheckpointRecord


def _bullet_section(title: str, items: tuple) -> str:
    if not items:
        return f"## {title}\n\n_None recorded._\n"
    body = "\n".join(f"- {item}" for item in items)
    return f"## {title}\n\n{body}\n"


def _text_section(title: str, text: str) -> str:
    return f"## {title}\n\n{text}\n"


def _validation_section(validation_passed, validation_details: tuple) -> str:
    if validation_passed is None and not validation_details:
        return "## Validation\n\n_Not yet run._\n"
    status = "PASSED" if validation_passed else "FAILED"
    body = "\n".join(f"- {d}" for d in validation_details) or "_No details recorded._"
    return f"## Validation\n\nStatus: {status}\n\n{body}\n"


def render_checkpoint_markdown(checkpoint: CheckpointRecord) -> str:
    sections = [
        f"# Session Checkpoint\n\nSession: {checkpoint.session_id}\n"
        f"Operating Mode: {checkpoint.operating_mode}\n"
        f"Specification Version: {checkpoint.spec_version_label or '(none)'}\n"
        f"Reason: {checkpoint.reason}\n",
        _text_section("Objective", checkpoint.objective),
        _bullet_section("Completed Work", checkpoint.completed_work),
        _text_section("Current Problem", checkpoint.current_problem or "_None recorded._"),
        _bullet_section("Relevant Decisions", checkpoint.relevant_decisions),
        _bullet_section("Reviewer Feedback", checkpoint.reviewer_feedback),
        _validation_section(checkpoint.validation_passed, checkpoint.validation_details),
        _bullet_section("Changed Files", checkpoint.changed_files),
        _text_section("Next Action", checkpoint.next_action or "_None recorded._"),
        _bullet_section("Constraints", checkpoint.constraints),
        _bullet_section("Context References", checkpoint.context_references),
    ]
    return "\n".join(sections)
