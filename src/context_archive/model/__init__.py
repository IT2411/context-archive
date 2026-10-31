"""model subsystem for context-archive."""

from __future__ import annotations

from context_archive.model.graph import (
    CanonicalGraph,
    Diagnostic,
    Edge,
    EdgeKind,
    Node,
    NodeKind,
)
from context_archive.model.ids import (
    make_edge_id,
    make_file_id,
    make_module_id,
    make_symbol_id,
    normalize_posix_path,
)
from context_archive.model.manifest import (
    DETERMINISTIC_TIMESTAMP,
    Manifest,
    StateCursors,
    compute_text_fingerprint,
    load_manifest,
    write_manifest,
)
from context_archive.model.provenance import ConfidenceLevel, EvidenceKind, Provenance

__all__ = [
    "CanonicalGraph",
    "ConfidenceLevel",
    "DETERMINISTIC_TIMESTAMP",
    "Diagnostic",
    "Edge",
    "EdgeKind",
    "EvidenceKind",
    "Manifest",
    "Node",
    "NodeKind",
    "Provenance",
    "StateCursors",
    "compute_text_fingerprint",
    "load_manifest",
    "make_edge_id",
    "make_file_id",
    "make_module_id",
    "make_symbol_id",
    "normalize_posix_path",
    "write_manifest",
]
