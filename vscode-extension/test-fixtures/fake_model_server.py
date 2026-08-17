"""Standalone launcher for the extension's own automated test suite
(@vscode/test-electron): a REAL Agent Platform backend process, identical
in every way to `python -m agent_platform.server` except the model
provider is a scripted FakeModelProvider instead of a real Ollama
connection - the same "real backend, fake model" pattern every
deterministic test in the Python suite already uses. Not shipped with the
extension; lives only under test-fixtures/.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agent_platform.orchestrator.fake_model import FakeModelProvider  # noqa: E402
from agent_platform.server import build_server, startup_line  # noqa: E402


def _plan_dict(objective="Build the widget"):
    return {
        "kind": "plan", "objective": objective, "requirements": ["req1"],
        "existing_context": [], "proposed_architecture": "single module",
        "files_to_create": ["widget.py"], "files_to_modify": [], "dependencies": [],
        "implementation_steps": ["step1"], "validation_strategy": ["test1"],
        "risks": [], "unknowns": [], "acceptance_criteria": ["file:widget.py"],
    }


def _review_dict():
    return {"comments": [], "missing_requirements": [], "security_concerns": [], "unnecessary_complexity": []}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--sandbox-root", default=None)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()

    model = FakeModelProvider(
        chat_responses=[{"message": "Hello from the test backend!"} for _ in range(20)],
        plan_mode_responses=[_plan_dict() for _ in range(20)],
        review_plan_responses=[_review_dict() for _ in range(20)],
    )
    server, sock, token = build_server(
        Path(args.workspace_root).resolve(), model, port=args.port,
        workspace_root=Path(args.sandbox_root).resolve() if args.sandbox_root else None,
    )
    assigned_port = sock.getsockname()[1]
    print(startup_line(assigned_port, token), flush=True)
    server.run(sockets=[sock])


if __name__ == "__main__":
    main()
