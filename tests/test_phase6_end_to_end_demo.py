"""The Phase 6 controlled end-to-end demonstration: Planner -> context
retrieval -> Coder -> tool gateway -> deterministic validation ->
Reviewer -> completion, exercising the review/fix loop along the way.
Everything is real (sandbox, gateway, real pytest execution via
test.run) except the model calls, which are scripted for
reproducibility - Phase 2 already separately proved real Ollama
integration with real measurements; re-proving that here would only add
non-determinism and slowness to what this test needs to show, which is
that the whole control plane is correctly wired together.
"""
from agent_platform.events import EventLog
from agent_platform.orchestrator.context_aware_provider import ContextAwareModelProvider
from agent_platform.orchestrator.core import Orchestrator, State
from agent_platform.orchestrator.fake_model import FakeModelProvider
from agent_platform.orchestrator.validation import TestRunValidator
from agent_platform.security.enums import Role, SessionMode
from agent_platform.security.permission import PermissionEvaluator
from agent_platform.security.sandbox import FilesystemSandbox
from agent_platform.spec.versioning import SpecStore
from agent_platform.tools.gateway import ToolGateway
from agent_platform.tools.registry import build_default_registry


def test_phase6_controlled_end_to_end_demo_with_review_fix_loop(tmp_path, capsys):
    workspace = tmp_path / "Projects"
    workspace.mkdir()
    project = workspace / "HealthCheckDemo"
    project.mkdir()

    sandbox = FilesystemSandbox(workspace)
    evaluator = PermissionEvaluator(sandbox)
    event_log = EventLog()
    gateway = ToolGateway(build_default_registry(), evaluator, event_log)

    # Attempt 1 is deliberately wrong (health_check() returns False) so
    # the demo exercises REJECT -> STRUCTURED_FEEDBACK -> IMPLEMENT_FIX,
    # not just the happy path.
    fake_model = FakeModelProvider(
        planner_responses=[{
            "kind": "spec",
            "goals": ["Add a health_check() function that reports the service is healthy"],
            "constraints": ["Keep it minimal"],
            "acceptance_criteria": ["file:health.py", "file:test_health.py"],
        }],
        coder_responses=[
            {
                "status": "completed", "spec_version_label": "demo-task-v1",
                "summary": "Added health_check(), returns False by mistake",
                "file_writes": [
                    {"path": "health.py", "content": "def health_check():\n    return False\n"},
                    {"path": "test_health.py",
                     "content": "from health import health_check\n\n\ndef test_health_check():\n"
                                "    assert health_check() is True\n"},
                ],
            },
            {
                "status": "completed", "spec_version_label": "demo-task-v1",
                "summary": "Fixed health_check() to return True as required",
                "file_writes": [
                    {"path": "health.py", "content": "def health_check():\n    return True\n"},
                    {"path": "test_health.py",
                     "content": "from health import health_check\n\n\ndef test_health_check():\n"
                                "    assert health_check() is True\n"},
                ],
            },
        ],
        reviewer_responses=[
            {
                "spec_version_label": "demo-task-v1", "decision": "REJECT",
                "requirements_met": False, "security_ok": True, "validation_ok": True,
                "issues": [{"severity": "high", "file": "health.py",
                            "description": "health_check() returns False, contradicting its own test",
                            "required_fix": "return True"}],
            },
            {
                "spec_version_label": "demo-task-v1", "decision": "APPROVE",
                "requirements_met": True, "security_ok": True, "validation_ok": True, "issues": [],
            },
        ],
    )
    model = ContextAwareModelProvider(fake_model, gateway=gateway, session_mode=SessionMode.AUTO,
                                       project_root=project.resolve())
    spec_store = SpecStore()
    validator = TestRunValidator(gateway, Role.REVIEWER, SessionMode.AUTO)
    orchestrator = Orchestrator(
        gateway=gateway, model=model, spec_store=spec_store, event_log=event_log,
        session_mode=SessionMode.AUTO, project_root=project.resolve(), validator=validator,
    )

    result = orchestrator.run("demo-task", "Add a health check function with a test for it.")

    transitions = [e.payload["to"] for e in event_log.internal_stream() if e.event_type.name == "STATE_TRANSITION"]
    print("\n=== PHASE 6 DEMO: state transitions ===")
    print(" -> ".join(transitions))
    print("=== user-visible progress ===")
    for event in event_log.user_stream():
        print(f"  {event.payload.get('text', event.payload)}")
    print(f"=== final state: {result.final_state} ===")
    print(f"=== summary: {result.summary} ===")

    assert result.final_state == State.COMPLETE
    assert "REVIEW" in transitions
    assert "FEEDBACK" in transitions and "IMPLEMENT_FIX" in transitions  # the fix loop was exercised
    assert (project / "health.py").read_text(encoding="utf-8") == "def health_check():\n    return True\n"

    # Deterministic validation actually ran real pytest against the real
    # written files - not a stub.
    real_validation = validator.validate(project.resolve(), spec_store.latest("demo-task"))
    assert real_validation.passed
