"""Executes exactly one (task, configuration) pair against the real,
unmodified orchestrator stack and returns a fully raw, machine-readable
result dict. No git, no mutation of src/agent_platform, no manual
intervention: if the run reaches AWAITING_USER_INPUT, that is recorded
as the run's terminal outcome (the platform currently has no
resume-with-an-answer entry point - see PHASE8 methodology notes), never
faked past.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from agent_platform.events import EventLog, EventType
from agent_platform.orchestrator.context_aware_provider import ContextAwareModelProvider
from agent_platform.orchestrator.core import Orchestrator
from agent_platform.orchestrator.ollama_provider import OllamaModelProvider
from agent_platform.orchestrator.validation import (
    AcceptanceCriteriaFileValidator,
    CompositeValidator,
    TestRunValidator,
)
from agent_platform.security.enums import Role, SessionMode
from agent_platform.security.permission import PermissionEvaluator
from agent_platform.security.sandbox import FilesystemSandbox
from agent_platform.spec.versioning import SpecStore
from agent_platform.tools.gateway import ToolGateway
from agent_platform.tools.registry import build_default_registry

from .configurations import MAX_CLARIFICATION_ROUNDS, MAX_FIX_ITERATIONS, MAX_OUTPUT_RETRIES, Configuration
from .dataset import BenchmarkTask
from .instrumentation import TimingWrapper, VramSampler

WORKSPACE_ROOT = Path(__file__).resolve().parent / "workspace"


def _prepare_project_dir(task: BenchmarkTask, config: Configuration) -> Path:
    run_root = WORKSPACE_ROOT / f"{config.name.split(' ')[1].strip('()')}_{task.task_id}"
    if run_root.exists():
        # Guarantee every run starts from a clean starting_files-only state -
        # a stale file left by a prior (e.g. dry-run) attempt at the same
        # task/configuration pair must never leak into this run.
        shutil.rmtree(run_root)
    run_root.mkdir(parents=True)
    project_root = run_root / "proj"
    project_root.mkdir(exist_ok=True)
    for rel_path, content in task.starting_files.items():
        target = project_root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return project_root


def run_one(task: BenchmarkTask, config: Configuration) -> dict:
    project_root = _prepare_project_dir(task, config)
    sandbox = FilesystemSandbox(project_root.parent)
    evaluator = PermissionEvaluator(sandbox)
    event_log = EventLog()
    gateway = ToolGateway(build_default_registry(), evaluator, event_log)
    spec_store = SpecStore()

    real_provider = OllamaModelProvider(
        planner_model=config.planner_model, coder_model=config.coder_model, reviewer_model=config.reviewer_model,
    )
    inner_timer = TimingWrapper(real_provider, "inner_generation_only")
    context_aware = ContextAwareModelProvider(
        inner_timer, gateway=gateway, session_mode=SessionMode.AUTO, project_root=project_root,
    )
    outer_timer = TimingWrapper(context_aware, "outer_including_context_retrieval")

    validator = CompositeValidator((
        AcceptanceCriteriaFileValidator(),
        TestRunValidator(gateway, Role.CODER, SessionMode.AUTO),
    ))
    orchestrator = Orchestrator(
        gateway=gateway, model=outer_timer, spec_store=spec_store, event_log=event_log,
        session_mode=SessionMode.AUTO, project_root=project_root, validator=validator,
        max_output_retries=MAX_OUTPUT_RETRIES, max_clarification_rounds=MAX_CLARIFICATION_ROUNDS,
        max_fix_iterations=MAX_FIX_ITERATIONS,
    )

    vram = VramSampler()
    vram.start()
    t0 = time.monotonic()
    error: str | None = None
    try:
        result = orchestrator.run(task.task_id, task.user_request)
        final_state = result.final_state.value
        summary = result.summary
    except Exception as exc:  # noqa: BLE001 - a crash is itself a measured outcome, not something to hide
        final_state = "HARNESS_EXCEPTION"
        summary = f"{type(exc).__name__}: {exc}"
        error = summary
    wall_s = time.monotonic() - t0
    vram.stop()

    ground_truth = None
    if task.check is not None:
        try:
            gt = task.check(project_root)
            ground_truth = {"applicable": gt.applicable, "passed": gt.passed, "detail": gt.detail}
        except Exception as exc:  # noqa: BLE001 - a ground-truth check crash (e.g. ImportError) is itself signal
            ground_truth = {"applicable": True, "passed": False, "detail": f"ground truth check raised {type(exc).__name__}: {exc}"}

    stuck_reasons = [e.payload["reason"] for e in event_log.internal_stream() if e.event_type == EventType.INTERNAL]
    state_transitions = [e.payload for e in event_log.internal_stream() if e.event_type == EventType.STATE_TRANSITION]
    tool_invocations = [e.payload for e in event_log.internal_stream() if e.event_type == EventType.TOOL_INVOKED]
    tool_denials = [e.payload for e in event_log.internal_stream() if e.event_type == EventType.TOOL_DENIED]

    role_by_method = {"plan": "planner", "code": "coder", "review": "reviewer"}
    model_by_method = {"plan": config.planner_model, "code": config.coder_model, "review": config.reviewer_model}

    per_call = []
    previous_model = None
    swap_count = 0
    for i, outer_rec in enumerate(outer_timer.calls):
        inner_rec = inner_timer.calls[i] if i < len(inner_timer.calls) else None
        telemetry = real_provider.telemetry_log[i] if i < len(real_provider.telemetry_log) else None
        model_name = model_by_method[outer_rec.method]
        is_swap = previous_model is not None and previous_model != model_name
        if is_swap:
            swap_count += 1
        previous_model = model_name
        record = {
            "index": i,
            "method": outer_rec.method,
            "role": role_by_method[outer_rec.method],
            "model": model_name,
            "outer_total_duration_s": outer_rec.duration_s,
            "inner_generation_duration_s": inner_rec.duration_s if inner_rec else None,
            "context_retrieval_duration_s": (
                outer_rec.duration_s - inner_rec.duration_s if inner_rec else None
            ),
            "was_model_swap": is_swap,
            "reviewer_decision": outer_rec.reviewer_decision,
            "validation_passed_at_review_time": outer_rec.validation_passed,
        }
        if telemetry is not None:
            record.update({
                "ollama_load_duration_ns": telemetry.load_duration_ns,
                "ollama_eval_duration_ns": telemetry.eval_duration_ns,
                "ollama_total_duration_ns": telemetry.total_duration_ns,
                "ollama_prompt_eval_count": telemetry.prompt_eval_count,
                "ollama_eval_count": telemetry.eval_count,
                "derived_prompt_processing_ns": max(
                    0, telemetry.total_duration_ns - telemetry.load_duration_ns - telemetry.eval_duration_ns
                ),
            })
        per_call.append(record)

    return {
        "task_id": task.task_id,
        "category": task.category,
        "configuration": config.name,
        "final_state": final_state,
        "summary": summary,
        "error": error,
        "wall_clock_s": wall_s,
        "model_call_count": len(outer_timer.calls),
        "model_swap_count": swap_count,
        "vram_baseline_mib": vram.baseline_mib,
        "vram_peak_mib": vram.peak_mib,
        "vram_sample_count": len(vram.samples),
        "stuck_reasons": stuck_reasons,
        "state_transition_count": len(state_transitions),
        "state_sequence": [t["to"] for t in state_transitions],
        "tool_invocation_count": len(tool_invocations),
        "tool_denial_count": len(tool_denials),
        "ground_truth": ground_truth,
        "per_call": per_call,
    }
