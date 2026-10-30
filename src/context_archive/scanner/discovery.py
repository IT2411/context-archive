"""Repository root discovery and path validation utilities."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from context_archive.exceptions import ConfigError

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

DiscoverySource = Literal["ctxa_toml", "pyproject_toml", "git_dir", "fallback_dir"]


@dataclass(frozen=True)
class DiscoveredRepo:
    """Result of locating a repository root directory."""

    repo_root: Path
    source: DiscoverySource
    config_file: Path | None


def _has_tool_ctxa_section(pyproject_path: Path) -> bool:
    """Return True if pyproject.toml contains a [tool.ctxa] table."""
    if not pyproject_path.is_file():
        return False
    try:
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    tool_section = data.get("tool")
    return isinstance(tool_section, dict) and "ctxa" in tool_section


def discover_repo_root(start_path: Path | None = None) -> DiscoveredRepo:
    """Locate the repository root by walking upward from start_path.

    Precedence during upward search:
    1. Directory containing `.ctxa.toml`
    2. Directory containing `pyproject.toml` with `[tool.ctxa]`
    3. Directory containing `.git` (directory or worktree file)
    4. Fallback to the resolved starting directory itself.
    """
    target = Path.cwd() if start_path is None else start_path
    resolved = target.resolve()

    if not resolved.exists():
        raise ConfigError(f"Target path does not exist: '{target}'")
    if not resolved.is_dir():
        raise ConfigError(f"Target path is not a directory: '{target}'")

    candidates = [resolved, *resolved.parents]

    for directory in candidates:
        ctxa_toml = directory / ".ctxa.toml"
        if ctxa_toml.is_file():
            return DiscoveredRepo(
                repo_root=directory,
                source="ctxa_toml",
                config_file=ctxa_toml,
            )

        pyproject_toml = directory / "pyproject.toml"
        if _has_tool_ctxa_section(pyproject_toml):
            return DiscoveredRepo(
                repo_root=directory,
                source="pyproject_toml",
                config_file=pyproject_toml,
            )

        git_marker = directory / ".git"
        if git_marker.exists():
            return DiscoveredRepo(
                repo_root=directory,
                source="git_dir",
                config_file=None,
            )

    return DiscoveredRepo(
        repo_root=resolved,
        source="fallback_dir",
        config_file=None,
    )
