"""The deterministic orchestrator. Models propose (via ModelProvider),
the orchestrator decides (every transition below is driven by a
schema-validated structured output or a deterministic gate, never by
parsing free-form prose). No model gets a direct execution path - file
writes go through the ToolGateway, which re-enforces Phase 0's sandbox
and permission system on every call.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

from ..context.bundle_builder import build_context_bundle
from ..context.role_context import build_planner_context
from ..events import EventLog, EventType
from ..security.enums import OperatingMode, Role, SessionMode
from ..spec.versioning import SpecStore, SpecVersion, SpecVersionMismatchError
from ..tools.gateway import ToolGateway
from .fake_model import ModelTimeoutError
from .model_schemas import (
    CoderBlocked,
    CoderCompleted,
    PlannerClarification,
    PlannerSpec,
    SchemaValidationError,
    parse_coder_output,
    parse_planner_output,
    parse_reviewer_output,
)
from .plan_artifacts import plan_artifact_path, predicted_next_version, slugify, write_plan_artifact
from .plan_schemas import (
    ResearchRequestBatch,
    StructuredPlan,
    parse_chat_output,
    parse_planner_plan_output,
    parse_review_session_output,
    parse_reviewer_plan_output,
    validate_spec_id,
)
from .stall_detection import is_negligible_diff, is_repeated_identical_test_failure, is_repeated_review_rejection
from .states import State
from .validation import Validator


@dataclass(frozen=True)
class OrchestratorResult:
    final_state: State
    spec_id: str
    summary: str


class PlanLifecycleError(Exception):
    """Raised for invalid Plan Mode lifecycle transitions - e.g.
    revising/approving/rejecting when no mutable (DRAFT/REVISED) draft is
    active for the given spec_id, or an approval whose predicted spec
    version no longer matches reality (concurrent-approval edge case,
    design §7). Distinct from PlanResult(status="FAILED"), which is
    reserved for model-output failures the bounded retry loop already
    exhausted."""


@dataclass(frozen=True)
class PlanResult:
    status: str  # DRAFT | REVISED | REJECTED | NEEDS_INPUT | FAILED
    spec_id: str
    message: str
    artifact_path: Optional[str] = None
    plan: Optional[StructuredPlan] = None


@dataclass(frozen=True)
class PlanApprovalResult:
    spec_id: str
    spec_version_label: str
    artifact_path: str


@dataclass(frozen=True)
class ChatResult:
    session_id: str
    message: str


@dataclass(frozen=True)
class ReviewResult:
    session_id: str
    summary: str
    findings: tuple = ()


@dataclass(frozen=True)
class _PlanSessionState:
    version: int
    path: str
    status: str
    plan: StructuredPlan
    spec_version_label: str
    finalized_paths: tuple = ()


class Orchestrator:
    def __init__(self, *, gateway: ToolGateway, model, spec_store: SpecStore,
                 event_log: EventLog, session_mode: SessionMode, project_root: Path,
                 validator: Validator, operating_mode: OperatingMode = OperatingMode.CODE,
                 max_output_retries: int = 3,
                 max_clarification_rounds: int = 3, max_fix_iterations: int = 3,
                 max_plan_research_rounds: int = 3):
        self._gateway = gateway
        self._model = model
        self._spec_store = spec_store
        self._event_log = event_log
        self._session_mode = session_mode
        self._project_root = project_root
        self._validator = validator
        self._operating_mode = operating_mode
        self._max_output_retries = max_output_retries
        self._max_clarification_rounds = max_clarification_rounds
        self._max_fix_iterations = max_fix_iterations
        self._max_plan_research_rounds = max_plan_research_rounds
        self._state = State.RECEIVE_REQUEST
        self._review_issue_history: list = []
        self._validation_detail_history: list = []
        self._last_file_writes = None
        self._plan_sessions: dict = {}

    @property
    def state(self) -> State:
        return self._state

    def run(self, spec_id: str, user_request: str) -> OrchestratorResult:
        self._review_issue_history = []
        self._validation_detail_history = []
        self._last_file_writes = None
        self._event_log.emit(EventType.USER_REQUEST_RECEIVED, "user", {"spec_id": spec_id, "request": user_request})
        self._user_event(user_request)
        self._transition(State.PLAN)
        plan_output = self._invoke_with_retry(
            "planner", lambda: self._model.plan({"request": user_request}), parse_planner_output)
        return self._after_plan(spec_id, plan_output)

    def amend_requirements(self, spec_id: str, amendment_request: str) -> OrchestratorResult:
        """A user-initiated requirement change. Phase 1 exposes this as an
        explicit entry point rather than a live mid-session interrupt -
        the deterministic control plane is what's in scope here, not an
        interactive session loop. A later phase's real session would call
        this the moment an incoming user message is recognized as an
        amendment rather than a status query or an answer to a pending
        question; the state transitions and spec-versioning behavior are
        identical either way."""
        self._review_issue_history = []
        self._validation_detail_history = []
        self._last_file_writes = None
        self._user_event(amendment_request)
        self._transition(State.AMEND_REQUIREMENTS)
        plan_output = self._invoke_with_retry(
            "planner", lambda: self._model.plan({"request": amendment_request, "amendment": True}),
            parse_planner_output)
        return self._after_plan(spec_id, plan_output)

    # ------------------------------------------------------- Planning Mode
    #
    # These lightweight methods never touch the State enum above - Plan
    # Mode's progress is tracked via PLAN_* events and each method's
    # return value, not via the Code/Edit state machine (design §1.5).
    # Coder is structurally absent here: no method below calls
    # self._model.code(...) anywhere.

    def run_plan(self, spec_id: str, user_request: str) -> PlanResult:
        self._require_operating_mode(OperatingMode.PLAN, "run_plan")
        validate_spec_id(spec_id)
        self._event_log.emit(EventType.USER_REQUEST_RECEIVED, "user",
                              {"spec_id": spec_id, "request": user_request})
        self._user_event(user_request)
        return self._run_planner_plan_cycle(spec_id, user_request)

    def revise_plan(self, spec_id: str, revision_request: str) -> PlanResult:
        self._require_operating_mode(OperatingMode.PLAN, "revise_plan")
        validate_spec_id(spec_id)
        existing = self._require_mutable_draft(spec_id, "revise")
        self._user_event(revision_request)
        return self._run_planner_plan_cycle(spec_id, revision_request, is_revision=True)

    def approve_plan(self, spec_id: str) -> PlanApprovalResult:
        self._require_operating_mode(OperatingMode.PLAN, "approve_plan")
        validate_spec_id(spec_id)
        existing = self._require_mutable_draft(spec_id, "approve")
        spec = self._spec_store.create(
            spec_id, goals=existing.plan.requirements,
            constraints=existing.plan.risks + existing.plan.unknowns,
            acceptance_criteria=existing.plan.acceptance_criteria)
        self._event_log.emit(EventType.SPEC_VERSION_CREATED, "internal", {"version_label": spec.version_label})
        if spec.version_label != existing.spec_version_label:
            raise PlanLifecycleError(
                f"predicted spec version {existing.spec_version_label!r} does not match actual "
                f"{spec.version_label!r} for spec_id {spec_id!r} - concurrent approval detected")

        final_plan = replace(existing.plan, target_spec_version_label=spec.version_label)
        obs = write_plan_artifact(self._gateway, session_mode=self._session_mode, project_root=self._project_root,
                                   path=existing.path, plan=final_plan, status="APPROVED",
                                   spec_version_label=spec.version_label)
        if obs.status != "ok":
            raise PlanLifecycleError(f"failed to write approved plan artifact: {obs.error}")

        self._plan_sessions[spec_id] = replace(
            existing, status="APPROVED", plan=final_plan, spec_version_label=spec.version_label)
        self._event_log.emit(EventType.PLAN_APPROVED, "internal", {"spec_id": spec_id, "path": existing.path})
        self._user_event(f"Plan approved for {spec_id}: {spec.version_label}")
        return PlanApprovalResult(spec_id=spec_id, spec_version_label=spec.version_label,
                                   artifact_path=existing.path)

    def reject_plan(self, spec_id: str, reason: str) -> PlanResult:
        self._require_operating_mode(OperatingMode.PLAN, "reject_plan")
        validate_spec_id(spec_id)
        existing = self._require_mutable_draft(spec_id, "reject")
        obs = write_plan_artifact(self._gateway, session_mode=self._session_mode, project_root=self._project_root,
                                   path=existing.path, plan=existing.plan, status="REJECTED",
                                   spec_version_label=existing.spec_version_label)
        if obs.status != "ok":
            raise PlanLifecycleError(f"failed to write rejected plan artifact: {obs.error}")

        self._plan_sessions[spec_id] = replace(existing, status="REJECTED")
        self._event_log.emit(EventType.PLAN_REJECTED, "internal",
                              {"spec_id": spec_id, "path": existing.path, "reason": reason})
        self._user_event(f"Plan rejected for {spec_id}: {reason}")
        return PlanResult(status="REJECTED", spec_id=spec_id, message=reason,
                           artifact_path=existing.path, plan=existing.plan)

    def restore_plan_session(self, spec_id: str, *, plan: StructuredPlan, status: str,
                              spec_version_label: str, path: str, version: int,
                              finalized_paths: tuple = ()) -> None:
        """Repopulates self._plan_sessions[spec_id] from persisted, already-
        typed data (Phase 10) so a resumed PLAN session's plan_status/
        revise_plan/approve_plan/reject_plan work exactly as they would
        have before the process restarted. `plan` must already be a
        validated StructuredPlan, never raw checkpoint prose - this method
        restores authoritative Plan Mode state, it does not parse or trust
        anything free-form. Every existing entry point
        (run_plan/revise_plan/approve_plan/reject_plan/plan_status) is
        unmodified; this is purely additive."""
        self._require_operating_mode(OperatingMode.PLAN, "restore_plan_session")
        validate_spec_id(spec_id)
        if status not in ("DRAFT", "REVISED", "APPROVED", "REJECTED"):
            raise ValueError(f"invalid plan session status: {status!r}")
        self._plan_sessions[spec_id] = _PlanSessionState(
            version=version, path=path, status=status, plan=plan,
            spec_version_label=spec_version_label, finalized_paths=finalized_paths)

    def plan_status(self, spec_id: str) -> Optional[PlanResult]:
        """Read-only snapshot of the current plan state for spec_id, or
        None if no planning round has ever run for it in this session.
        The API layer (backend_api.py) uses this instead of reaching into
        Orchestrator's private plan-session state directly."""
        state = self._plan_sessions.get(spec_id)
        if state is None:
            return None
        return PlanResult(status=state.status, spec_id=spec_id, message=f"plan {state.status.lower()}",
                           artifact_path=state.path, plan=state.plan)

    def run_chat(self, session_id: str, message: str) -> ChatResult:
        self._require_operating_mode(OperatingMode.CHAT, "run_chat")
        self._user_event(message)
        bundle = build_planner_context(self._gateway, self._session_mode, self._project_root, message,
                                        operating_mode=self._operating_mode)
        output = self._invoke_with_retry(
            "chat", lambda: self._model.chat({"message": message, "context_bundle": bundle}),
            parse_chat_output)
        reply = output.message if output is not None else \
            "I'm having trouble responding right now - please try again."
        self._user_event(reply)
        return ChatResult(session_id=session_id, message=reply)

    def run_review(self, session_id: str, target_description: str) -> ReviewResult:
        self._require_operating_mode(OperatingMode.REVIEW, "run_review")
        self._user_event(target_description)
        bundle = build_context_bundle(
            gateway=self._gateway, role=Role.REVIEWER, session_mode=self._session_mode,
            project_root=self._project_root, reference_hints=(target_description,),
            operating_mode=self._operating_mode)
        output = self._invoke_with_retry(
            "review_session",
            lambda: self._model.review_session({"target": target_description, "context_bundle": bundle}),
            parse_review_session_output)
        if output is None:
            summary = "review output invalid after max retries"
            self._user_event(summary)
            return ReviewResult(session_id=session_id, summary=summary, findings=())
        self._user_event(output.summary)
        return ReviewResult(session_id=session_id, summary=output.summary, findings=output.findings)

    # ------------------------------------------------------ Plan internals

    def _require_operating_mode(self, expected: OperatingMode, method_name: str) -> None:
        if self._operating_mode is not expected:
            raise ValueError(
                f"{method_name} requires an OperatingMode.{expected.value} session, "
                f"got OperatingMode.{self._operating_mode.value}"
            )

    def _require_mutable_draft(self, spec_id: str, action: str) -> _PlanSessionState:
        existing = self._plan_sessions.get(spec_id)
        if existing is None or existing.status not in ("DRAFT", "REVISED"):
            raise PlanLifecycleError(f"no mutable draft to {action} for spec_id {spec_id!r}")
        return existing

    def _run_planner_plan_cycle(self, spec_id: str, request_text: str, *, is_revision: bool = False,
                                 research_round: int = 0, research_observations: Optional[list] = None) -> PlanResult:
        research_observations = list(research_observations or [])
        bundle = build_planner_context(self._gateway, self._session_mode, self._project_root, request_text,
                                        operating_mode=self._operating_mode)
        model_context: dict = {"request": request_text, "context_bundle": bundle, "spec_id": spec_id}
        if is_revision:
            model_context["revision_request"] = request_text
            existing = self._plan_sessions.get(spec_id)
            if existing is not None:
                model_context["previous_plan"] = existing.plan
        if research_observations:
            model_context["research_observations"] = tuple(research_observations)

        output = self._invoke_with_retry(
            "planner_plan_mode", lambda: self._model.plan_mode(model_context), parse_planner_plan_output)
        if output is None:
            return PlanResult(status="FAILED", spec_id=spec_id,
                               message="planner plan-mode output invalid after max retries")

        if isinstance(output, PlannerClarification):
            self._user_event(output.question)
            return PlanResult(status="NEEDS_INPUT", spec_id=spec_id, message=output.question)

        if isinstance(output, ResearchRequestBatch):
            if research_round >= self._max_plan_research_rounds:
                return PlanResult(
                    status="NEEDS_INPUT", spec_id=spec_id,
                    message=f"plan research exceeded {self._max_plan_research_rounds} rounds - need user input")
            for request in output.requests:
                self._event_log.emit(EventType.PLAN_RESEARCH_REQUESTED, "internal",
                                      {"capability": request.capability, "query": request.query})
                tool_obs = self._gateway.invoke(
                    role=Role.PLANNER, tool_name=request.capability, arguments={"query": request.query},
                    session_mode=self._session_mode, project_root=self._project_root,
                    operating_mode=OperatingMode.PLAN)
                self._event_log.emit(EventType.PLAN_RESEARCH_COMPLETED, "internal", {
                    "capability": request.capability, "status": tool_obs.status, "error": tool_obs.error,
                })
                research_observations.append({
                    "capability": request.capability, "query": request.query,
                    "status": tool_obs.status, "result": tool_obs.result, "error": tool_obs.error,
                })
            return self._run_planner_plan_cycle(
                spec_id, request_text, is_revision=is_revision, research_round=research_round + 1,
                research_observations=research_observations)

        structured_plan = output
        review = self._invoke_with_retry(
            "reviewer_plan_critique", lambda: self._model.review_plan({"plan": structured_plan}),
            parse_reviewer_plan_output)
        reviewer_feedback: tuple = ()
        if review is not None:
            reviewer_feedback = (review.comments + review.missing_requirements
                                  + review.security_concerns + review.unnecessary_complexity)
            self._event_log.emit(EventType.PLAN_REVIEWED, "internal", {"spec_id": spec_id})
        structured_plan = replace(structured_plan, reviewer_feedback=reviewer_feedback)

        return self._write_plan_draft(spec_id, structured_plan)

    def _write_plan_draft(self, spec_id: str, plan: StructuredPlan) -> PlanResult:
        existing = self._plan_sessions.get(spec_id)
        if existing is not None and existing.status in ("DRAFT", "REVISED"):
            version, path, spec_version_label = existing.version, existing.path, existing.spec_version_label
            status = "REVISED"
            finalized_paths = existing.finalized_paths
        else:
            version = predicted_next_version(self._spec_store, spec_id)
            path = plan_artifact_path(spec_id, version, slug=slugify(plan.objective))
            spec_version_label = f"{spec_id}-v{version}"
            status = "DRAFT"
            finalized_paths = (existing.finalized_paths + (existing.path,)) if existing is not None else ()

        plan = replace(plan, target_spec_version_label=spec_version_label)
        obs = write_plan_artifact(self._gateway, session_mode=self._session_mode, project_root=self._project_root,
                                   path=path, plan=plan, status=status, spec_version_label=spec_version_label)
        if obs.status != "ok":
            return PlanResult(status="FAILED", spec_id=spec_id,
                               message=f"failed to write plan artifact: {obs.error}")

        self._plan_sessions[spec_id] = _PlanSessionState(
            version=version, path=path, status=status, plan=plan,
            spec_version_label=spec_version_label, finalized_paths=finalized_paths)

        self._event_log.emit(EventType.PLAN_ARTIFACT_WRITTEN, "internal",
                              {"spec_id": spec_id, "path": path, "status": status})
        self._event_log.emit(EventType.PLAN_REVISED if status == "REVISED" else EventType.PLAN_CREATED,
                              "internal", {"spec_id": spec_id, "path": path})
        self._user_event(f"Plan {status.lower()} for {spec_id}: {path}")
        return PlanResult(status=status, spec_id=spec_id, message=f"plan {status.lower()}",
                           artifact_path=path, plan=plan)

    # ----------------------------------------------------------- internals

    def _transition(self, new_state: State) -> None:
        self._event_log.emit(EventType.STATE_TRANSITION, "internal",
                              {"from": self._state.value, "to": new_state.value})
        self._state = new_state

    def _user_event(self, text: str) -> None:
        self._event_log.emit(EventType.USER_MESSAGE, "user", {"text": text})

    def _invoke_with_retry(self, role_name: str, call_fn, parse_fn):
        for _ in range(self._max_output_retries):
            try:
                raw = call_fn()
            except ModelTimeoutError:
                self._event_log.emit(EventType.MODEL_OUTPUT_INVALID, "internal",
                                      {"role": role_name, "error": "timeout"})
                continue
            try:
                return parse_fn(raw)
            except SchemaValidationError as exc:
                self._event_log.emit(EventType.MODEL_OUTPUT_INVALID, "internal",
                                      {"role": role_name, "error": str(exc)})
                continue
        return None

    def _after_plan(self, spec_id: str, plan_output) -> OrchestratorResult:
        if plan_output is None:
            return self._stuck(spec_id, "planner output invalid after max retries")
        if isinstance(plan_output, PlannerClarification):
            self._transition(State.AWAITING_USER_INPUT)
            self._user_event(plan_output.question)
            return OrchestratorResult(State.AWAITING_USER_INPUT, spec_id, plan_output.question)
        spec = self._spec_store.create(
            spec_id, goals=plan_output.goals, constraints=plan_output.constraints,
            acceptance_criteria=plan_output.acceptance_criteria)
        self._event_log.emit(EventType.SPEC_VERSION_CREATED, "internal", {"version_label": spec.version_label})
        return self._validate_plan(spec_id, spec)

    def _validate_plan(self, spec_id: str, spec: SpecVersion) -> OrchestratorResult:
        self._transition(State.VALIDATE_PLAN)
        if not spec.goals:
            return self._stuck(spec_id, "plan failed deterministic validation: no goals")
        return self._implement(spec_id, spec, reviewer_feedback=None, fix_iteration=0)

    def _implement(self, spec_id: str, spec: SpecVersion, reviewer_feedback, fix_iteration: int,
                    clarification_round: int = 0) -> OrchestratorResult:
        self._transition(State.IMPLEMENT_FIX if fix_iteration > 0 else State.IMPLEMENT)
        coder_output = self._invoke_with_retry(
            "coder", lambda: self._model.code({"spec": spec, "reviewer_feedback": reviewer_feedback}),
            parse_coder_output)
        if coder_output is None:
            return self._stuck(spec_id, "coder output invalid after max retries")
        if isinstance(coder_output, CoderBlocked):
            return self._blocked(spec_id, spec, coder_output, fix_iteration, clarification_round)

        try:
            self._spec_store.assert_current(spec_id, coder_output.spec_version_label)
        except SpecVersionMismatchError as exc:
            self._event_log.emit(EventType.SPEC_VERSION_MISMATCH, "internal",
                                  {"expected": exc.expected, "actual": exc.actual})
            return self._stuck(spec_id, f"coder attempt pinned to wrong specification version: {exc}")

        if fix_iteration > 0 and is_negligible_diff(self._last_file_writes, coder_output.file_writes):
            return self._stuck(
                spec_id, "the fix attempt produced a negligible diff from the previous attempt - no progress detected"
            )
        self._last_file_writes = coder_output.file_writes

        failed = self._apply_file_writes(coder_output)
        if failed is not None:
            return self._stuck(spec_id, f"file write failed during implement: {failed.error}")
        return self._test_and_review(spec_id, spec, coder_output, fix_iteration)

    def _apply_file_writes(self, coder_output: CoderCompleted):
        for write in coder_output.file_writes:
            obs = self._gateway.invoke(
                role=Role.CODER, tool_name="filesystem.write",
                arguments={"path": write.path, "content": write.content},
                session_mode=self._session_mode, project_root=self._project_root,
                operating_mode=self._operating_mode)
            if obs.status != "ok":
                return obs
        return None

    def _test_and_review(self, spec_id: str, spec: SpecVersion, coder_output: CoderCompleted,
                          fix_iteration: int) -> OrchestratorResult:
        self._transition(State.TEST)
        validation_result = self._validator.validate(self._project_root, spec)
        self._validation_detail_history.append(validation_result.details)
        self._transition(State.REVIEW)
        reviewer_output = self._invoke_with_retry(
            "reviewer",
            lambda: self._model.review({"spec": spec, "coder_output": coder_output,
                                         "validation_result": validation_result}),
            parse_reviewer_output)
        if reviewer_output is None:
            return self._stuck(spec_id, "reviewer output invalid after max retries")
        try:
            self._spec_store.assert_current(spec_id, reviewer_output.spec_version_label)
        except SpecVersionMismatchError as exc:
            self._event_log.emit(EventType.SPEC_VERSION_MISMATCH, "internal",
                                  {"expected": exc.expected, "actual": exc.actual})
            return self._stuck(spec_id, f"reviewer spec version mismatch: {exc}")

        if reviewer_output.decision == "APPROVE":
            return self._final_validation(spec_id, spec, coder_output, validation_result,
                                           reviewer_output, fix_iteration)
        self._review_issue_history.append(tuple(issue.description for issue in reviewer_output.issues))
        return self._feedback(spec_id, spec, reviewer_output, fix_iteration)

    def _final_validation(self, spec_id, spec, coder_output, validation_result, reviewer_output, fix_iteration):
        self._transition(State.FINAL_VALIDATION)
        gates_pass = (validation_result.passed and reviewer_output.requirements_met
                      and reviewer_output.security_ok and reviewer_output.validation_ok)
        if gates_pass:
            self._transition(State.COMPLETE)
            self._user_event(coder_output.summary)
            return OrchestratorResult(State.COMPLETE, spec_id, coder_output.summary)
        return self._feedback(spec_id, spec, reviewer_output, fix_iteration)

    def _feedback(self, spec_id: str, spec: SpecVersion, reviewer_output, fix_iteration: int) -> OrchestratorResult:
        self._transition(State.FEEDBACK)
        if fix_iteration >= self._max_fix_iterations:
            return self._stuck(spec_id, f"fix loop exceeded {self._max_fix_iterations} iterations")
        if is_repeated_review_rejection(tuple(self._review_issue_history)):
            return self._stuck(spec_id, "reviewer repeated the same rejection reasons - no progress detected")
        if is_repeated_identical_test_failure(tuple(self._validation_detail_history)):
            return self._stuck(spec_id, "the same validation failure recurred - no progress detected")
        return self._implement(spec_id, spec, reviewer_output, fix_iteration + 1)

    def _blocked(self, spec_id, spec, coder_output: CoderBlocked, fix_iteration, clarification_round):
        self._transition(State.BLOCKED)
        if clarification_round >= self._max_clarification_rounds:
            return self._stuck(spec_id, f"clarification loop exceeded {self._max_clarification_rounds} rounds")
        return self._resolve_clarification(spec_id, spec, coder_output, fix_iteration, clarification_round + 1)

    def _resolve_clarification(self, spec_id, spec, coder_output: CoderBlocked, fix_iteration, clarification_round):
        self._transition(State.RESOLVE_CLARIFICATION)
        resolution = self._invoke_with_retry(
            "planner",
            lambda: self._model.plan({"spec": spec, "blocking_questions": coder_output.blocking_questions}),
            parse_planner_output)
        if resolution is None:
            return self._stuck(spec_id, "planner clarification output invalid after max retries")
        if isinstance(resolution, PlannerClarification):
            self._transition(State.AWAITING_USER_INPUT)
            self._user_event(resolution.question)
            return OrchestratorResult(State.AWAITING_USER_INPUT, spec_id, resolution.question)
        new_spec = self._spec_store.create(
            spec_id, goals=resolution.goals, constraints=resolution.constraints,
            acceptance_criteria=resolution.acceptance_criteria)
        self._event_log.emit(EventType.SPEC_VERSION_CREATED, "internal", {"version_label": new_spec.version_label})
        return self._implement(spec_id, new_spec, reviewer_feedback=None, fix_iteration=fix_iteration,
                                clarification_round=clarification_round)

    def _stuck(self, spec_id: str, reason: str) -> OrchestratorResult:
        self._transition(State.STUCK)
        self._event_log.emit(EventType.INTERNAL, "internal", {"reason": reason})
        self._transition(State.ESCALATE_TO_USER)
        self._user_event(f"I'm stopping and need your input: {reason}")
        return OrchestratorResult(State.ESCALATE_TO_USER, spec_id, reason)
