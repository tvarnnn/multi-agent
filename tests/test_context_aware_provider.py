from agent_platform.events import EventLog
from agent_platform.context.bundle import ContextBundle
from agent_platform.orchestrator.context_aware_provider import ContextAwareModelProvider
from agent_platform.orchestrator.model_schemas import CoderCompleted, CoderFileWrite
from agent_platform.security.enums import SessionMode
from agent_platform.security.permission import PermissionEvaluator
from agent_platform.security.sandbox import FilesystemSandbox
from agent_platform.spec.versioning import SpecStore
from agent_platform.tools.gateway import ToolGateway
from agent_platform.tools.registry import build_default_registry


class _RecordingInnerProvider:
    def __init__(self, plan_response=None, code_response=None, review_response=None):
        self.received: list = []
        self._plan_response = plan_response
        self._code_response = code_response
        self._review_response = review_response

    def plan(self, context):
        self.received.append(("plan", context))
        return self._plan_response

    def code(self, context):
        self.received.append(("code", context))
        return self._code_response

    def review(self, context):
        self.received.append(("review", context))
        return self._review_response


def _workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    proj = root / "MyProj"
    proj.mkdir()
    return proj


def _gateway(proj):
    sandbox = FilesystemSandbox(proj.parent)
    evaluator = PermissionEvaluator(sandbox)
    return ToolGateway(build_default_registry(), evaluator, EventLog())


def test_plan_enriches_context_with_a_planner_bundle(tmp_path):
    proj = _workspace(tmp_path)
    (proj / "app.py").write_text("x = 1", encoding="utf-8")
    inner = _RecordingInnerProvider(plan_response={"kind": "spec", "goals": [], "constraints": [],
                                                    "acceptance_criteria": []})
    provider = ContextAwareModelProvider(inner, gateway=_gateway(proj), session_mode=SessionMode.AUTO,
                                          project_root=proj.resolve())
    provider.plan({"request": "fix app.py"})
    _, received_context = inner.received[0]
    bundle = received_context["context_bundle"]
    assert isinstance(bundle, ContextBundle)
    assert bundle.role == "PLANNER"
    assert any(f.path == "app.py" for f in bundle.files)


def test_code_enriches_context_with_a_coder_bundle(tmp_path):
    proj = _workspace(tmp_path)
    (proj / "app.py").write_text("x = 1", encoding="utf-8")
    spec = SpecStore().create("task-1", goals=["fix app.py"], constraints=[], acceptance_criteria=[])
    inner = _RecordingInnerProvider(code_response={"status": "completed", "spec_version_label": spec.version_label,
                                                    "summary": "s", "file_writes": []})
    provider = ContextAwareModelProvider(inner, gateway=_gateway(proj), session_mode=SessionMode.AUTO,
                                          project_root=proj.resolve())
    provider.code({"spec": spec, "reviewer_feedback": None})
    _, received_context = inner.received[0]
    bundle = received_context["context_bundle"]
    assert bundle.role == "CODER"
    assert any(f.path == "app.py" for f in bundle.files)


def test_review_enriches_context_with_a_reviewer_bundle(tmp_path):
    proj = _workspace(tmp_path)
    (proj / "app.py").write_text("x = 1", encoding="utf-8")
    spec = SpecStore().create("task-1", goals=["g"], constraints=[], acceptance_criteria=[])
    coder_output = CoderCompleted(spec_version_label=spec.version_label, summary="s",
                                   file_writes=(CoderFileWrite(path="app.py", content="x = 1"),))
    inner = _RecordingInnerProvider(review_response={"spec_version_label": spec.version_label,
                                                       "decision": "APPROVE", "requirements_met": True,
                                                       "security_ok": True, "validation_ok": True, "issues": []})
    provider = ContextAwareModelProvider(inner, gateway=_gateway(proj), session_mode=SessionMode.AUTO,
                                          project_root=proj.resolve())
    provider.review({"spec": spec, "coder_output": coder_output, "validation_result": None})
    _, received_context = inner.received[0]
    bundle = received_context["context_bundle"]
    assert bundle.role == "REVIEWER"
    assert any(f.path == "app.py" for f in bundle.files)


def test_plan_uses_blocking_questions_as_hints_during_clarification(tmp_path):
    proj = _workspace(tmp_path)
    (proj / "auth.py").write_text("x = 1", encoding="utf-8")
    inner = _RecordingInnerProvider(plan_response={"kind": "spec", "goals": [], "constraints": [],
                                                    "acceptance_criteria": []})
    provider = ContextAwareModelProvider(inner, gateway=_gateway(proj), session_mode=SessionMode.AUTO,
                                          project_root=proj.resolve())
    provider.plan({"spec": SpecStore().create("t", goals=["g"], constraints=[], acceptance_criteria=[]),
                    "blocking_questions": ["should auth.py use OAuth?"]})
    _, received_context = inner.received[0]
    bundle = received_context["context_bundle"]
    assert any(f.path == "auth.py" for f in bundle.files)


def test_original_context_keys_are_preserved_alongside_the_bundle(tmp_path):
    proj = _workspace(tmp_path)
    spec = SpecStore().create("task-1", goals=["g"], constraints=[], acceptance_criteria=[])
    from agent_platform.orchestrator.model_schemas import ReviewerOutput
    feedback = ReviewerOutput(spec_version_label=spec.version_label, decision="REJECT",
                               requirements_met=False, security_ok=True, validation_ok=True, issues=())
    inner = _RecordingInnerProvider(code_response={"status": "completed", "spec_version_label": spec.version_label,
                                                    "summary": "s", "file_writes": []})
    provider = ContextAwareModelProvider(inner, gateway=_gateway(proj), session_mode=SessionMode.AUTO,
                                          project_root=proj.resolve())
    provider.code({"spec": spec, "reviewer_feedback": feedback})
    _, received_context = inner.received[0]
    assert received_context["spec"] is spec
    assert received_context["reviewer_feedback"] is feedback
