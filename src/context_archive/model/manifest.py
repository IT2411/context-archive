"""Manifest schema model (.context/manifest.json) and atomic persistence helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from context_archive import __version__
from context_archive.exceptions import IntegrityError
from context_archive.git.state import GitState
from context_archive.lock import atomic_write_text
from context_archive.scanner.report import ScanReport, ScanSummary

if TYPE_CHECKING:
    from pathlib import Path

DETERMINISTIC_TIMESTAMP = "1970-01-01T00:00:00Z"


def compute_text_fingerprint(text: str) -> str:
    """Compute a `sha256:<hex>` digest for UTF-8 text."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


class StateCursors(BaseModel):
    """Cursors tracking active snapshot, journal head, and notes fingerprint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    latest_snapshot_id: str = Field(pattern=r"^snapshot-[0-9]{4,}$")
    snapshot_incorporated_journal_cursor: str | None = Field(default=None)
    head_journal_cursor: str | None = Field(default=None)
    unincorporated_record_count: int = Field(default=0, ge=0)
    notes_fingerprint: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")


class Manifest(BaseModel):
    """Root model for .context/manifest.json matching docs/schemas/manifest.schema.json."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    tool_version: str = Field(default=__version__, min_length=1)
    repository_id: str = Field(pattern=r"^repo:sha256:[a-f0-9]{32,64}$")
    generated_at: str = Field(min_length=1)
    config_fingerprint: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    git_state: GitState
    state_cursors: StateCursors
    scan_summary: ScanSummary
    file_fingerprints: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_scan_report(
        cls,
        scan_report: ScanReport,
        *,
        latest_snapshot_id: str = "snapshot-0001",
        snapshot_incorporated_journal_cursor: str | None = None,
        head_journal_cursor: str | None = None,
        unincorporated_record_count: int = 0,
        notes_content: str = "",
        deterministic: bool = False,
        files_failed_override: int | None = None,
    ) -> Manifest:
        """Build a Manifest from a ScanReport and active cursor metadata."""
        timestamp = (
            DETERMINISTIC_TIMESTAMP
            if deterministic
            else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        summary = scan_report.summary
        if files_failed_override is not None:
            summary = ScanSummary(
                files_discovered=summary.files_discovered,
                files_analyzed=summary.files_analyzed,
                files_excluded=summary.files_excluded,
                files_failed=files_failed_override,
                unsupported_files=summary.unsupported_files,
            )
        return cls(
            tool_version=__version__,
            repository_id=scan_report.repository_id,
            generated_at=timestamp,
            config_fingerprint=scan_report.config_fingerprint,
            git_state=scan_report.git_state,
            state_cursors=StateCursors(
                latest_snapshot_id=latest_snapshot_id,
                snapshot_incorporated_journal_cursor=snapshot_incorporated_journal_cursor,
                head_journal_cursor=head_journal_cursor,
                unincorporated_record_count=unincorporated_record_count,
                notes_fingerprint=compute_text_fingerprint(notes_content),
            ),
            scan_summary=summary,
            file_fingerprints=scan_report.file_fingerprints(),
        )

    def to_deterministic_json(self, *, indent: int = 2) -> str:
        """Serialize manifest to deterministically sorted JSON."""
        payload = self.model_dump(mode="json")
        git_dict = payload.get("git_state")
        if isinstance(git_dict, dict) and git_dict.get("remote_url") is None:
            git_dict.pop("remote_url", None)
        return json.dumps(payload, indent=indent, sort_keys=True) + "\n"


def write_manifest(context_dir: Path, manifest: Manifest) -> Path:
    """Atomically write .context/manifest.json."""
    target = context_dir / "manifest.json"
    atomic_write_text(target, manifest.to_deterministic_json())
    return target


def load_manifest(context_dir: Path) -> Manifest:
    """Load and validate .context/manifest.json or raise IntegrityError (Exit 4)."""
    target = context_dir / "manifest.json"
    if not target.is_file():
        raise IntegrityError(f"Manifest file is missing: '{target}'")
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        return Manifest.model_validate(raw)
    except (OSError, ValueError, ValidationError) as exc:
        raise IntegrityError(f"Corrupt or incompatible manifest '{target}': {exc}") from exc
