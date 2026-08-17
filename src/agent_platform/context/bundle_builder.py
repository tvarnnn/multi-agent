"""The core bounded, deterministic, priority-ordered context retrieval
engine. Every file read and every git status check goes through the same
ToolGateway every other tool call uses - context retrieval has no
privileged path to the filesystem or git, and everything it does is
logged exactly like any other tool call made on a role's behalf.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .bundle import ContextBundle, ContextFile
from .discovery import classify_file, extract_imports, parse_changed_files, resolve_import_to_path, walk_project_tree
from .limits import ContextLimits, DEFAULT_LIMITS, estimate_tokens
from .staleness import ContextCache

_PRIORITY = {"referenced": 0, "changed": 1, "dependency": 2, "test": 3,
             "config": 4, "documentation": 5, "tree": 6}


def _read_file(gateway, role, session_mode, project_root, path, limits):
    obs = gateway.invoke(role=role, tool_name="filesystem.read", arguments={"path": path},
                          session_mode=session_mode, project_root=project_root)
    if obs.status != "ok":
        return None, False
    content = obs.result["content"]
    truncated = False
    encoded = content.encode("utf-8")
    if len(encoded) > limits.max_individual_file_bytes:
        content = encoded[:limits.max_individual_file_bytes].decode("utf-8", errors="ignore")
        truncated = True
    return content, truncated


def build_context_bundle(*, gateway, role, session_mode, project_root: Path,
                          reference_hints: tuple, include_git_changes: bool = True,
                          limits: ContextLimits = DEFAULT_LIMITS,
                          cache: Optional[ContextCache] = None) -> ContextBundle:
    tree = walk_project_tree(gateway, role, session_mode, project_root, limits.max_retrieval_depth)

    changed_files: tuple = ()
    if include_git_changes:
        status_obs = gateway.invoke(role=role, tool_name="git.status", arguments={},
                                     session_mode=session_mode, project_root=project_root)
        if status_obs.status == "ok" and status_obs.result.get("scoped"):
            changed_files = parse_changed_files(status_obs.result["output"])

    hints_lower = [h.lower() for h in reference_hints if h]
    referenced = [p for p in tree if any(Path(p).name.lower() in h or p.lower() in h for h in hints_lower)]
    changed_in_tree = [p for p in changed_files if p in tree]

    candidates: dict = {}
    for p in referenced:
        candidates[p] = "referenced"
    for p in changed_in_tree:
        candidates.setdefault(p, "changed")

    seed_paths = sorted(candidates.keys())
    dependency_paths = []
    for seed in seed_paths:
        content, _ = _read_file(gateway, role, session_mode, project_root, seed, limits)
        if content is None:
            continue
        for name in extract_imports(content):
            resolved = resolve_import_to_path(name, tree)
            if resolved and resolved not in candidates:
                dependency_paths.append(resolved)
    for p in sorted(set(dependency_paths)):
        candidates.setdefault(p, "dependency")

    seed_stems = {Path(p).stem for p in seed_paths}
    for p in tree:
        if classify_file(p) == "test":
            stem = Path(p).stem
            target_stem = stem[len("test_"):] if stem.startswith("test_") else stem
            if target_stem in seed_stems:
                candidates.setdefault(p, "test")

    for p in tree:
        category = classify_file(p)
        if category in ("config", "documentation"):
            candidates.setdefault(p, category)

    if not referenced:
        candidates.setdefault("__tree__", "tree")

    ordered = sorted(candidates.items(), key=lambda item: (_PRIORITY[item[1]], item[0]))

    files: list = []
    excluded: list = []
    stale: list = []
    total_bytes = 0
    for path, category in ordered:
        if len(files) >= limits.max_files:
            excluded.append(path)
            continue
        truncated_flag = False
        if path == "__tree__":
            content = "\n".join(sorted(tree))
        else:
            content, truncated_flag = _read_file(gateway, role, session_mode, project_root, path, limits)
            if content is None:
                excluded.append(path)
                continue
        encoded_len = len(content.encode("utf-8"))
        if total_bytes + encoded_len > limits.max_total_bytes:
            excluded.append(path)
            continue
        prospective = estimate_tokens("\n".join(f.content for f in files) + content)
        if prospective > limits.max_tokens_estimate:
            excluded.append(path)
            continue
        if cache is not None and path != "__tree__":
            if cache.check_and_update(path, content):
                stale.append(path)
        total_bytes += encoded_len
        files.append(ContextFile(path=path, content=content, category=category, truncated=truncated_flag))

    return ContextBundle(
        role=role.value, files=tuple(files), changed_files=changed_files,
        excluded_paths=tuple(excluded), stale_paths=tuple(stale),
        total_bytes=total_bytes, limit_exceeded=bool(excluded),
    )
