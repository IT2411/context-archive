"""Protocol definitions for language and framework static analysis adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

    from context_archive.model.graph import Diagnostic, Edge, Node
    from context_archive.scanner.report import ScannedFile


@dataclass(frozen=True)
class AdapterExtractionResult:
    """Container for Nodes, Edges, and Diagnostics produced by an adapter."""

    nodes: tuple[Node, ...] = field(default=())
    edges: tuple[Edge, ...] = field(default=())
    diagnostics: tuple[Diagnostic, ...] = field(default=())


@runtime_checkable
class LanguageAdapter(Protocol):
    """Protocol implemented by static source language analyzers."""

    @property
    def adapter_id(self) -> str:
        """Return versioned extractor identifier (e.g., `python_ast:1.0`)."""

    def can_handle(self, scanned_file: ScannedFile) -> bool:
        """Return True if this adapter can analyze the given ScannedFile."""

    def extract_repository(
        self,
        repo_root: Path,
        files: tuple[ScannedFile, ...] | list[ScannedFile],
    ) -> AdapterExtractionResult:
        """Statically analyze all matching files in the repository."""
