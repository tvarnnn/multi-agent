from agent_platform.orchestrator.model_schemas import CoderCompleted, CoderFileWrite, ReviewerOutput, ReviewerIssue
from agent_platform.orchestrator.prompts import build_coder_prompt, build_planner_prompt, build_reviewer_prompt
from agent_platform.orchestrator.validation import ValidationResult
from agent_platform.spec.versioning import SpecStore


def _spec(**kwargs):
    store = SpecStore()
    defaults = {"goals": ["build app"], "constraints": ["no network"], "acceptance_criteria": ["file:app.py"]}
    defaults.update(kwargs)
    return store.create("task-1", **defaults)


def test_planner_prompt_includes_the_user_request():
    prompt = build_planner_prompt({"request": "build me a FastAPI app"})
    assert "build me a FastAPI app" in prompt


def test_planner_clarification_prompt_includes_blocking_questions_and_spec():
    spec = _spec()
    prompt = build_planner_prompt({"spec": spec, "blocking_questions": ["OAuth or API keys?"]})
    assert "OAuth or API keys?" in prompt
    assert "build app" in prompt


def test_coder_prompt_includes_spec_and_exact_version_label():
    spec = _spec()
    prompt = build_coder_prompt({"spec": spec, "reviewer_feedback": None})
    assert spec.version_label in prompt
    assert "file:app.py" in prompt


def test_coder_prompt_includes_reviewer_feedback_when_present():
    spec = _spec()
    feedback = ReviewerOutput(spec_version_label=spec.version_label, decision="REJECT",
                               requirements_met=False, security_ok=True, validation_ok=True,
                               issues=(ReviewerIssue(severity="high", file="app.py",
                                                      description="missing auth",
                                                      required_fix="add auth check"),))
    prompt = build_coder_prompt({"spec": spec, "reviewer_feedback": feedback})
    assert "missing auth" in prompt
    assert "add auth check" in prompt


def test_coder_prompt_never_includes_raw_user_conversation_text():
    # Phase 1's orchestrator never puts "request" in the coder context to
    # begin with - this proves the prompt builder doesn't reach for it
    # even if it were accidentally present.
    spec = _spec()
    prompt = build_coder_prompt({"spec": spec, "reviewer_feedback": None, "request": "SECRET USER TEXT"})
    assert "SECRET USER TEXT" not in prompt


def test_reviewer_prompt_includes_files_and_validation_but_not_coder_summary():
    spec = _spec()
    coder_output = CoderCompleted(spec_version_label=spec.version_label,
                                   summary="I cleverly used a singleton pattern here",
                                   file_writes=(CoderFileWrite(path="app.py", content="print('hi')"),))
    validation_result = ValidationResult(passed=True, details=("OK: file:app.py",))
    prompt = build_reviewer_prompt({"spec": spec, "coder_output": coder_output,
                                     "validation_result": validation_result})
    assert "print('hi')" in prompt
    assert "OK: file:app.py" in prompt
    assert "singleton" not in prompt


def test_reviewer_prompt_includes_exact_spec_version_label():
    spec = _spec()
    coder_output = CoderCompleted(spec_version_label=spec.version_label, summary="s", file_writes=())
    validation_result = ValidationResult(passed=True, details=())
    prompt = build_reviewer_prompt({"spec": spec, "coder_output": coder_output,
                                     "validation_result": validation_result})
    assert spec.version_label in prompt
