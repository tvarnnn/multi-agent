"""The deterministic orchestrator. Models propose (via ModelProvider),
the orchestrator decides (every transition below is driven by a
schema-validated structured output or a deterministic gate, never by
parsing free-form prose). No model gets a direct execution path - file
writes go through the ToolGateway, which re-enforces Phase 0's sandbox
and permission system on every call.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..events import EventLog, EventType
from ..security.enums import Role, SessionMode
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
from .states import State
from .validation import Validator


@dataclass(frozen=True)
class OrchestratorResult:
    final_state: State
    spec_id: str
    summary: str


class Orchestrator:
    def __init__(self, *, gateway: ToolGateway, model, spec_store: SpecStore,
                 event_log: EventLog, session_mode: SessionMode, project_root: Path,
                 validator: Validator, max_output_retries: int = 3,
                 max_clarification_rounds: int = 3, max_fix_iterations: int = 3):
        self._gateway = gateway
        self._model = model
        self._spec_store = spec_store
        self._event_log = event_log
        self._session_mode = session_mode
        self._project_root = project_root
        self._validator = validator
        self._max_output_retries = max_output_retries
        self._max_clarification_rounds = max_clarification_rounds
        self._max_fix_iterations = max_fix_iterations
        self._state = State.RECEIVE_REQUEST

    @property
    def state(self) -> State:
        return self._state

    def run(self, spec_id: str, user_request: str) -> OrchestratorResult:
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
        self._user_event(amendment_request)
        self._transition(State.AMEND_REQUIREMENTS)
        plan_output = self._invoke_with_retry(
            "planner", lambda: self._model.plan({"request": amendment_request, "amendment": True}),
            parse_planner_output)
        return self._after_plan(spec_id, plan_output)

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

        failed = self._apply_file_writes(coder_output)
        if failed is not None:
            return self._stuck(spec_id, f"file write failed during implement: {failed.error}")
        return self._test_and_review(spec_id, spec, coder_output, fix_iteration)

    def _apply_file_writes(self, coder_output: CoderCompleted):
        for write in coder_output.file_writes:
            obs = self._gateway.invoke(
                role=Role.CODER, tool_name="filesystem.write",
                arguments={"path": write.path, "content": write.content},
                session_mode=self._session_mode, project_root=self._project_root)
            if obs.status != "ok":
                return obs
        return None

    def _test_and_review(self, spec_id: str, spec: SpecVersion, coder_output: CoderCompleted,
                          fix_iteration: int) -> OrchestratorResult:
        self._transition(State.TEST)
        validation_result = self._validator.validate(self._project_root, spec)
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
