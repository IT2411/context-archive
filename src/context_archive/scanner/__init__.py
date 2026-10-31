"""scanner subsystem for context-archive."""

from __future__ import annotations

from context_archive.scanner.discovery import DiscoveredRepo, discover_repo_root
from context_archive.scanner.report import (
    FileCategory,
    ScanDiagnostic,
    ScannedFile,
    ScanReport,
    ScanSummary,
)
from context_archive.scanner.walker import scan_repository

__all__ = [
    "DiscoveredRepo",
    "FileCategory",
    "ScanDiagnostic",
    "ScanReport",
    "ScanSummary",
    "ScannedFile",
    "discover_repo_root",
    "scan_repository",
]
