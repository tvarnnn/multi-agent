"""The 10-task Phase 8 benchmark dataset. Each task is a starting
filesystem state plus a natural-language request handed to the real
orchestrator; ground truth is established independently by the harness
(never by the model, never by whatever acceptance_criteria the Planner
happens to write), via a dedicated pytest file the harness authors and
runs itself after the orchestrator finishes, regardless of what the
orchestrator's own outcome was.

Tasks 6 and 7 are deliberately ambiguous / under-specified. They have no
objectively-correct code outcome, so ground_truth is None for them - they
are excluded from Reviewer false-positive/negative scoring and instead
feed the clarification-frequency and AWAITING_USER_INPUT-rate metrics.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


@dataclass(frozen=True)
class GroundTruthResult:
    applicable: bool
    passed: Optional[bool]
    detail: str


@dataclass(frozen=True)
class BenchmarkTask:
    task_id: str
    category: str
    description: str
    user_request: str
    starting_files: dict = field(default_factory=dict)
    check: Callable[[Path], GroundTruthResult] = None


def _run_hidden_pytest(project_root: Path, hidden_filename: str, hidden_content: str) -> GroundTruthResult:
    (project_root / hidden_filename).write_text(hidden_content, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-P", "-m", "pytest", hidden_filename, "-q"],
        cwd=project_root, capture_output=True, text=True, timeout=60,
    )
    passed = result.returncode == 0
    detail = f"hidden pytest exit={result.returncode}\n{result.stdout[-2000:]}\n{result.stderr[-500:]}"
    return GroundTruthResult(applicable=True, passed=passed, detail=detail)


def _check_task_1(project_root: Path) -> GroundTruthResult:
    return _run_hidden_pytest(
        project_root, "hidden_test_calc.py",
        "from calc import add\n\n\ndef test_add_hidden():\n"
        "    assert add(2, 3) == 5\n    assert add(-1, 1) == 0\n",
    )


def _check_task_2(project_root: Path) -> GroundTruthResult:
    return _run_hidden_pytest(
        project_root, "hidden_test_calc2.py",
        "from calc2 import subtract\n\n\ndef test_subtract_hidden():\n"
        "    assert subtract(10, 4) == 6\n    assert subtract(0, 0) == 0\n",
    )


def _check_task_3(project_root: Path) -> GroundTruthResult:
    return _run_hidden_pytest(
        project_root, "hidden_test_shapes.py",
        "from shapes import Rectangle\nfrom geometry_utils import area\n\n\n"
        "def test_area_hidden():\n    r = Rectangle(3, 4)\n    assert area(r) == 12\n",
    )


def _check_task_4(project_root: Path) -> GroundTruthResult:
    return _run_hidden_pytest(
        project_root, "hidden_test_config_reader.py",
        "import pytest\nfrom config_reader import get_setting\n\n\n"
        "def test_get_setting_present_hidden():\n    assert get_setting({'a': '1'}, 'a') == '1'\n\n\n"
        "def test_get_setting_missing_hidden():\n    with pytest.raises(KeyError):\n"
        "        get_setting({'a': '1'}, 'b')\n",
    )


def _check_task_5(project_root: Path) -> GroundTruthResult:
    original = "def is_even(n):\n    return n % 2 == 0\n"
    current = (project_root / "math_utils.py").read_text(encoding="utf-8") if (project_root / "math_utils.py").exists() else ""
    if current != original:
        return GroundTruthResult(applicable=True, passed=False,
                                  detail="math_utils.py was modified; task required leaving it unchanged")
    test_files = [p for p in project_root.glob("test_*.py")] + [p for p in project_root.glob("*_test.py")]
    references_is_even = any("is_even" in p.read_text(encoding="utf-8") for p in test_files)
    if not references_is_even:
        return GroundTruthResult(applicable=True, passed=False, detail="no test file references is_even")
    result = subprocess.run(
        [sys.executable, "-P", "-m", "pytest", "-q"],
        cwd=project_root, capture_output=True, text=True, timeout=60,
    )
    passed = result.returncode == 0
    return GroundTruthResult(applicable=True, passed=passed,
                              detail=f"math_utils.py unchanged; test suite exit={result.returncode}\n{result.stdout[-1000:]}")


def _check_not_applicable(project_root: Path) -> GroundTruthResult:
    return GroundTruthResult(applicable=False, passed=None,
                              detail="task is deliberately ambiguous - no objectively-correct code outcome")


def _check_task_8(project_root: Path) -> GroundTruthResult:
    return _run_hidden_pytest(
        project_root, "hidden_test_pricing.py",
        "from pricing import apply_discount\n\n\ndef test_apply_discount_hidden():\n"
        "    assert apply_discount(200, 25) == 150\n    assert apply_discount(50, 0) == 50\n",
    )


def _check_task_9(project_root: Path) -> GroundTruthResult:
    functional = _run_hidden_pytest(
        project_root, "hidden_test_file_reader.py",
        "from pathlib import Path\nfrom file_reader import read_user_file\n\n\n"
        "def test_read_user_file_hidden(tmp_path):\n"
        "    p = tmp_path / 'sample.txt'\n    p.write_text('hello world')\n"
        "    assert read_user_file(str(p)) == 'hello world'\n",
    )
    src = project_root / "file_reader.py"
    text = src.read_text(encoding="utf-8") if src.exists() else ""
    hardened = any(marker in text for marker in ("realpath", "resolve(", "os.path.abspath", "..", "commonpath"))
    detail = functional.detail + f"\nsecurity_hardening_present={hardened} (source-text heuristic, not gating)"
    return GroundTruthResult(applicable=True, passed=functional.passed, detail=detail)


def _check_task_10(project_root: Path) -> GroundTruthResult:
    return _run_hidden_pytest(
        project_root, "hidden_test_strings_util.py",
        "from strings_util import reverse_string\n\n\ndef test_reverse_string_hidden():\n"
        "    assert reverse_string('hello') == 'olleh'\n    assert reverse_string('') == ''\n",
    )


TASKS: tuple[BenchmarkTask, ...] = (
    BenchmarkTask(
        task_id="task01_simple_feature", category="simple_feature",
        description="Single-file greenfield function with a test.",
        user_request=("Create a Python module calc.py with a function add(a, b) that returns the sum "
                       "of a and b. Include a test file that verifies it."),
        starting_files={}, check=_check_task_1,
    ),
    BenchmarkTask(
        task_id="task02_bug_fix", category="bug_fix",
        description="Existing failing test; fix the implementation, not the test.",
        user_request=("The test in test_calc2.py is currently failing. Fix the bug in calc2.py so the "
                       "existing test passes, without modifying the test."),
        starting_files={
            "calc2.py": "def subtract(a, b):\n    return a + b\n",
            "test_calc2.py": "from calc2 import subtract\n\n\ndef test_subtract():\n    assert subtract(5, 3) == 2\n",
        },
        check=_check_task_2,
    ),
    BenchmarkTask(
        task_id="task03_multi_file", category="multi_file_implementation",
        description="Two new files with a cross-file import dependency.",
        user_request=("Create a shapes.py module with a Rectangle class that has width and height "
                       "attributes, and a separate geometry_utils.py module with a function area(rectangle) "
                       "that returns rectangle.width * rectangle.height by importing Rectangle from shapes.py. "
                       "Include tests."),
        starting_files={}, check=_check_task_3,
    ),
    BenchmarkTask(
        task_id="task04_api_integration", category="api_integration",
        description="Local dict-backed 'config API' integration with required error handling.",
        user_request=("Create a config_reader.py module with a function get_setting(config: dict, key: str) "
                       "-> str that returns config[key] if present, and raises a KeyError with a clear "
                       "message if the key is missing. Include tests covering both the present and missing "
                       "key cases."),
        starting_files={}, check=_check_task_4,
    ),
    BenchmarkTask(
        task_id="task05_test_creation", category="test_creation",
        description="Untested existing function; write tests without touching the implementation.",
        user_request="Write a test file for the existing is_even() function in math_utils.py. Do not modify math_utils.py.",
        starting_files={"math_utils.py": "def is_even(n):\n    return n % 2 == 0\n"},
        check=_check_task_5,
    ),
    BenchmarkTask(
        task_id="task06_ambiguous_requirement", category="ambiguous_requirement",
        description="Maximally vague request with no anchoring context. No objectively-correct outcome.",
        user_request="Make the code better.",
        starting_files={}, check=_check_not_applicable,
    ),
    BenchmarkTask(
        task_id="task07_clarification_required", category="clarification_required",
        description="Underspecified security-relevant request designed to require a genuine clarifying question.",
        user_request="Add authentication to the login function in login.py.",
        starting_files={"login.py": "def login(username, password):\n    pass\n"},
        check=_check_not_applicable,
    ),
    BenchmarkTask(
        task_id="task08_seeded_defect", category="seeded_defect",
        description="Subtle seeded arithmetic bug (wrong divisor) with an existing failing test.",
        user_request=("The test in test_pricing.py is failing. Fix the bug in pricing.py so it passes, "
                       "without modifying the test."),
        starting_files={
            "pricing.py": ("def apply_discount(price, discount_percent):\n"
                            "    return price - (price * discount_percent / 10)\n"),
            "test_pricing.py": ("from pricing import apply_discount\n\n\ndef test_apply_discount():\n"
                                 "    assert apply_discount(100, 10) == 90\n"),
        },
        check=_check_task_8,
    ),
    BenchmarkTask(
        task_id="task09_security_sensitive", category="security_sensitive",
        description="File-read-by-user-supplied-path request; tests whether Coder/Reviewer surface the path-traversal risk.",
        user_request=("Create a file_reader.py module with a function read_user_file(filename: str) -> str "
                       "that reads and returns the contents of a file specified by the given filename, for "
                       "use in a small internal tool. Include a test using a temporary file."),
        starting_files={}, check=_check_task_9,
    ),
    BenchmarkTask(
        task_id="task10_mcp_context", category="mcp_or_context_task",
        description="Small self-contained utility function; used to measure MCP/context-retrieval usage during a real run.",
        user_request="Implement a reverse_string(s: str) -> str function in strings_util.py that returns the input string reversed, and include a test.",
        starting_files={}, check=_check_task_10,
    ),
)
