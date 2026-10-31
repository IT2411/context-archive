"""Data models for repository scan reports, file classifications, and diagnostics."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from context_archive.git.state import GitState

FileCategory = Literal[
    "source_code",
    "test",
    "manifest",
    "config",
    "documentation",
    "unsupported",
    "excluded",
]

DiagnosticSeverity = Literal["info", "warning", "error"]


class ScannedFile(BaseModel):
    """Metadata and content digest for a single discovered repository file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1, description="Normalized POSIX path relative to repo_root.")
    category: FileCategory
    language: str | None = Field(default=None)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")


class ScanDiagnostic(BaseModel):
    """Security, encoding, symlink, or I/O diagnostic emitted during repository scanning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1)
    severity: DiagnosticSeverity
    message: str = Field(min_length=1)
    source_path: str | None = Field(default=None)


class ScanSummary(BaseModel):
    """Aggregate file counts matching manifest.schema.json scan_summary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    files_discovered: int = Field(default=0, ge=0)
    files_analyzed: int = Field(default=0, ge=0)
    files_excluded: int = Field(default=0, ge=0)
    files_failed: int = Field(default=0, ge=0)
    unsupported_files: int = Field(default=0, ge=0)


class ScanReport(BaseModel):
    """Complete immutable output of a repository scan pass."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_id: str = Field(pattern=r"^repo:sha256:[a-f0-9]{32,64}$")
    repo_root: str = Field(min_length=1)
    config_fingerprint: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    git_state: GitState
    summary: ScanSummary
    files: tuple[ScannedFile, ...] = Field(default=())
    diagnostics: tuple[ScanDiagnostic, ...] = Field(default=())

    def file_fingerprints(self) -> dict[str, str]:
        """Return a deterministically sorted mapping of relative POSIX path -> sha256 digest."""
        return {item.path: item.sha256 for item in sorted(self.files, key=lambda f: f.path)}
