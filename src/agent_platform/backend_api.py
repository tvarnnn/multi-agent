"""Thin FastAPI translation layer over Orchestrator (design §9-§13). Every
route handler constructs an Orchestrator call, or reads already-emitted
EventLog/PlanResult state, and serializes the result via
api_serialization.py - no route handler ever calls ToolGateway,
PermissionEvaluator, MCPClient, or the filesystem directly. Every route
requires a valid bearer token, checked before any session or
orchestrator state is touched.
"""
from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from .api_serialization import (
    error_envelope,
    serialize_available_models,
    serialize_chat_result,
    serialize_checkpoint_summary,
    serialize_configuration_view,
    serialize_message,
    serialize_orchestrator_result,
    serialize_plan_approval_result,
    serialize_plan_result,
    serialize_reconstructed_context,
    serialize_review_result,
    serialize_session_detail,
    serialize_session_summary,
    serialize_stream_event,
)
from .events import EventLog
from .mcp.preferences import MCPUserPreferences, describe_server
from .mcp.schemas import MCPServerConfig
from .orchestrator.core import Orchestrator, PlanLifecycleError
from .orchestrator.plan_schemas import InvalidSpecIdError, validate_spec_id
from .orchestrator.validation import Validator
from .persistence.service import SessionPersistenceService
from .security.enums import OperatingMode, SessionMode
from .security.permission import PermissionEvaluator
from .security.sandbox import FilesystemSandbox
from .settings.model_discovery import describe_configured_models, discover_installed_models
from .settings.service import SettingsService
from .spec.versioning import SpecStore
from .tools.gateway import ToolGateway
from .tools.registry import ToolRegistry


@dataclass
class BackendServices:
    """Shared, process-lifetime services every session's Orchestrator is
    built from. registry/evaluator are stateless enough to share across
    sessions; each session still gets its own EventLog (SSE isolation)
    and its own Orchestrator instance (one OperatingMode per session,
    immutable for its lifetime - design §1.1)."""
    project_root: Path
    spec_store: SpecStore
    model: object
    validator: Validator
    registry: ToolRegistry
    evaluator: PermissionEvaluator
    sandbox: FilesystemSandbox
    persistence: SessionPersistenceService
    settings: SettingsService
    session_mode: SessionMode = SessionMode.AUTO
    max_plan_research_rounds: int = 3
    mcp_servers: tuple = ()
    mcp_clients: dict = field(default_factory=dict)
    mcp_preferences: MCPUserPreferences = field(default_factory=MCPUserPreferences)
    # Phase 11: injectable so tests never touch the real network - mirrors
    # OllamaModelProvider's existing http_post injection point. None means
    # "use the real (network-optional, never-raising) Ollama /api/tags query".
    model_discovery_query_fn: Optional[object] = None


@dataclass
class _Session:
    orchestrator: Orchestrator
    event_log: EventLog
    operating_mode: OperatingMode
    spec_id: Optional[str] = None


class CreateSessionRequest(BaseModel):
    operating_mode: str
    spec_id: Optional[str] = None


class MessageRequest(BaseModel):
    message: str


class RevisionRequest(BaseModel):
    revision_request: str


class RejectionRequest(BaseModel):
    reason: str


class MCPPreferenceUpdate(BaseModel):
    enabled: Optional[bool] = None
    capability_overrides: Optional[dict] = None


def _http_error(status_code: int, message: str, code: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=error_envelope(message, code))


# Every session_id this backend ever mints is secrets.token_urlsafe(16) -
# URL-safe base64 (A-Za-z0-9_-), well under 64 chars. This pattern rejects
# anything else (path separators, traversal sequences, control characters,
# oversized input) before a client-supplied session_id can reach the
# persistence layer at all - defense in depth on top of
# FilesystemSandbox.authorize() already denying any resulting path escape.
_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_PLAN_VERSION_SUFFIX = re.compile(r"-v(\d+)$")


def _validate_session_id(session_id: str) -> None:
    if not _SESSION_ID_PATTERN.match(session_id):
        raise _http_error(400, "malformed session_id", "BAD_REQUEST")


def _plan_version_from_label(spec_version_label: str) -> int:
    match = _PLAN_VERSION_SUFFIX.search(spec_version_label)
    if match is None:
        raise _http_error(500, f"malformed spec_version_label: {spec_version_label!r}", "INTERNAL")
    return int(match.group(1))


def create_app(services: BackendServices, token: str) -> FastAPI:
    app = FastAPI(title="agent-platform backend")
    sessions: dict[str, _Session] = {}

    def _require_auth(authorization: str = Header(default="")) -> None:
        presented = authorization[len("Bearer "):] if authorization.startswith("Bearer ") else ""
        if not presented or not secrets.compare_digest(presented, token):
            raise _http_error(401, "missing or invalid bearer token", "UNAUTHORIZED")

    @app.middleware("http")
    async def _enforce_auth_before_routing(request: Request, call_next):
        # Runs before Starlette's routing resolves a handler, so an
        # unauthenticated caller learns nothing about which paths exist -
        # an unknown route with a bad/missing token gets 401, never 404.
        # The route-level dependency above still applies too (defense in
        # depth), but this is what makes auth-before-routing true for
        # paths that never match any route.
        presented = request.headers.get("authorization", "")
        presented = presented[len("Bearer "):] if presented.startswith("Bearer ") else ""
        if not presented or not secrets.compare_digest(presented, token):
            # Matches the shape FastAPI's own HTTPException handler produces
            # (`{"detail": ...}`) so callers see one consistent error
            # contract regardless of whether a route matched.
            return JSONResponse(
                status_code=401,
                content={"detail": error_envelope("missing or invalid bearer token", "UNAUTHORIZED")},
            )
        return await call_next(request)

    router = APIRouter(dependencies=[Depends(_require_auth)])

    def _get_session(session_id: str) -> _Session:
        _validate_session_id(session_id)
        session = sessions.get(session_id)
        if session is None:
            raise _http_error(404, "unknown session", "NOT_FOUND")
        return session

    def _require_plan_mode(session: _Session) -> None:
        if session.operating_mode is not OperatingMode.PLAN:
            raise _http_error(409, "session is not in PLAN mode", "WRONG_MODE")

    def _mcp_server(server_id: str) -> MCPServerConfig:
        for server in services.mcp_servers:
            if server.server_id == server_id:
                return server
        raise _http_error(404, f"unknown MCP server: {server_id}", "NOT_FOUND")

    @router.post("/sessions")
    def create_session(body: CreateSessionRequest):
        try:
            operating_mode = OperatingMode(body.operating_mode)
        except ValueError:
            raise _http_error(400, f"invalid operating_mode: {body.operating_mode!r}", "BAD_REQUEST")

        if body.spec_id is not None:
            try:
                validate_spec_id(body.spec_id)
            except InvalidSpecIdError as exc:
                raise _http_error(400, str(exc), "BAD_REQUEST")
        if operating_mode in (OperatingMode.PLAN, OperatingMode.CODE, OperatingMode.EDIT) and body.spec_id is None:
            raise _http_error(400, f"spec_id is required for {operating_mode.value} mode sessions", "BAD_REQUEST")

        session_id = secrets.token_urlsafe(16)
        event_log = EventLog()
        gateway = ToolGateway(services.registry, services.evaluator, event_log)
        orchestrator = Orchestrator(
            gateway=gateway, model=services.model, spec_store=services.spec_store, event_log=event_log,
            session_mode=services.session_mode, project_root=services.project_root, validator=services.validator,
            operating_mode=operating_mode, max_plan_research_rounds=services.max_plan_research_rounds,
        )
        sessions[session_id] = _Session(orchestrator=orchestrator, event_log=event_log,
                                         operating_mode=operating_mode, spec_id=body.spec_id)
        services.persistence.create_session(session_id, operating_mode=operating_mode.value,
                                             session_mode=services.session_mode.value, spec_id=body.spec_id)
        return {"session_id": session_id}

    def _record_plan_snapshot_and_decision(session_id: str, session: _Session, result) -> None:
        """Shared by post_message(PLAN)/revise_plan/reject_plan - never
        duplicated inline. Records the plan draft/revision/rejection as a
        structured decision plus a full plan_snapshot (needed so a resumed
        PLAN session's draft survives a restart - Orchestrator._plan_sessions
        is in-memory only)."""
        event_type = {"DRAFT": "PLAN_CREATED", "REVISED": "PLAN_REVISED",
                       "REJECTED": "PLAN_REJECTED"}.get(result.status)
        if event_type is not None and result.artifact_path is not None:
            services.persistence.record_decision(
                session_id, event_type=event_type, payload={"spec_id": result.spec_id, "path": result.artifact_path})
        if result.plan is not None and result.artifact_path is not None:
            services.persistence.record_plan_snapshot(
                session_id, spec_id=result.spec_id,
                version=_plan_version_from_label(result.plan.target_spec_version_label),
                status=result.status, path=result.artifact_path,
                spec_version_label=result.plan.target_spec_version_label, finalized_paths=(), plan=result.plan,
            )

    def _record_orchestrator_result(session_id: str, session: _Session, result) -> None:
        """Shared by the CODE/EDIT branches below. Persists the SpecVersion
        SpecStore just created/updated internally (run()/amend_requirements()
        call SpecStore.create() themselves - no field on OrchestratorResult
        exposes the SpecVersion object, so it's read back via spec_store.latest())
        so a restart rehydrates to the correct next version, and forces the
        checkpoint milestone Phase 10 always intended for CODE/EDIT completion
        but had no route to trigger from until this phase."""
        try:
            latest_spec = services.spec_store.latest(session.spec_id)
            services.persistence.record_spec_version(latest_spec)
            services.persistence.set_active_spec_version(session_id, latest_spec.version)
        except KeyError:
            pass  # e.g. AWAITING_USER_INPUT before any spec was ever created
        if result.final_state.value in ("COMPLETE", "ESCALATE_TO_USER"):
            services.persistence.force_checkpoint(session_id, reason="terminal_state")

    @router.post("/sessions/{session_id}/messages")
    def post_message(session_id: str, body: MessageRequest):
        session = _get_session(session_id)
        services.persistence.record_message(session_id, speaker="user", content=body.message)
        try:
            if session.operating_mode is OperatingMode.CHAT:
                result = session.orchestrator.run_chat(session_id, body.message)
                services.persistence.record_message(session_id, speaker="assistant", content=result.message)
                services.persistence.maybe_compact(session_id)
                return serialize_chat_result(result)
            if session.operating_mode is OperatingMode.PLAN:
                result = session.orchestrator.run_plan(session.spec_id, body.message)
                services.persistence.record_message(session_id, speaker="assistant", content=result.message)
                _record_plan_snapshot_and_decision(session_id, session, result)
                services.persistence.maybe_compact(session_id)
                return serialize_plan_result(result)
            if session.operating_mode is OperatingMode.REVIEW:
                result = session.orchestrator.run_review(session_id, body.message)
                services.persistence.record_message(session_id, speaker="assistant", content=result.summary)
                services.persistence.maybe_compact(session_id)
                return serialize_review_result(result)
            if session.operating_mode is OperatingMode.CODE:
                result = session.orchestrator.run(session.spec_id, body.message)
                services.persistence.record_message(session_id, speaker="assistant", content=result.summary)
                _record_orchestrator_result(session_id, session, result)
                services.persistence.maybe_compact(session_id)
                return serialize_orchestrator_result(result)
            if session.operating_mode is OperatingMode.EDIT:
                result = session.orchestrator.amend_requirements(session.spec_id, body.message)
                services.persistence.record_message(session_id, speaker="assistant", content=result.summary)
                _record_orchestrator_result(session_id, session, result)
                services.persistence.maybe_compact(session_id)
                return serialize_orchestrator_result(result)
        except InvalidSpecIdError as exc:
            raise _http_error(400, str(exc), "BAD_REQUEST")
        raise _http_error(
            409, f"operating mode {session.operating_mode.value} does not support /messages", "WRONG_MODE")

    @router.get("/sessions/{session_id}/events")
    def get_events(session_id: str):
        """Merges plain conversational text (EventLog.user_stream() - never
        internal reasoning/state-machine-internals, unchanged since Phase 1)
        with structured decision events already persisted by Phase 10
        (PLAN_CREATED/PLAN_APPROVED/SPEC_VERSION_CREATED/... - themselves
        only ever recorded from already-typed route-handler results, never
        drained from internal traces) into one stable, time-ordered shape."""
        session = _get_session(session_id)
        combined = [
            (e.timestamp, serialize_stream_event(
                session_id, event_type=e.event_type.value, timestamp=e.timestamp, payload=dict(e.payload)))
            for e in session.event_log.user_stream()
        ]
        for decision in services.persistence.get_decisions(session_id):
            combined.append((decision.created_at, serialize_stream_event(
                session_id, event_type=decision.event_type, timestamp=decision.created_at,
                payload=decision.payload, spec_version_label=decision.payload.get("version_label"))))
        combined.sort(key=lambda item: item[0])
        lines = [f"data: {json.dumps(item[1])}\n\n" for item in combined]

        def _generate():
            for line in lines:
                yield line

        return StreamingResponse(_generate(), media_type="text/event-stream")

    @router.get("/sessions/{session_id}/plan")
    def get_plan(session_id: str):
        session = _get_session(session_id)
        _require_plan_mode(session)
        result = session.orchestrator.plan_status(session.spec_id)
        if result is None:
            raise _http_error(404, "no plan has been drafted for this session yet", "NOT_FOUND")
        return serialize_plan_result(result)

    @router.post("/sessions/{session_id}/plan/revise")
    def revise_plan(session_id: str, body: RevisionRequest):
        session = _get_session(session_id)
        _require_plan_mode(session)
        services.persistence.record_message(session_id, speaker="user", content=body.revision_request)
        try:
            result = session.orchestrator.revise_plan(session.spec_id, body.revision_request)
        except PlanLifecycleError as exc:
            raise _http_error(409, str(exc), "CONFLICT")
        services.persistence.record_message(session_id, speaker="assistant", content=result.message)
        _record_plan_snapshot_and_decision(session_id, session, result)
        services.persistence.maybe_compact(session_id)
        return serialize_plan_result(result)

    @router.post("/sessions/{session_id}/plan/approve")
    def approve_plan(session_id: str):
        session = _get_session(session_id)
        _require_plan_mode(session)
        try:
            result = session.orchestrator.approve_plan(session.spec_id)
        except PlanLifecycleError as exc:
            raise _http_error(409, str(exc), "CONFLICT")
        # approve_plan() returns PlanApprovalResult (no .plan field) - plan_status()
        # reads back the same now-APPROVED state Orchestrator just finalized, so the
        # persisted snapshot carries the full StructuredPlan too.
        approved = session.orchestrator.plan_status(session.spec_id)
        services.persistence.record_decision(
            session_id, event_type="SPEC_VERSION_CREATED", payload={"version_label": result.spec_version_label})
        services.persistence.record_decision(
            session_id, event_type="PLAN_APPROVED", payload={"spec_id": result.spec_id, "path": result.artifact_path})
        if approved is not None:
            _record_plan_snapshot_and_decision(session_id, session, approved)
        latest_spec = services.spec_store.latest(session.spec_id)
        services.persistence.record_spec_version(latest_spec)
        services.persistence.set_active_spec_version(session_id, latest_spec.version)
        services.persistence.force_checkpoint(session_id, reason="plan_approved")
        return serialize_plan_approval_result(result)

    @router.post("/sessions/{session_id}/plan/reject")
    def reject_plan(session_id: str, body: RejectionRequest):
        session = _get_session(session_id)
        _require_plan_mode(session)
        services.persistence.record_message(session_id, speaker="user", content=body.reason)
        try:
            result = session.orchestrator.reject_plan(session.spec_id, body.reason)
        except PlanLifecycleError as exc:
            raise _http_error(409, str(exc), "CONFLICT")
        services.persistence.record_message(session_id, speaker="assistant", content=result.message)
        _record_plan_snapshot_and_decision(session_id, session, result)
        services.persistence.force_checkpoint(session_id, reason="plan_rejected")
        return serialize_plan_result(result)

    @router.get("/sessions/{session_id}/state")
    def get_state(session_id: str):
        session = _get_session(session_id)
        return {"state": session.orchestrator.state.value, "operating_mode": session.operating_mode.value}

    # ---------------------------------------------------- Phase 10: persistence

    def _require_persisted_session(session_id: str):
        _validate_session_id(session_id)
        record = services.persistence.get_session(session_id)
        if record is None:
            raise _http_error(404, "unknown session", "NOT_FOUND")
        return record

    @router.get("/sessions")
    def list_sessions():
        return {"sessions": [serialize_session_summary(r) for r in services.persistence.list_sessions()]}

    @router.get("/sessions/{session_id}")
    def get_session_detail(session_id: str):
        record = _require_persisted_session(session_id)
        return serialize_session_detail(record)

    @router.get("/sessions/{session_id}/history")
    def get_history(session_id: str, before_seq: Optional[int] = None, limit: int = 50):
        _require_persisted_session(session_id)
        bounded_limit = max(1, min(limit, 200))
        history = services.persistence.get_history(session_id, before_seq=before_seq, limit=bounded_limit)
        return {"messages": [serialize_message(m) for m in history]}

    @router.get("/sessions/{session_id}/checkpoints")
    def get_checkpoints(session_id: str):
        _require_persisted_session(session_id)
        return {"checkpoints": [serialize_checkpoint_summary(c) for c in services.persistence.get_checkpoints(
            session_id)]}

    @router.post("/sessions/{session_id}/resume")
    def resume_session(session_id: str):
        record = _require_persisted_session(session_id)
        # AUTHORITATIVE: operating_mode/session_mode come only from the persisted
        # sessions row (itself only ever written by create_session above, from an
        # already-validated request) - never from checkpoint content, which
        # reconstruct_for_resume() below treats as inert data throughout.
        operating_mode = OperatingMode(record.operating_mode)
        session_mode = SessionMode(record.session_mode)
        reconstructed = services.persistence.resume(session_id)

        event_log = EventLog()
        gateway = ToolGateway(services.registry, services.evaluator, event_log)
        orchestrator = Orchestrator(
            gateway=gateway, model=services.model, spec_store=services.spec_store, event_log=event_log,
            session_mode=session_mode, project_root=services.project_root, validator=services.validator,
            operating_mode=operating_mode, max_plan_research_rounds=services.max_plan_research_rounds,
        )
        if operating_mode is OperatingMode.PLAN and record.spec_id is not None:
            snapshot = services.persistence.latest_plan_snapshot(session_id, record.spec_id)
            if snapshot is not None:
                orchestrator.restore_plan_session(
                    record.spec_id, plan=snapshot.plan, status=snapshot.status,
                    spec_version_label=snapshot.spec_version_label, path=snapshot.path,
                    version=snapshot.version, finalized_paths=snapshot.finalized_paths,
                )
        sessions[session_id] = _Session(orchestrator=orchestrator, event_log=event_log,
                                         operating_mode=operating_mode, spec_id=record.spec_id)
        return serialize_reconstructed_context(reconstructed)

    @router.post("/sessions/{session_id}/archive")
    def archive_session_route(session_id: str):
        _require_persisted_session(session_id)
        services.persistence.archive_session(session_id)
        sessions.pop(session_id, None)
        return {"session_id": session_id, "status": "ARCHIVED"}

    # -------------------------------------------------- Phase 11: configuration
    #
    # Configuration is preference, not authority: every route below only ever
    # reads SettingsService.safe_view()/model_settings - it never calls
    # PermissionEvaluator, ToolGateway, or FilesystemSandbox, and there is no
    # mutation route for anything beyond the existing, unchanged
    # PUT /mcp/servers/{server_id}/preferences (narrowing-only, Phase 9).

    @router.get("/configuration")
    def get_configuration():
        return serialize_configuration_view(services.settings.safe_view())

    @router.get("/configuration/models")
    def get_configuration_models():
        installed = discover_installed_models(query_fn=services.model_discovery_query_fn)
        described = describe_configured_models(services.settings.model_settings, installed=installed)
        return serialize_available_models(described, installed)

    @router.get("/configuration/mcp")
    def get_configuration_mcp():
        return {"mcp": serialize_configuration_view(services.settings.safe_view())["mcp"]}

    @router.get("/mcp/servers")
    def list_mcp_servers():
        views = [
            describe_server(server, services.mcp_clients[server.server_id], services.mcp_preferences)
            for server in services.mcp_servers
        ]
        return {"servers": views}

    @router.put("/mcp/servers/{server_id}/preferences")
    def put_mcp_preferences(server_id: str, body: MCPPreferenceUpdate):
        server = _mcp_server(server_id)
        if body.enabled is not None:
            services.mcp_preferences.set_enabled(server_id, body.enabled)
        for capability, enabled in (body.capability_overrides or {}).items():
            services.mcp_preferences.set_capability_enabled(server_id, capability, enabled)
        return describe_server(server, services.mcp_clients[server_id], services.mcp_preferences)

    app.include_router(router)
    return app
