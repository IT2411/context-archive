"""Unit tests for Git state extraction, URL credential sanitization, and repository IDs."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from context_archive.git.state import (
    compute_repository_id,
    extract_git_state,
    sanitize_remote_url,
)

if TYPE_CHECKING:
    from pathlib import Path


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.unit
def test_sanitize_remote_url_strips_embedded_credentials() -> None:
    """Verify HTTP(S) tokens and user:pass credentials are removed from remote URLs."""
    assert (
        sanitize_remote_url("https://ghp_secretToken123@github.com/org/repo.git")
        == "https://github.com/org/repo.git"
    )
    assert (
        sanitize_remote_url("https://user:super_secret@gitlab.com/team/service.git")
        == "https://gitlab.com/team/service.git"
    )
    assert sanitize_remote_url("git@github.com:org/repo.git") == "git@github.com:org/repo.git"
    assert sanitize_remote_url(None) is None
    assert sanitize_remote_url("   ") is None


@pytest.mark.unit
def test_git_matrix_non_git_unborn_clean_dirty_and_detached(tmp_path: Path) -> None:
    """Test Git state across non-Git, 0-commit, clean, dirty, and detached HEAD."""
    # 1. Non-Git directory
    non_git = tmp_path / "plain_dir"
    non_git.mkdir()
    state_non_git = extract_git_state(non_git)
    assert state_non_git.is_git_repo is False
    assert state_non_git.commit_sha is None
    assert state_non_git.branch is None

    # 2. Newborn Git repo with 0 commits
    repo = tmp_path / "git_repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _git(
        repo,
        "remote",
        "add",
        "origin",
        "https://token_abc@github.com/org/context-archive.git",
    )

    state_unborn = extract_git_state(repo)
    assert state_unborn.is_git_repo is True
    assert state_unborn.commit_sha is None
    assert state_unborn.branch == "main"
    assert state_unborn.remote_url == "https://github.com/org/context-archive.git"

    # 3. Clean committed working tree
    (repo / "module.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "module.py")
    _git(repo, "commit", "-m", "Initial commit")

    state_clean = extract_git_state(repo)
    assert state_clean.is_git_repo is True
    assert state_clean.commit_sha is not None
    assert len(state_clean.commit_sha) == 40
    assert state_clean.branch == "main"
    assert state_clean.is_dirty is False
    assert state_clean.untracked_count == 0

    first_commit = state_clean.commit_sha
    repo_id_1 = compute_repository_id(repo)

    # 4. Dirty working tree with untracked and modified files
    (repo / "module.py").write_text("x = 2\n", encoding="utf-8")
    (repo / "untracked.py").write_text("y = 3\n", encoding="utf-8")
    state_dirty = extract_git_state(repo)
    assert state_dirty.is_dirty is True
    assert state_dirty.untracked_count == 1

    # 5. Second commit and detached HEAD
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "Second commit")
    _git(repo, "checkout", "--detach", first_commit)

    state_detached = extract_git_state(repo)
    assert state_detached.branch == "DETACHED_HEAD"
    assert state_detached.commit_sha == first_commit

    # Repository ID remains stable across commits because root commit is unchanged
    repo_id_2 = compute_repository_id(repo)
    assert repo_id_1 == repo_id_2
    assert repo_id_1.startswith("repo:sha256:")
