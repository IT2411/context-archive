"""Deterministic canonical Node and Edge identifier generators (ADR 001)."""

from __future__ import annotations

from pathlib import PurePosixPath


def normalize_posix_path(raw_path: str) -> str:
    """Normalize a relative path to forward-slash POSIX form without leading './'."""
    replaced = raw_path.replace("\\", "/").strip()
    if not replaced or replaced == ".":
        return "."
    norm = PurePosixPath(replaced).as_posix()
    while norm.startswith("./"):
        norm = norm[2:]
    return norm or "."


def make_file_id(source_path: str) -> str:
    """Create a deterministic File node ID: `file:<posix_path>`."""
    return f"file:{normalize_posix_path(source_path)}"


def make_module_id(language: str, source_path: str, qualified_module: str) -> str:
    """Create a deterministic Module node ID: `mod:<lang>:<posix_path>:<qualified_module>`."""
    norm_path = normalize_posix_path(source_path)
    return f"mod:{language.lower()}:{norm_path}:{qualified_module}"


def make_symbol_id(language: str, source_path: str, qualified_symbol: str) -> str:
    """Create a deterministic Symbol node ID: `sym:<lang>:<posix_path>:<qualified_symbol>`."""
    norm_path = normalize_posix_path(source_path)
    return f"sym:{language.lower()}:{norm_path}:{qualified_symbol}"


def make_edge_id(kind: str, source_id: str, target_id: str) -> str:
    """Create a deterministic Edge ID: `edge:<KIND>:<source_id>-><target_id>`."""
    return f"edge:{kind}:{source_id}->{target_id}"
