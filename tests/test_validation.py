from agent_platform.orchestrator.validation import AcceptanceCriteriaFileValidator
from agent_platform.spec.versioning import SpecStore


def _spec(**kwargs):
    store = SpecStore()
    defaults = {"goals": ["g"], "constraints": [], "acceptance_criteria": []}
    defaults.update(kwargs)
    return store.create("task-1", **defaults)


def test_passes_when_all_file_criteria_exist(tmp_path):
    (tmp_path / "app.py").write_text("x", encoding="utf-8")
    spec = _spec(acceptance_criteria=["file:app.py"])
    result = AcceptanceCriteriaFileValidator().validate(tmp_path, spec)
    assert result.passed


def test_fails_when_a_file_criterion_is_missing(tmp_path):
    spec = _spec(acceptance_criteria=["file:missing.py"])
    result = AcceptanceCriteriaFileValidator().validate(tmp_path, spec)
    assert not result.passed
    assert any("MISSING" in d for d in result.details)


def test_non_file_criteria_are_advisory_and_never_fail_validation(tmp_path):
    spec = _spec(acceptance_criteria=["the app should feel fast"])
    result = AcceptanceCriteriaFileValidator().validate(tmp_path, spec)
    assert result.passed
    assert any("ADVISORY" in d for d in result.details)


def test_no_criteria_passes_trivially(tmp_path):
    spec = _spec(acceptance_criteria=[])
    result = AcceptanceCriteriaFileValidator().validate(tmp_path, spec)
    assert result.passed
    assert result.details == ()


def test_mixed_criteria_fail_overall_if_any_file_criterion_is_missing(tmp_path):
    (tmp_path / "present.py").write_text("x", encoding="utf-8")
    spec = _spec(acceptance_criteria=["file:present.py", "file:absent.py", "should be fast"])
    result = AcceptanceCriteriaFileValidator().validate(tmp_path, spec)
    assert not result.passed
    assert len(result.details) == 3
