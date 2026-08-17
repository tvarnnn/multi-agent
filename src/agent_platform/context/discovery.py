"""Discovery primitives, each reusing an existing gateway-mediated tool
call rather than any new filesystem/git capability. walk_project_tree
calls filesystem.list repeatedly (once per directory) - the exact same
tool a model could call directly - never anything with broader access.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

_SKIP_DIR_NAMES = {".git", "__pycache__", ".pytest_cache", ".venv", "node_modules"}
_TEST_PREFIX = "test_"
_CONFIG_NAMES = {
    "pyproject.toml", "setup.py", "setup.cfg", "tox.ini", "mypy.ini",
    ".flake8", "pytest.ini", "package.json",
}
_DOC_SUFFIXES = (".md", ".rst")
_DOC_NAME_PREFIXES = ("readme", "changelog", "contributing")
_IMPORT_RE = re.compile(r"^\s*(?:from\s+([\w\.]+)\s+import|import\s+([\w\.]+))", re.MULTILINE)


def parse_changed_files(status_output: str) -> tuple:
    paths = []
    for line in status_output.splitlines():
        if not line.strip():
            continue
        candidate = line[3:].strip() if len(line) > 3 else line.strip()
        if " -> " in candidate:
            candidate = candidate.split(" -> ")[-1].strip()
        if candidate:
            paths.append(candidate)
    return tuple(paths)


def classify_file(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    lower = name.lower()
    if lower.startswith(_TEST_PREFIX) and lower.endswith(".py"):
        return "test"
    if name in _CONFIG_NAMES or lower.startswith("requirements"):
        return "config"
    if lower.endswith(_DOC_SUFFIXES) or lower.split(".")[0] in _DOC_NAME_PREFIXES:
        return "documentation"
    return "other"


def extract_imports(content: str) -> list:
    names = []
    for match in _IMPORT_RE.finditer(content):
        name = match.group(1) or match.group(2)
        if name:
            names.append(name.split(".")[0])
    return names


def resolve_import_to_path(import_name: str, tree: list) -> Optional[str]:
    for path in tree:
        if path == f"{import_name}.py" or path.endswith(f"/{import_name}.py"):
            return path
        if path.endswith(f"/{import_name}/__init__.py") or path == f"{import_name}/__init__.py":
            return path
    return None


def walk_project_tree(gateway, role, session_mode, project_root, max_depth: int) -> list:
    results: list = []
    _walk(gateway, role, session_mode, project_root, "", max_depth, results)
    return results


def _walk(gateway, role, session_mode, project_root, rel_dir: str, remaining_depth: int, results: list) -> None:
    if remaining_depth < 0:
        return
    list_path = rel_dir if rel_dir else "."
    obs = gateway.invoke(role=role, tool_name="filesystem.list", arguments={"path": list_path},
                          session_mode=session_mode, project_root=project_root)
    if obs.status != "ok":
        return
    for name in obs.result["entries"]:
        if name in _SKIP_DIR_NAMES or name.endswith(".egg-info"):
            continue
        rel_path = f"{rel_dir}/{name}" if rel_dir else name
        full = Path(project_root) / rel_path
        if full.is_dir():
            _walk(gateway, role, session_mode, project_root, rel_path, remaining_depth - 1, results)
        else:
            results.append(rel_path)
