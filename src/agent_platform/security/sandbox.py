"""Windows-aware filesystem sandbox.

Every path a tool wants to touch is authorized here before any I/O
happens. Deny-by-default: any ambiguity, resolution failure, or detected
reparse point anywhere in the path chain results in denial, never a
best-effort continuation. This module never does naive string-prefix
containment - see test_sibling_prefix_attack_is_denied for exactly why.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Optional

FILE_ATTRIBUTE_REPARSE_POINT = 0x400

_RESERVED_DEVICE_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class SandboxConfigurationError(Exception):
    """Raised when the sandbox itself cannot be safely constructed - e.g.
    the configured workspace root doesn't exist or is a reparse point."""


@dataclass(frozen=True)
class PathDecision:
    allowed: bool
    resolved_path: Optional[Path]
    reason: str

    @staticmethod
    def deny(reason: str) -> "PathDecision":
        return PathDecision(allowed=False, resolved_path=None, reason=reason)

    @staticmethod
    def allow(path: Path, reason: str = "authorized") -> "PathDecision":
        return PathDecision(allowed=True, resolved_path=path, reason=reason)


def _has_reserved_device_name(raw: str) -> bool:
    for part in PureWindowsPath(raw).parts:
        stem = part.split(".")[0].rstrip(" ").upper()
        if stem in _RESERVED_DEVICE_NAMES:
            return True
    return False


def _is_ambiguous_relative(raw: str) -> bool:
    """True for 'C:foo' (drive-relative) or '\\foo' (root-relative, no
    drive) - Windows resolves either using process state (current
    directory on that drive) this sandbox has no visibility into, so both
    are rejected rather than guessed at."""
    p = PureWindowsPath(raw)
    has_drive = p.drive != ""
    has_root = p.root != ""
    return has_drive != has_root


def _is_unc_or_device_path(raw: str) -> bool:
    stripped = raw.replace("/", "\\")
    return stripped.startswith("\\\\")


def _contains_reparse_point(path: Path, stop_at: Path) -> Optional[Path]:
    """Walk existing ancestors of `path` (checked *before* OS-level
    resolution has erased any reparse points from the chain) up to and
    including `stop_at`, and return the first one found to be a reparse
    point, or None. Deliberately does not follow symlinks when stat-ing -
    a reparse point must be visible as itself, not as its target."""
    current = path
    while True:
        try:
            st = os.stat(current, follow_symlinks=False)
        except (FileNotFoundError, OSError):
            pass
        else:
            if getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
                return current
        if current == stop_at:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


class FilesystemSandbox:
    def __init__(self, workspace_root: Path):
        raw = Path(workspace_root)
        # Check the *unresolved* path for reparse points first - resolve()
        # would silently dereference a junction/symlink before we ever get
        # a chance to see it, exactly like the escape it's checking for.
        reparse_hit = _contains_reparse_point(raw, stop_at=raw)
        if reparse_hit is not None:
            raise SandboxConfigurationError(
                f"workspace root itself is a reparse point: {reparse_hit}"
            )
        try:
            resolved_root = raw.resolve(strict=True)
        except OSError as exc:
            raise SandboxConfigurationError(
                f"workspace_root does not exist or cannot be resolved: {workspace_root}"
            ) from exc
        if not resolved_root.is_dir():
            raise SandboxConfigurationError(f"workspace_root is not a directory: {resolved_root}")
        self.workspace_root = resolved_root

    def authorize(self, requested: str, *, scope_root: Optional[Path] = None) -> PathDecision:
        if not requested or not requested.strip() or "\x00" in requested:
            return PathDecision.deny("empty or malformed path")

        if _is_unc_or_device_path(requested):
            return PathDecision.deny("UNC or device-namespace path rejected")

        if _is_ambiguous_relative(requested):
            return PathDecision.deny("drive-relative or root-relative path rejected (ambiguous)")

        if _has_reserved_device_name(requested):
            return PathDecision.deny("reserved Windows device name in path")

        base = scope_root if scope_root is not None else self.workspace_root
        try:
            base = Path(base).resolve(strict=False)
        except OSError:
            return PathDecision.deny("failed to resolve scope root")

        candidate = PureWindowsPath(requested)
        joined = Path(requested) if candidate.is_absolute() else base / requested

        reparse_hit = _contains_reparse_point(joined, stop_at=self.workspace_root)
        if reparse_hit is not None:
            return PathDecision.deny(f"reparse point detected at {reparse_hit}")

        try:
            resolved = joined.resolve(strict=False)
        except OSError:
            return PathDecision.deny("path resolution failed")

        try:
            relative_to_workspace = resolved.relative_to(self.workspace_root)
        except ValueError:
            return PathDecision.deny("path escapes workspace root")

        if scope_root is not None:
            try:
                resolved.relative_to(base)
            except ValueError:
                return PathDecision.deny("path escapes active project scope")

        if ".git" in {part.lower() for part in relative_to_workspace.parts}:
            return PathDecision.deny("direct access to .git internals is not permitted")

        return PathDecision.allow(resolved)

    def authorize_new_project(self, project_name: str) -> PathDecision:
        """Authorize creation of a brand-new project directly under the
        workspace root. Refuses if the name is unsafe, or if something
        already exists at that path - including as a reparse point, even
        one that would otherwise resolve back inside the workspace."""
        if not project_name or not project_name.strip():
            return PathDecision.deny("invalid project name")
        if any(c in project_name for c in '<>:"/\\|?*') or "\x00" in project_name:
            return PathDecision.deny("invalid project name")
        if project_name in (".", ".."):
            return PathDecision.deny("invalid project name")
        if _has_reserved_device_name(project_name):
            return PathDecision.deny("reserved Windows device name as project name")

        target = self.workspace_root / project_name
        try:
            st = os.stat(target, follow_symlinks=False)
        except FileNotFoundError:
            return PathDecision.allow(target)
        except OSError:
            return PathDecision.deny("failed to stat target project path")

        attrs = getattr(st, "st_file_attributes", 0)
        if attrs & FILE_ATTRIBUTE_REPARSE_POINT:
            return PathDecision.deny(
                "refusing to create project over an existing symlink/junction"
            )
        return PathDecision.deny("project already exists")
