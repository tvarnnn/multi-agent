from agent_platform.persistence.checkpoint_schema import render_checkpoint_markdown
from agent_platform.persistence.records import CheckpointRecord


def _checkpoint(**overrides):
    defaults = dict(
        session_id="s1", seq=1, spec_id="spec-1", spec_version_label="spec-1-v1",
        plan_snapshot_id=None, operating_mode="CODE", objective="Add a health-check endpoint",
        completed_work=("Created health.py", "Wired route"),
        current_problem="Reviewer flagged missing test coverage",
        relevant_decisions=("Chose FastAPI over Flask",),
        reviewer_feedback=("Add a test for the 500 case",),
        validation_passed=False, validation_details=("2 passed, 1 failed",),
        changed_file_hashes={"health.py": "abc123"},
        next_action="Add the missing test and re-run validation",
        constraints=("Must not add new dependencies",),
        context_references=("health.py", "test_health.py"),
        reason="compaction_threshold", content_hash="deadbeef", markdown_path="checkpoint-001.md",
        token_estimate=1234, created_at=1700000000.0,
    )
    defaults.update(overrides)
    return CheckpointRecord(**defaults)


def test_render_is_deterministic_same_input_same_output():
    checkpoint = _checkpoint()
    assert render_checkpoint_markdown(checkpoint) == render_checkpoint_markdown(checkpoint)


def test_render_includes_identity_and_objective():
    text = render_checkpoint_markdown(_checkpoint())
    assert "spec-1-v1" in text
    assert "CODE" in text
    assert "Add a health-check endpoint" in text


def test_render_includes_completed_work_as_bullets():
    text = render_checkpoint_markdown(_checkpoint())
    assert "- Created health.py" in text
    assert "- Wired route" in text


def test_render_includes_current_problem_and_next_action():
    text = render_checkpoint_markdown(_checkpoint())
    assert "Reviewer flagged missing test coverage" in text
    assert "Add the missing test and re-run validation" in text


def test_render_includes_changed_files_but_never_hashes():
    text = render_checkpoint_markdown(_checkpoint())
    assert "health.py" in text
    assert "abc123" not in text  # hash is DB-integrity-only, never surfaced in the human-readable body


def test_render_empty_sections_use_placeholder_text():
    checkpoint = _checkpoint(completed_work=(), relevant_decisions=(), reviewer_feedback=(),
                              constraints=(), context_references=())
    text = render_checkpoint_markdown(checkpoint)
    assert "_None recorded._" in text


def test_render_validation_section_reflects_pass_and_fail():
    passing = render_checkpoint_markdown(_checkpoint(validation_passed=True, validation_details=("3 passed",)))
    failing = render_checkpoint_markdown(_checkpoint(validation_passed=False, validation_details=("1 failed",)))
    assert "PASSED" in passing
    assert "FAILED" in failing


def test_render_validation_section_handles_none():
    text = render_checkpoint_markdown(_checkpoint(validation_passed=None, validation_details=()))
    assert "not yet run" in text.lower() or "_None recorded._" in text
