"""Manual CLI convenience for a real, live end-to-end run: real Ollama
models, real filesystem writes, the real Plan -> Code -> Test -> Review
state machine - no VS Code client, no HTTP backend, no fakes anywhere.

This is not part of the installed package and has no test coverage of its
own; it's a thin wrapper around the same construction
tests/test_ollama_integration.py::test_full_orchestrator_run_with_real_models_reaches_a_terminal_state
uses, pointed at a real directory you choose instead of a throwaway tmp_path,
so you can inspect what the Coder actually wrote afterward.

Requires a running Ollama with the three models below (or pass your own via
--planner-model/--coder-model/--reviewer-model). Run `ollama list` first if
unsure what's pulled.

Usage:
    python scripts/live_run.py --workspace-root "C:\\Users\\you\\Scratch" \\
        --project hello-world-test \\
        --request "Write a single Python file main.py with a function add(a, b) that returns a + b."

Add --test-run to require the project's real pytest suite to pass (via the
test.run tool) instead of only checking that acceptance-criteria files
exist. Leave --session-mode at the default AUTO for a run that can actually
reach COMPLETE: CONFIRMATION/MANUAL make writes come back as
"requires_confirmation" observations, and there is no interactive
resume path built yet to unblock them (see README's Status section) - the
Coder would just report BLOCKED.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent_platform.events import EventLog, EventType  # noqa: E402
from agent_platform.orchestrator.core import Orchestrator, State  # noqa: E402
from agent_platform.orchestrator.ollama_provider import OllamaModelProvider  # noqa: E402
from agent_platform.orchestrator.validation import (  # noqa: E402
    AcceptanceCriteriaFileValidator,
    CompositeValidator,
    TestRunValidator,
)
from agent_platform.security.enums import Role, SessionMode  # noqa: E402
from agent_platform.security.permission import PermissionEvaluator  # noqa: E402
from agent_platform.security.sandbox import FilesystemSandbox  # noqa: E402
from agent_platform.spec.versioning import SpecStore  # noqa: E402
from agent_platform.tools.gateway import ToolGateway  # noqa: E402
from agent_platform.tools.registry import build_default_registry  # noqa: E402

DEFAULT_PLANNER_MODEL = "phi4-reasoning:plus"
DEFAULT_CODER_MODEL = "qwen2.5-coder:14b"
DEFAULT_REVIEWER_MODEL = "phi4-reasoning:plus"


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace-root", required=True,
                         help="sandbox root (parent of --project); created if missing")
    parser.add_argument("--project", required=True,
                         help="project directory name under --workspace-root; created if missing")
    parser.add_argument("--request", required=True, help="the user request to hand the Planner")
    parser.add_argument("--spec-id", default="live-run", help="spec id for this run (default: live-run)")
    parser.add_argument("--session-mode", choices=["AUTO", "CONFIRMATION", "MANUAL"], default="AUTO")
    parser.add_argument("--planner-model", default=DEFAULT_PLANNER_MODEL)
    parser.add_argument("--coder-model", default=DEFAULT_CODER_MODEL)
    parser.add_argument("--reviewer-model", default=DEFAULT_REVIEWER_MODEL)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--max-output-retries", type=int, default=3)
    parser.add_argument("--max-clarification-rounds", type=int, default=2)
    parser.add_argument("--max-fix-iterations", type=int, default=2)
    parser.add_argument("--test-run", action="store_true",
                         help="also require the project's real pytest suite to pass via test.run, "
                              "not just acceptance-criteria file existence")
    return parser.parse_args(argv)


def build_validator(gateway: ToolGateway, session_mode: SessionMode, use_test_run: bool):
    if not use_test_run:
        return AcceptanceCriteriaFileValidator()
    return CompositeValidator((
        AcceptanceCriteriaFileValidator(),
        TestRunValidator(gateway, Role.REVIEWER, session_mode),
    ))


def print_events(event_log: EventLog) -> None:
    print("\n--- internal trace ---")
    for event in event_log.internal_stream():
        if event.event_type == EventType.STATE_TRANSITION:
            print(f"  [state] {event.payload['from']} -> {event.payload['to']}")
        else:
            print(f"  [{event.event_type.name}] {event.payload}")
    print("\n--- user-facing messages ---")
    for event in event_log.user_stream():
        print(f"  {event.payload}")


def main(argv=None) -> int:
    args = parse_args(argv)
    session_mode = SessionMode[args.session_mode]

    workspace_root = Path(args.workspace_root).resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    project_root = workspace_root / args.project
    project_root.mkdir(parents=True, exist_ok=True)

    sandbox = FilesystemSandbox(workspace_root)
    evaluator = PermissionEvaluator(sandbox)
    event_log = EventLog()
    gateway = ToolGateway(build_default_registry(), evaluator, event_log)

    provider = OllamaModelProvider(
        planner_model=args.planner_model, coder_model=args.coder_model,
        reviewer_model=args.reviewer_model, timeout_seconds=args.timeout_seconds,
    )

    orchestrator = Orchestrator(
        gateway=gateway, model=provider, spec_store=SpecStore(), event_log=event_log,
        session_mode=session_mode, project_root=project_root,
        validator=build_validator(gateway, session_mode, args.test_run),
        max_output_retries=args.max_output_retries,
        max_clarification_rounds=args.max_clarification_rounds,
        max_fix_iterations=args.max_fix_iterations,
    )

    print(f"workspace_root = {workspace_root}")
    print(f"project_root   = {project_root}")
    print(f"models         = planner={args.planner_model} coder={args.coder_model} reviewer={args.reviewer_model}")
    print(f"session_mode   = {session_mode.value}")
    print(f"request        = {args.request!r}\n")

    result = orchestrator.run(args.spec_id, args.request)

    print(f"\nfinal_state = {result.final_state}")
    print(f"summary     = {result.summary}")

    print_events(event_log)

    print(f"\ntelemetry calls = {len(provider.telemetry_log)}")
    for i, entry in enumerate(provider.telemetry_log):
        print(f"  call {i}: load={entry.load_duration_ns / 1e9:.2f}s eval={entry.eval_duration_ns / 1e9:.2f}s "
              f"prompt_tokens={entry.prompt_eval_count} output_tokens={entry.eval_count}")

    return 0 if result.final_state == State.COMPLETE else 1


if __name__ == "__main__":
    raise SystemExit(main())
