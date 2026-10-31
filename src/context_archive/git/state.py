"""Safe Git state extraction and deterministic repository ID generation."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from pathlib import Path

_CREDENTIAL_URL_RE = re.compile(r"^(https?://)([^/@]+@)(.+)$")


class GitState(BaseModel):
    """Immutable snapshot of repository Git state matching manifest.schema.json."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    is_git_repo: bool = Field(default=False)
    commit_sha: str | None = Field(default=None)
    branch: str | None = Field(default=None)
    is_dirty: bool = Field(default=False)
    untracked_count: int = Field(default=0, ge=0)
    remote_url: str | None = Field(default=None)


def sanitize_remote_url(raw_url: str | None) -> str | None:
    """Strip embedded username/password/token credentials from HTTP(S) remote URLs."""
    if not raw_url:
        return None
    cleaned = raw_url.strip()
    if not cleaned:
        return None
    return _CREDENTIAL_URL_RE.sub(r"\1\3", cleaned)


def _run_git(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str] | None:
    """Run a read-only git command safely without shell execution."""
    git_bin = shutil.which("git")
    if git_bin is None:
        return None
    try:
        return subprocess.run(  # noqa: S603
            [git_bin, *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _is_self_managed_context_path(rel_path: str) -> bool:
    """Return True if a Git status path belongs to ctxa's own output artifacts."""
    cleaned = rel_path.strip().strip('"')
    return (
        cleaned == "PROJECT_CONTEXT.md"
        or cleaned == "PROJECT_CONTEXT.md.bak"
        or cleaned == ".context"
        or cleaned.startswith(".context/")
    )


def extract_git_state(repo_root: Path) -> GitState:
    """Extract current Git commit, branch, dirty working tree status, and sanitized remote."""
    status_proc = _run_git(
        repo_root,
        ["status", "--porcelain=v2", "--branch", "--untracked-files=all"],
    )
    if status_proc is None or status_proc.returncode != 0:
        return GitState(is_git_repo=False)

    commit_sha: str | None = None
    branch: str | None = None
    staged_or_unstaged = 0
    untracked = 0

    for raw_line in status_proc.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("# branch.oid "):
            oid = line[len("# branch.oid ") :].strip()
            if oid and oid != "(initial)":
                commit_sha = oid
        elif line.startswith("# branch.head "):
            head = line[len("# branch.head ") :].strip()
            branch = "DETACHED_HEAD" if head == "(detached)" else head
        elif line.startswith(("1 ", "2 ", "u ")):
            path_part = line.split("\t")[0].split(" ", 8)[-1]
            if not _is_self_managed_context_path(path_part):
                staged_or_unstaged += 1
        elif line.startswith("? "):
            path_part = line[2:].strip()
            if not _is_self_managed_context_path(path_part):
                untracked += 1

    remote_proc = _run_git(repo_root, ["config", "--get", "remote.origin.url"])
    remote_url: str | None = None
    if remote_proc is not None and remote_proc.returncode == 0:
        remote_url = sanitize_remote_url(remote_proc.stdout)

    is_dirty = (staged_or_unstaged + untracked) > 0
    return GitState(
        is_git_repo=True,
        commit_sha=commit_sha,
        branch=branch,
        is_dirty=is_dirty,
        untracked_count=untracked,
        remote_url=remote_url,
    )


def compute_repository_id(repo_root: Path, *, project_name: str | None = None) -> str:
    """Compute a deterministic repository_id (`repo:sha256:<hex>`).

    Precedence for seed identity:
    1. First (root) Git commit SHA (`git rev-list --max-parents=0 HEAD`)
    2. Sanitized Git remote origin URL + project_name
    3. Normalized project_name or directory name
    """
    resolved = repo_root.resolve()
    seed: str | None = None

    root_commit_proc = _run_git(resolved, ["rev-list", "--max-parents=0", "HEAD"])
    if root_commit_proc is not None and root_commit_proc.returncode == 0:
        lines = [ln.strip() for ln in root_commit_proc.stdout.splitlines() if ln.strip()]
        if lines:
            seed = f"git-root-commit:{lines[0]}"

    if seed is None:
        remote_proc = _run_git(resolved, ["config", "--get", "remote.origin.url"])
        if remote_proc is not None and remote_proc.returncode == 0:
            sanitized = sanitize_remote_url(remote_proc.stdout)
            if sanitized:
                seed = f"git-remote:{sanitized}"

    if seed is None:
        effective_name = (project_name or resolved.name or "unnamed-project").strip()
        seed = f"project-name:{effective_name}"

    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]
    return f"repo:sha256:{digest}"
