"""Attack 34 (executable substitution): a same-named pytest.py/ruff.py/
mypy.py file inside the sandboxed project must never shadow the real
installed tool via python -m's current-directory sys.path injection.
"""
from agent_platform.events import EventLog
from agent_platform.security.enums import Role, SessionMode
from agent_platform.security.permission import PermissionEvaluator
from agent_platform.security.sandbox import FilesystemSandbox
from agent_platform.tools.gateway import ToolGateway
from agent_platform.tools.registry import build_default_registry


def _workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    proj = root / "MyProj"
    proj.mkdir()
    return proj


def test_malicious_pytest_module_in_project_root_does_not_shadow_the_real_package(tmp_path):
    proj = _workspace(tmp_path)
    (proj / "pytest.py").write_text(
        "import sys\n"
        "with open('PWNED.txt', 'w') as f:\n"
        "    f.write('executable substitution succeeded')\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    (proj / "test_real.py").write_text("def test_x():\n    assert 1 == 1\n", encoding="utf-8")

    sandbox = FilesystemSandbox(proj.parent)
    evaluator = PermissionEvaluator(sandbox)
    gateway = ToolGateway(build_default_registry(), evaluator, EventLog())
    obs = gateway.invoke(role=Role.CODER, tool_name="test.run", arguments={},
                          session_mode=SessionMode.AUTO, project_root=proj.resolve())

    assert not (proj / "PWNED.txt").exists(), "malicious pytest.py was imported and executed"
    assert obs.status == "ok"
    assert obs.result["passed"] is True  # the REAL pytest ran test_real.py and it passed
