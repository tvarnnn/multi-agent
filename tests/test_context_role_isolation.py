import inspect

from agent_platform.events import EventLog
from agent_platform.context.role_context import build_coder_context, build_planner_context, build_reviewer_context
from agent_platform.orchestrator.model_schemas import CoderCompleted, CoderFileWrite
from agent_platform.security.enums import Role, SessionMode
from agent_platform.security.permission import PermissionEvaluator
from agent_platform.security.sandbox import FilesystemSandbox
from agent_platform.spec.versioning import SpecStore
from agent_platform.tools.gateway import ToolGateway
from agent_platform.tools.registry import build_default_registry


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


def test_coder_context_has_no_raw_user_conversation_parameter():
    params = set(inspect.signature(build_coder_context).parameters)
    forbidden = {"user_request", "conversation", "user_conversation", "request"}
    assert not (params & forbidden)


def test_planner_context_includes_the_user_request_as_a_hint(tmp_path):
    proj = _workspace(tmp_path)
    (proj / "app.py").write_text("x = 1", encoding="utf-8")
    bundle = build_planner_context(_gateway(proj), SessionMode.AUTO, proj.resolve(),
                                    "please update app.py to add logging")
    assert bundle.role == "PLANNER"
    assert any(f.path == "app.py" for f in bundle.files)


def test_coder_context_never_surfaces_a_distinctive_summary_string(tmp_path):
    # The Coder's context builder takes spec + reviewer_feedback only -
    # there's nothing summary-shaped to leak in the first place, but this
    # proves it end to end: a distinctive marker that would only appear
    # via mishandled prior-attempt state never shows up.
    proj = _workspace(tmp_path)
    (proj / "app.py").write_text("x = 1", encoding="utf-8")
    spec = SpecStore().create("task-1", goals=["fix app.py"], constraints=[], acceptance_criteria=[])
    bundle = build_coder_context(_gateway(proj), SessionMode.AUTO, proj.resolve(), spec)
    assert bundle.role == "CODER"
    assert not any("SECRET_USER_MARKER" in f.content for f in bundle.files)


def test_reviewer_context_ignores_coder_summary_text_for_hint_matching(tmp_path):
    proj = _workspace(tmp_path)
    (proj / "app.py").write_text("x = 1", encoding="utf-8")
    (proj / "unrelated_topic.py").write_text("nothing to do with this task", encoding="utf-8")
    spec = SpecStore().create("task-1", goals=["fix app.py"], constraints=[], acceptance_criteria=[])
    # The summary mentions unrelated_topic.py by name - if the reviewer
    # context builder read .summary for hints, that file would get pulled
    # in. It must not, because build_reviewer_context only reads
    # file_writes paths, never .summary.
    coder_output = CoderCompleted(
        spec_version_label=spec.version_label,
        summary="see unrelated_topic.py for background on why I did this",
        file_writes=(CoderFileWrite(path="app.py", content="x = 1"),),
    )
    bundle = build_reviewer_context(_gateway(proj), SessionMode.AUTO, proj.resolve(), spec, coder_output)
    assert bundle.role == "REVIEWER"
    paths = {f.path for f in bundle.files}
    assert "app.py" in paths
    assert "unrelated_topic.py" not in paths


def test_reviewer_context_includes_files_the_coder_actually_wrote(tmp_path):
    proj = _workspace(tmp_path)
    (proj / "app.py").write_text("x = 1", encoding="utf-8")
    spec = SpecStore().create("task-1", goals=["g"], constraints=[], acceptance_criteria=[])
    coder_output = CoderCompleted(spec_version_label=spec.version_label, summary="s",
                                   file_writes=(CoderFileWrite(path="app.py", content="x = 1"),))
    bundle = build_reviewer_context(_gateway(proj), SessionMode.AUTO, proj.resolve(), spec, coder_output)
    assert any(f.path == "app.py" for f in bundle.files)
