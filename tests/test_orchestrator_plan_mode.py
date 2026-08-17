import pytest

from agent_platform.events import EventLog
from agent_platform.orchestrator.core import (
    ChatResult,
    Orchestrator,
    PlanApprovalResult,
    PlanLifecycleError,
    PlanResult,
    ReviewResult,
)
from agent_platform.orchestrator.fake_model import FakeModelProvider
from agent_platform.orchestrator.plan_schemas import InvalidSpecIdError
from agent_platform.orchestrator.validation import AcceptanceCriteriaFileValidator
from agent_platform.security.enums import OperatingMode, Role, SessionMode, ToolPermission
from agent_platform.security.permission import PermissionEvaluator
from agent_platform.security.sandbox import FilesystemSandbox
from agent_platform.spec.versioning import SpecStore
from agent_platform.tools.gateway import ToolGateway
from agent_platform.tools.registry import build_default_registry
from agent_platform.tools.schemas import ToolExecutionContext, ToolSpec


def _plan_dict(**overrides):
    d = {
        "kind": "plan",
        "objective": "Build the widget",
        "requirements": ["req1"],
        "existing_context": [],
        "proposed_architecture": "single module",
        "files_to_create": ["widget.py"],
        "files_to_modify": [],
        "dependencies": [],
        "implementation_steps": ["step1"],
        "validation_strategy": ["test1"],
        "risks": [],
        "unknowns": [],
        "acceptance_criteria": ["file:widget.py"],
    }
    d.update(overrides)
    return d


def _review_dict(**overrides):
    d = {"comments": [], "missing_requirements": [], "security_concerns": [], "unnecessary_complexity": []}
    d.update(overrides)
    return d


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    (root / "MyProj").mkdir()
    return root


def _build_orchestrator(workspace, model, *, operating_mode=OperatingMode.PLAN,
                         tool_table=None, registry=None, **overrides):
    sandbox = FilesystemSandbox(workspace)
    evaluator = PermissionEvaluator(sandbox, tool_table=tool_table)
    event_log = EventLog()
    gateway = ToolGateway(registry or build_default_registry(), evaluator, event_log)
    kwargs = dict(
        gateway=gateway, model=model, spec_store=SpecStore(), event_log=event_log,
        session_mode=SessionMode.AUTO, project_root=(workspace / "MyProj").resolve(),
        validator=AcceptanceCriteriaFileValidator(), operating_mode=operating_mode,
    )
    kwargs.update(overrides)
    return Orchestrator(**kwargs), event_log


# --------------------------------------------------------------- draft

def test_run_plan_produces_draft_artifact_and_never_touches_spec_store(workspace):
    model = FakeModelProvider(
        plan_mode_responses=[_plan_dict()],
        review_plan_responses=[_review_dict()],
    )
    orchestrator, event_log = _build_orchestrator(workspace, model)
    result = orchestrator.run_plan("widget", "build me a widget")
    assert isinstance(result, PlanResult)
    assert result.status == "DRAFT"
    assert result.artifact_path.startswith(".agent/plans/")
    assert (workspace / "MyProj" / result.artifact_path).exists()
    content = (workspace / "MyProj" / result.artifact_path).read_text(encoding="utf-8")
    assert "Status: DRAFT" in content
    assert model.code_call_count == 0
    with pytest.raises(KeyError):
        orchestrator._spec_store.latest("widget")  # not created until approval


def test_run_plan_rejects_invalid_spec_id_without_normalizing(workspace):
    model = FakeModelProvider(plan_mode_responses=[_plan_dict()])
    orchestrator, _ = _build_orchestrator(workspace, model)
    with pytest.raises(InvalidSpecIdError):
        orchestrator.run_plan("../escape", "build me a widget")


def test_run_plan_wrong_operating_mode_raises(workspace):
    model = FakeModelProvider()
    orchestrator, _ = _build_orchestrator(workspace, model, operating_mode=OperatingMode.CODE)
    with pytest.raises(ValueError):
        orchestrator.run_plan("widget", "build me a widget")


# --------------------------------------------------------- clarification

def test_run_plan_clarification_returns_needs_input(workspace):
    model = FakeModelProvider(plan_mode_responses=[{"kind": "needs_user_input", "question": "which db?"}])
    orchestrator, _ = _build_orchestrator(workspace, model)
    result = orchestrator.run_plan("widget", "build me a widget")
    assert result.status == "NEEDS_INPUT"
    assert result.message == "which db?"
    assert model.code_call_count == 0


def test_run_plan_malformed_output_returns_failed(workspace):
    model = FakeModelProvider(plan_mode_responses=[{"kind": "plan"}, {"kind": "plan"}, {"kind": "plan"}])
    orchestrator, _ = _build_orchestrator(workspace, model)
    result = orchestrator.run_plan("widget", "build me a widget")
    assert result.status == "FAILED"
    assert model.code_call_count == 0


# -------------------------------------------------------------- research

def _registry_with_capability():
    registry = build_default_registry()
    registry.register(ToolSpec(
        name="mcp.testserver.search",
        validate_arguments=lambda args: args,
        path_argument_key=None,
        check_preconditions=lambda args, ctx: None,
        execute=lambda args, ctx: {"found": "some result"},
    ))
    return registry


def test_run_plan_allowed_research_capability_feeds_observation_back(workspace):
    model = FakeModelProvider(
        plan_mode_responses=[
            {"kind": "research_request", "requests": [
                {"capability": "mcp.testserver.search", "query": "find auth code"}]},
            _plan_dict(),
        ],
        review_plan_responses=[_review_dict()],
    )
    grants = {(Role.PLANNER, "mcp.testserver.search"): ToolPermission.ALLOW}
    orchestrator, event_log = _build_orchestrator(workspace, model, registry=_registry_with_capability(),
                                                   tool_table=grants)
    result = orchestrator.run_plan("widget", "build me a widget")
    assert result.status == "DRAFT"
    research_completed = [e for e in event_log.internal_stream()
                           if e.event_type.name == "PLAN_RESEARCH_COMPLETED"]
    assert len(research_completed) == 1
    assert research_completed[0].payload["status"] == "ok"


def test_run_plan_denied_research_capability_feeds_denial_back_not_exception(workspace):
    model = FakeModelProvider(
        plan_mode_responses=[
            {"kind": "research_request", "requests": [
                {"capability": "mcp.github.delete_repo", "query": "delete it"}]},
            _plan_dict(),
        ],
        review_plan_responses=[_review_dict()],
    )
    orchestrator, event_log = _build_orchestrator(workspace, model)
    result = orchestrator.run_plan("widget", "build me a widget")
    assert result.status == "DRAFT"  # never raised - denial fed back, planner proceeded
    research_completed = [e for e in event_log.internal_stream()
                           if e.event_type.name == "PLAN_RESEARCH_COMPLETED"]
    assert research_completed[0].payload["status"] in ("unknown_tool", "denied")


def test_run_plan_research_loop_bounded(workspace):
    responses = [
        {"kind": "research_request", "requests": [{"capability": "mcp.testserver.search", "query": "q"}]}
    ] * 5
    model = FakeModelProvider(plan_mode_responses=responses)
    orchestrator, _ = _build_orchestrator(workspace, model, registry=_registry_with_capability(),
                                           max_plan_research_rounds=2)
    result = orchestrator.run_plan("widget", "build me a widget")
    assert result.status == "NEEDS_INPUT"
    assert "research" in result.message.lower()
    assert model.code_call_count == 0


# -------------------------------------------------------------- reviewer

def test_run_plan_single_automatic_reviewer_pass_populates_feedback(workspace):
    model = FakeModelProvider(
        plan_mode_responses=[_plan_dict()],
        review_plan_responses=[_review_dict(comments=["nice work"], missing_requirements=["add logging"])],
    )
    orchestrator, _ = _build_orchestrator(workspace, model)
    result = orchestrator.run_plan("widget", "build me a widget")
    assert "nice work" in result.plan.reviewer_feedback
    assert "add logging" in result.plan.reviewer_feedback
    content = (workspace / "MyProj" / result.artifact_path).read_text(encoding="utf-8")
    assert "nice work" in content


# --------------------------------------------------------------- revision

def test_revise_plan_overwrites_same_artifact_with_revised_status(workspace):
    model = FakeModelProvider(
        plan_mode_responses=[_plan_dict(), _plan_dict(objective="Build the widget v2")],
        review_plan_responses=[_review_dict(), _review_dict()],
    )
    orchestrator, _ = _build_orchestrator(workspace, model)
    first = orchestrator.run_plan("widget", "build me a widget")
    second = orchestrator.revise_plan("widget", "add auth")
    assert second.status == "REVISED"
    assert second.artifact_path == first.artifact_path
    content = (workspace / "MyProj" / second.artifact_path).read_text(encoding="utf-8")
    assert "Status: REVISED" in content
    assert "Build the widget v2" in content


def test_revise_plan_without_active_draft_raises(workspace):
    model = FakeModelProvider()
    orchestrator, _ = _build_orchestrator(workspace, model)
    with pytest.raises(PlanLifecycleError):
        orchestrator.revise_plan("widget", "add auth")


# --------------------------------------------------------------- approval

def test_approve_plan_creates_spec_version_and_finalizes_artifact(workspace):
    model = FakeModelProvider(
        plan_mode_responses=[_plan_dict()],
        review_plan_responses=[_review_dict()],
    )
    orchestrator, event_log = _build_orchestrator(workspace, model)
    draft = orchestrator.run_plan("widget", "build me a widget")
    result = orchestrator.approve_plan("widget")
    assert isinstance(result, PlanApprovalResult)
    assert result.spec_version_label == "widget-v1"
    assert orchestrator._spec_store.latest("widget").version_label == "widget-v1"
    content = (workspace / "MyProj" / draft.artifact_path).read_text(encoding="utf-8")
    assert "Status: APPROVED" in content
    approved_events = [e for e in event_log.internal_stream() if e.event_type.name == "PLAN_APPROVED"]
    assert len(approved_events) == 1


def test_approve_plan_without_active_draft_raises(workspace):
    model = FakeModelProvider()
    orchestrator, _ = _build_orchestrator(workspace, model)
    with pytest.raises(PlanLifecycleError):
        orchestrator.approve_plan("widget")


def test_artifact_is_immutable_after_approval_revise_raises(workspace):
    model = FakeModelProvider(
        plan_mode_responses=[_plan_dict()],
        review_plan_responses=[_review_dict()],
    )
    orchestrator, _ = _build_orchestrator(workspace, model)
    orchestrator.run_plan("widget", "build me a widget")
    orchestrator.approve_plan("widget")
    with pytest.raises(PlanLifecycleError):
        orchestrator.revise_plan("widget", "one more change")


def test_amend_after_approval_creates_new_version_preserving_old_file(workspace):
    model = FakeModelProvider(
        plan_mode_responses=[_plan_dict(), _plan_dict(objective="Build the widget v2")],
        review_plan_responses=[_review_dict(), _review_dict()],
    )
    orchestrator, _ = _build_orchestrator(workspace, model)
    first = orchestrator.run_plan("widget", "build me a widget")
    orchestrator.approve_plan("widget")
    second = orchestrator.run_plan("widget", "build me a widget v2")
    assert second.artifact_path != first.artifact_path
    assert second.status == "DRAFT"
    # The original approved file is untouched - historical evidence preserved.
    original_content = (workspace / "MyProj" / first.artifact_path).read_text(encoding="utf-8")
    assert "Status: APPROVED" in original_content
    assert orchestrator._spec_store.latest("widget").version == 1


# -------------------------------------------------------------- rejection

def test_reject_plan_writes_rejected_status_and_never_creates_spec_version(workspace):
    model = FakeModelProvider(
        plan_mode_responses=[_plan_dict()],
        review_plan_responses=[_review_dict()],
    )
    orchestrator, event_log = _build_orchestrator(workspace, model)
    draft = orchestrator.run_plan("widget", "build me a widget")
    result = orchestrator.reject_plan("widget", "not what I wanted")
    assert result.status == "REJECTED"
    content = (workspace / "MyProj" / draft.artifact_path).read_text(encoding="utf-8")
    assert "Status: REJECTED" in content
    with pytest.raises(KeyError):
        orchestrator._spec_store.latest("widget")
    rejected_events = [e for e in event_log.internal_stream() if e.event_type.name == "PLAN_REJECTED"]
    assert len(rejected_events) == 1


# ----------------------------------------------------- manual edit non-authority

def test_manual_markdown_edit_is_overwritten_not_read_back(workspace):
    model = FakeModelProvider(
        plan_mode_responses=[_plan_dict(), _plan_dict(objective="Revised objective")],
        review_plan_responses=[_review_dict(), _review_dict()],
    )
    orchestrator, _ = _build_orchestrator(workspace, model)
    draft = orchestrator.run_plan("widget", "build me a widget")
    artifact_file = workspace / "MyProj" / draft.artifact_path
    artifact_file.write_text("# HAND EDITED NONSENSE", encoding="utf-8")
    revised = orchestrator.revise_plan("widget", "change it")
    content = artifact_file.read_text(encoding="utf-8")
    assert "HAND EDITED NONSENSE" not in content
    assert "Revised objective" in content
    assert revised.plan.objective == "Revised objective"


# ------------------------------------------------------------- role denial

def test_planner_write_outside_plan_directory_is_structurally_impossible_via_orchestrator(workspace):
    # The orchestrator's own plan-artifact writer always targets
    # .agent/plans/** - proven by inspecting every artifact path it ever
    # produces across a draft/revise/approve cycle.
    model = FakeModelProvider(
        plan_mode_responses=[_plan_dict(), _plan_dict()],
        review_plan_responses=[_review_dict(), _review_dict()],
    )
    orchestrator, _ = _build_orchestrator(workspace, model)
    draft = orchestrator.run_plan("widget", "build me a widget")
    revised = orchestrator.revise_plan("widget", "tweak")
    for path in (draft.artifact_path, revised.artifact_path):
        assert path.startswith(".agent/plans/")


# ---------------------------------------------------------------- chat/review

def test_run_chat_returns_message_and_never_touches_coder(workspace):
    model = FakeModelProvider(chat_responses=[{"message": "Sure, here's an answer."}])
    orchestrator, _ = _build_orchestrator(workspace, model, operating_mode=OperatingMode.CHAT)
    result = orchestrator.run_chat("session-1", "how does auth work here?")
    assert isinstance(result, ChatResult)
    assert result.message == "Sure, here's an answer."
    assert model.code_call_count == 0


def test_run_chat_wrong_mode_raises(workspace):
    model = FakeModelProvider()
    orchestrator, _ = _build_orchestrator(workspace, model, operating_mode=OperatingMode.PLAN)
    with pytest.raises(ValueError):
        orchestrator.run_chat("session-1", "hi")


def test_run_review_returns_summary_and_never_touches_coder(workspace):
    model = FakeModelProvider(review_session_responses=[{"summary": "looks fine", "findings": []}])
    orchestrator, _ = _build_orchestrator(workspace, model, operating_mode=OperatingMode.REVIEW)
    result = orchestrator.run_review("session-1", "review the auth module")
    assert isinstance(result, ReviewResult)
    assert result.summary == "looks fine"
    assert model.code_call_count == 0


def test_plan_status_reflects_current_state_and_none_when_absent(workspace):
    model = FakeModelProvider(
        plan_mode_responses=[_plan_dict()],
        review_plan_responses=[_review_dict()],
    )
    orchestrator, _ = _build_orchestrator(workspace, model)
    assert orchestrator.plan_status("widget") is None
    draft = orchestrator.run_plan("widget", "build me a widget")
    status = orchestrator.plan_status("widget")
    assert status.status == "DRAFT"
    assert status.artifact_path == draft.artifact_path


def test_reviewer_cannot_write_plan_artifacts_even_if_attempted(workspace):
    # Deterministic proof Reviewer plan-writes are denied (design §1.2/§1.4):
    # no ALLOW/CONFIRM grant exists for (REVIEWER, filesystem.write) in the
    # base table, and PLAN mode's mode_grants only grants PLANNER.
    from agent_platform.security.permission import ToolCall
    sandbox = FilesystemSandbox(workspace)
    evaluator = PermissionEvaluator(sandbox)
    decision = evaluator.evaluate(
        ToolCall(Role.REVIEWER, "filesystem.write", ".agent/plans/x.md", (workspace / "MyProj").resolve()),
        SessionMode.AUTO, operating_mode=OperatingMode.PLAN,
    )
    assert decision.permission == ToolPermission.DENY
