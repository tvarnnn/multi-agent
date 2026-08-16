"""Real Ollama integration tests. Unlike every other test file in this
project, these hit the real, already-running local Ollama server and the
real GPU - not a fake transport. Kept in their own file so the rest of
the suite stays network-free; run this file with -s to see the printed
timing/telemetry output.
"""
import json
import time

import pytest

from agent_platform.events import EventLog
from agent_platform.orchestrator.core import Orchestrator, State
from agent_platform.orchestrator.gpu_telemetry import query_gpu_memory
from agent_platform.orchestrator.model_schemas import parse_planner_output
from agent_platform.orchestrator.ollama_provider import OllamaModelProvider
from agent_platform.orchestrator.validation import AcceptanceCriteriaFileValidator
from agent_platform.security.enums import SessionMode
from agent_platform.security.permission import PermissionEvaluator
from agent_platform.security.sandbox import FilesystemSandbox
from agent_platform.spec.versioning import SpecStore
from agent_platform.tools.gateway import ToolGateway
from agent_platform.tools.registry import build_default_registry

PLANNER_MODEL = "phi4-reasoning:plus"
CODER_MODEL = "qwen2.5-coder:14b"
REVIEWER_MODEL = "phi4-reasoning:plus"


def _counting_transport():
    from agent_platform.orchestrator.ollama_provider import default_http_post
    calls = []

    def wrapped(url, payload, timeout):
        calls.append({"model": payload.get("model"), "keep_alive": payload.get("keep_alive")})
        return default_http_post(url, payload, timeout)

    return wrapped, calls


def test_real_planner_call_produces_schema_valid_output():
    provider = OllamaModelProvider(planner_model=PLANNER_MODEL, coder_model=CODER_MODEL,
                                    reviewer_model=REVIEWER_MODEL, timeout_seconds=180.0)
    t0 = time.time()
    raw = provider.plan({"request": "Build a small FastAPI app that has one endpoint "
                                     "returning the current GPU utilization percentage."})
    elapsed = time.time() - t0
    parsed = parse_planner_output(raw)  # raises if the real model's output doesn't validate
    print(f"\n[planner] wall_clock={elapsed:.2f}s raw={json.dumps(raw)[:300]}")
    entry = provider.telemetry_log[0]
    print(f"[planner] load={entry.load_duration_ns/1e9:.2f}s "
          f"eval={entry.eval_duration_ns/1e9:.2f}s total={entry.total_duration_ns/1e9:.2f}s "
          f"prompt_tokens={entry.prompt_eval_count} output_tokens={entry.eval_count}")
    assert parsed is not None


def test_switching_planner_to_coder_triggers_real_unload_then_full_gpu_residency():
    transport, calls = _counting_transport()
    provider = OllamaModelProvider(planner_model=PLANNER_MODEL, coder_model=CODER_MODEL,
                                    reviewer_model=REVIEWER_MODEL, http_post=transport, timeout_seconds=180.0)
    provider.plan({"request": "Build a tiny health-check endpoint."})
    provider.code({"spec": SpecStore().create("t", goals=["g"], constraints=[],
                                               acceptance_criteria=["file:main.py"]),
                    "reviewer_feedback": None})
    unload_calls = [c for c in calls if c["keep_alive"] == 0]
    assert len(unload_calls) == 1
    assert unload_calls[0]["model"] == PLANNER_MODEL
    gpu = query_gpu_memory()
    print(f"\n[after coder load] gpu={gpu}")
    assert gpu is not None
    assert gpu["used_mib"] > 5000  # a 9.5GB model is resident


def test_reviewer_reuses_planner_model_without_unload():
    transport, calls = _counting_transport()
    provider = OllamaModelProvider(planner_model=PLANNER_MODEL, coder_model=CODER_MODEL,
                                    reviewer_model=REVIEWER_MODEL, http_post=transport, timeout_seconds=180.0)
    # coder is currently resident from the previous test; switch planner -> reviewer,
    # both phi4-reasoning:plus, and confirm no unload fires between them.
    provider.plan({"request": "Build a tiny health-check endpoint."})
    calls.clear()
    from agent_platform.orchestrator.model_schemas import CoderCompleted
    from agent_platform.orchestrator.validation import ValidationResult
    provider.review({
        "spec": SpecStore().create("t2", goals=["g"], constraints=[], acceptance_criteria=[]),
        "coder_output": CoderCompleted(spec_version_label="t2-v1", summary="s", file_writes=()),
        "validation_result": ValidationResult(passed=True, details=()),
    })
    assert len(calls) == 1  # only the review call itself, no intervening unload


def test_full_orchestrator_run_with_real_models_reaches_a_terminal_state(tmp_path):
    workspace = tmp_path / "Projects"
    workspace.mkdir()
    project = workspace / "GpuMonitor"
    project.mkdir()

    sandbox = FilesystemSandbox(workspace)
    evaluator = PermissionEvaluator(sandbox)
    event_log = EventLog()
    gateway = ToolGateway(build_default_registry(), evaluator, event_log)
    provider = OllamaModelProvider(planner_model=PLANNER_MODEL, coder_model=CODER_MODEL,
                                    reviewer_model=REVIEWER_MODEL, timeout_seconds=180.0)
    orchestrator = Orchestrator(
        gateway=gateway, model=provider, spec_store=SpecStore(), event_log=event_log,
        session_mode=SessionMode.AUTO, project_root=project.resolve(),
        validator=AcceptanceCriteriaFileValidator(),
        max_output_retries=3, max_clarification_rounds=2, max_fix_iterations=2,
    )
    t0 = time.time()
    result = orchestrator.run("gpu-monitor-task", "Write a single Python file called main.py "
                               "with one function `gpu_utilization()` that returns a hardcoded "
                               "float for now. Keep it minimal.")
    elapsed = time.time() - t0
    transitions = [e.payload["to"] for e in event_log.internal_stream() if e.event_type.name == "STATE_TRANSITION"]
    print(f"\n[full run] wall_clock={elapsed:.2f}s final_state={result.final_state} "
          f"transitions={transitions}")
    print(f"[full run] telemetry entries={len(provider.telemetry_log)}")
    for i, entry in enumerate(provider.telemetry_log):
        print(f"  call {i}: load={entry.load_duration_ns/1e9:.2f}s eval={entry.eval_duration_ns/1e9:.2f}s")
    assert result.final_state in (State.COMPLETE, State.ESCALATE_TO_USER)


def test_large_prompt_context_length_behavior():
    provider = OllamaModelProvider(planner_model=PLANNER_MODEL, coder_model=CODER_MODEL,
                                    reviewer_model=REVIEWER_MODEL, timeout_seconds=180.0)
    padding = "This is filler context to probe context-length behavior. " * 400  # ~24k chars
    raw = provider.plan({"request": f"{padding}\n\nBuild a tiny health-check endpoint."})
    entry = provider.telemetry_log[0]
    print(f"\n[large prompt] prompt_tokens={entry.prompt_eval_count} "
          f"output_tokens={entry.eval_count} response_keys={list(raw.keys())}")
    # No hard assertion on token count - the point is to observe and record
    # actual behavior (truncation vs. full ingestion vs. error), not assert
    # a specific number this test can't know in advance.
    assert isinstance(raw, dict)
