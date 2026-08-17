"""Explicit, typed-dataclass-to-dict serializers for the backend HTTP/SSE
layer. Every payload is built field-by-field from the existing typed
dataclasses (StructuredPlan, PlanReview, Event, ToolObservation, ...) -
never vars()/__dict__ reflection over an arbitrary object - so a field
can't leak into the wire format just by existing on some internal
class. Internal-stream events, secrets, and private reasoning are
excluded by construction: only user_stream() events are ever passed to
serialize_event here, and MCP server views come from
mcp/preferences.py's describe_server(), which omits credentials
entirely rather than merely masking them.
"""
from __future__ import annotations

from typing import Optional

from .events import Event
from .orchestrator.core import ChatResult, OrchestratorResult, PlanApprovalResult, PlanResult, ReviewResult
from .orchestrator.plan_schemas import StructuredPlan
from .persistence.records import CheckpointRecord, MessageRecord, ReconstructedContext, SessionRecord


def serialize_structured_plan(plan: StructuredPlan) -> dict:
    return {
        "objective": plan.objective,
        "requirements": list(plan.requirements),
        "existing_context": list(plan.existing_context),
        "proposed_architecture": plan.proposed_architecture,
        "files_to_create": list(plan.files_to_create),
        "files_to_modify": list(plan.files_to_modify),
        "dependencies": list(plan.dependencies),
        "implementation_steps": list(plan.implementation_steps),
        "validation_strategy": list(plan.validation_strategy),
        "risks": list(plan.risks),
        "unknowns": list(plan.unknowns),
        "acceptance_criteria": list(plan.acceptance_criteria),
        "reviewer_feedback": list(plan.reviewer_feedback),
        "target_spec_version_label": plan.target_spec_version_label,
    }


def serialize_plan_result(result: PlanResult) -> dict:
    return {
        "status": result.status,
        "spec_id": result.spec_id,
        "message": result.message,
        "artifact_path": result.artifact_path,
        "plan": serialize_structured_plan(result.plan) if result.plan is not None else None,
    }


def serialize_plan_approval_result(result: PlanApprovalResult) -> dict:
    return {
        "spec_id": result.spec_id,
        "spec_version_label": result.spec_version_label,
        "artifact_path": result.artifact_path,
    }


def serialize_chat_result(result: ChatResult) -> dict:
    return {"session_id": result.session_id, "message": result.message}


def serialize_review_result(result: ReviewResult) -> dict:
    return {"session_id": result.session_id, "summary": result.summary, "findings": list(result.findings)}


def serialize_orchestrator_result(result: OrchestratorResult) -> dict:
    return {"final_state": result.final_state.value, "spec_id": result.spec_id, "summary": result.summary}


def serialize_event(event: Event) -> dict:
    return {
        "event_type": event.event_type.value,
        "stream": event.stream,
        "payload": dict(event.payload),
        "timestamp": event.timestamp,
    }


def serialize_stream_event(session_id: str, *, event_type: str, timestamp: float, payload: dict,
                            spec_version_label: Optional[str] = None) -> dict:
    """The one stable shape GET /sessions/{id}/events normalizes every
    event into - plain EventLog.user_stream() text and Phase 10's
    persisted, already-safe decision records alike. Minimum fields per
    Phase 11 Part 10: session_id, event_type, timestamp, a safe payload,
    and specification version where applicable."""
    return {
        "session_id": session_id, "event_type": event_type, "timestamp": timestamp,
        "payload": dict(payload), "spec_version_label": spec_version_label,
    }


def error_envelope(message: str, code: str) -> dict:
    return {"error": message, "code": code}


# --------------------------------------------------------- Phase 11 (configuration)

def serialize_configuration_view(view: dict) -> dict:
    """Explicit field-by-field re-projection of SettingsService.safe_view()
    - a defense-in-depth allowlist on top of an already-safe dict, never a
    passthrough of an arbitrary object. A credential key could not survive
    this even if one somehow reached `view`."""
    return {
        "models": {role: dict(info) for role, info in view.get("models", {}).items()},
        "mcp": {
            server_id: {
                "enabled": entry.get("enabled"),
                "transport": entry.get("transport"),
                "capabilities": list(entry.get("capabilities", [])),
            }
            for server_id, entry in view.get("mcp", {}).items()
        },
        "agent_behavior": dict(view.get("agent_behavior", {})),
        "precedence": dict(view.get("precedence", {})),
    }


def serialize_model_settings(described: dict) -> dict:
    return {"models": {role: dict(info) for role, info in described.items()}}


def serialize_available_models(described: dict, installed: tuple) -> dict:
    return {"models": {role: dict(info) for role, info in described.items()}, "installed": list(installed)}


# ------------------------------------------------------------ Phase 10 (persistence)

def serialize_session_summary(record: SessionRecord) -> dict:
    return {
        "session_id": record.session_id, "operating_mode": record.operating_mode,
        "status": record.status, "spec_id": record.spec_id, "updated_at": record.updated_at,
    }


def serialize_session_detail(record: SessionRecord) -> dict:
    return {
        "session_id": record.session_id, "operating_mode": record.operating_mode,
        "session_mode": record.session_mode, "spec_id": record.spec_id, "status": record.status,
        "active_spec_version": record.active_spec_version, "active_plan_id": record.active_plan_id,
        "current_checkpoint_id": record.current_checkpoint_id,
        "fix_iteration_count": record.fix_iteration_count,
        "clarification_round_count": record.clarification_round_count,
        "created_at": record.created_at, "updated_at": record.updated_at, "archived_at": record.archived_at,
    }


def serialize_message(record: MessageRecord) -> dict:
    return {"seq": record.seq, "speaker": record.speaker, "content": record.content,
            "created_at": record.created_at}


def serialize_checkpoint_summary(record: CheckpointRecord) -> dict:
    return {
        "id": record.id, "seq": record.seq, "reason": record.reason, "objective": record.objective,
        "spec_version_label": record.spec_version_label, "created_at": record.created_at,
    }


def serialize_checkpoint_detail(record: CheckpointRecord) -> dict:
    return {
        "id": record.id, "seq": record.seq, "spec_id": record.spec_id,
        "spec_version_label": record.spec_version_label, "operating_mode": record.operating_mode,
        "objective": record.objective, "completed_work": list(record.completed_work),
        "current_problem": record.current_problem, "relevant_decisions": list(record.relevant_decisions),
        "reviewer_feedback": list(record.reviewer_feedback), "validation_passed": record.validation_passed,
        "validation_details": list(record.validation_details), "changed_files": list(record.changed_files),
        "next_action": record.next_action, "constraints": list(record.constraints),
        "context_references": list(record.context_references), "reason": record.reason,
        "created_at": record.created_at,
    }


def serialize_reconstructed_context(result: ReconstructedContext) -> dict:
    return {
        "operating_mode": result.operating_mode, "session_mode": result.session_mode,
        "spec_id": result.spec_id,
        "spec_version_label": result.spec_version.version_label if result.spec_version else None,
        "checkpoint": serialize_checkpoint_detail(result.checkpoint) if result.checkpoint else None,
        "stale": result.stale, "stale_reasons": list(result.stale_reasons),
        "recent_messages": [serialize_message(m) for m in result.recent_messages],
        "project_files": [{"path": f.path, "category": f.category, "truncated": f.truncated}
                           for f in (result.project_bundle.files if result.project_bundle else ())],
        "messages_dropped_for_budget": len(result.messages_dropped_for_budget),
    }
