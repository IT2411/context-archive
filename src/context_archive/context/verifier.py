"""Freshness verification engine (`ctxa verify`) implementing SRS FR-14."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from context_archive.exceptions import ExitCode, IntegrityError
from context_archive.model.manifest import compute_text_fingerprint, load_manifest
from context_archive.notes.boundaries import validate_and_extract_manual_block
from context_archive.scanner.walker import scan_repository
from context_archive.state.snapshot import load_snapshot

if TYPE_CHECKING:
    from pathlib import Path

    from context_archive.config import CtxaConfig

VerificationStatus = Literal[
    "CURRENT",
    "STALE_JOURNALED",
    "STALE_UNRECORDED",
    "CORRUPT_OR_MISSING",
]


class VerificationReport(BaseModel):
    """Structured result of `ctxa verify`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: VerificationStatus
    exit_code: int
    repo_root: str
    reasons: tuple[str, ...] = Field(default=())
    added_files: tuple[str, ...] = Field(default=())
    modified_files: tuple[str, ...] = Field(default=())
    deleted_files: tuple[str, ...] = Field(default=())

    def to_deterministic_json(self, *, indent: int = 2) -> str:
        """Serialize report to deterministically sorted JSON."""
        return json.dumps(self.model_dump(mode="json"), indent=indent, sort_keys=True) + "\n"


def verify_repository_freshness(
    repo_root: Path,
    config: CtxaConfig,
) -> VerificationReport:
    """Verify whether PROJECT_CONTEXT.md and .context/ match the current working tree."""
    resolved_root = repo_root.resolve()
    context_dir = resolved_root / ".context"
    output_rel = config.context.output_path
    md_path = (
        resolved_root / output_rel
        if not output_rel.startswith("/")
        else resolved_root / output_rel.lstrip("/")
    )
    notes_path = context_dir / "notes.md"

    # 1. Check structural integrity of manifest, active snapshot, and PROJECT_CONTEXT.md
    if not context_dir.is_dir() or not (context_dir / "manifest.json").is_file():
        return VerificationReport(
            status="CORRUPT_OR_MISSING",
            exit_code=int(ExitCode.INTEGRITY_ERROR),
            repo_root=resolved_root.as_posix(),
            reasons=("Missing .context/manifest.json. Run `ctxa init` or `ctxa handoff`.",),
        )

    if not md_path.is_file():
        return VerificationReport(
            status="CORRUPT_OR_MISSING",
            exit_code=int(ExitCode.INTEGRITY_ERROR),
            repo_root=resolved_root.as_posix(),
            reasons=(f"Missing context document '{md_path.name}'. Run `ctxa handoff`.",),
        )

    try:
        manifest = load_manifest(context_dir)
        _ = load_snapshot(context_dir, manifest.state_cursors.latest_snapshot_id)
        md_text = md_path.read_text(encoding="utf-8")
        md_manual = validate_and_extract_manual_block(md_text, source_path=None)
    except (IntegrityError, OSError) as exc:
        return VerificationReport(
            status="CORRUPT_OR_MISSING",
            exit_code=int(ExitCode.INTEGRITY_ERROR),
            repo_root=resolved_root.as_posix(),
            reasons=(str(exc),),
        )

    reasons: list[str] = []

    # 2. Check configuration fingerprint
    live_cfg_fp = config.fingerprint()
    if live_cfg_fp != manifest.config_fingerprint:
        reasons.append(
            f"Configuration fingerprint changed ({manifest.config_fingerprint[:19]}... -> "
            f"{live_cfg_fp[:19]}...)."
        )

    # 3. Check notes fingerprint (both .context/notes.md and inline PROJECT_CONTEXT.md manual block)
    md_manual_fp = compute_text_fingerprint(md_manual + "\n")
    if md_manual_fp != manifest.state_cursors.notes_fingerprint:
        reasons.append("Inline manual notes in PROJECT_CONTEXT.md have unrecorded edits.")
    if notes_path.is_file():
        notes_file_text = notes_path.read_text(encoding="utf-8", errors="replace").strip()
        notes_file_fp = compute_text_fingerprint(notes_file_text + "\n")
        if notes_file_fp != manifest.state_cursors.notes_fingerprint:
            reasons.append("Durable notes file (.context/notes.md) changed since last handoff.")

    # 4. Scan live repository files and Git state
    live_scan = scan_repository(resolved_root, config)
    live_git = live_scan.git_state
    recorded_git = manifest.git_state

    if live_git.is_git_repo != recorded_git.is_git_repo:
        reasons.append("Git repository initialization state changed.")
    elif live_git.is_git_repo:
        if live_git.branch != recorded_git.branch:
            reasons.append(
                f"Git branch changed from '{recorded_git.branch}' to '{live_git.branch}'."
            )
        if live_git.commit_sha != recorded_git.commit_sha:
            reasons.append(
                f"Git HEAD commit changed from '{recorded_git.commit_sha}' "
                f"to '{live_git.commit_sha}'."
            )
        if live_git.is_dirty != recorded_git.is_dirty:
            reasons.append(
                f"Git working tree dirty state changed ({recorded_git.is_dirty} -> "
                f"{live_git.is_dirty})."
            )

    live_fps = live_scan.file_fingerprints()
    recorded_fps = manifest.file_fingerprints

    added = sorted(p for p in live_fps if p not in recorded_fps)
    deleted = sorted(p for p in recorded_fps if p not in live_fps)
    modified = sorted(p for p in live_fps if p in recorded_fps and live_fps[p] != recorded_fps[p])

    if added:
        reasons.append(f"Added tracked files: {', '.join(added)}")
    if modified:
        reasons.append(f"Modified tracked files: {', '.join(modified)}")
    if deleted:
        reasons.append(f"Deleted tracked files: {', '.join(deleted)}")

    if reasons:
        return VerificationReport(
            status="STALE_UNRECORDED",
            exit_code=int(ExitCode.STALE_OR_DIFF),
            repo_root=resolved_root.as_posix(),
            reasons=tuple(reasons),
            added_files=tuple(added),
            modified_files=tuple(modified),
            deleted_files=tuple(deleted),
        )

    # 5. Check if journal has unincorporated records not yet rendered into PROJECT_CONTEXT.md
    head_cursor = manifest.state_cursors.head_journal_cursor
    if head_cursor and f"Journal Cursor `{head_cursor}`" not in md_text:
        return VerificationReport(
            status="STALE_JOURNALED",
            exit_code=int(ExitCode.STALE_OR_DIFF),
            repo_root=resolved_root.as_posix(),
            reasons=(
                f"Journal cursor '{head_cursor}' is recorded in manifest but "
                f"'{md_path.name}' has not been re-rendered.",
            ),
        )

    return VerificationReport(
        status="CURRENT",
        exit_code=int(ExitCode.SUCCESS),
        repo_root=resolved_root.as_posix(),
    )
