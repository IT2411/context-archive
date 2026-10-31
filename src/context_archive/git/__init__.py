"""git subsystem for context-archive."""

from __future__ import annotations

from context_archive.git.state import (
    GitState,
    compute_repository_id,
    extract_git_state,
    sanitize_remote_url,
)

__all__ = [
    "GitState",
    "compute_repository_id",
    "extract_git_state",
    "sanitize_remote_url",
]
