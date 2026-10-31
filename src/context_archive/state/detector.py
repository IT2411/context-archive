"""Incremental change detector, AST signature diffing, and Update Level (L1/L2/L3) selector."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING

from context_archive.adapters.pipeline import extract_all_adapters
from context_archive.adapters.python_ast import resolve_relative_module
from context_archive.scanner.walker import MANIFEST_FILENAMES
from context_archive.state.journal import (
    ChangeCategory,
    JournalFileChange,
    JournalIntent,
    JournalRecord,
    UpdateLevel,
    compute_tree_fingerprint,
)

if TYPE_CHECKING:
    from pathlib import Path

    from context_archive.model.graph import CanonicalGraph, Node
    from context_archive.model.manifest import Manifest
    from context_archive.scanner.report import ScannedFile, ScanReport


@dataclass(frozen=True)
class ChangeDetectionResult:
    """Result of comparing the live repository against the latest recorded state."""

    is_noop: bool
    update_level: UpdateLevel
    category: ChangeCategory
    intent: JournalIntent
    file_changes: tuple[JournalFileChange, ...]
    tree_fingerprint: str


def _symbol_structural_key(node: Node) -> tuple[str, str, str, bool, tuple[str, ...]]:
    """Return a tuple representing the public structural contract of a symbol node."""
    sig = str(node.attributes.get("signature", ""))
    is_async = bool(node.attributes.get("is_async", False))
    decorators = tuple(str(d) for d in node.attributes.get("decorators", []))
    bases = tuple(str(b) for b in node.attributes.get("bases", []))
    return (node.kind, node.qualified_name, sig, is_async, decorators + bases)


def _extract_internal_import_targets(
    repo_root: Path,
    rel_path: str,
    previous_graph: CanonicalGraph,
) -> set[str] | None:
    """Extract resolved intra-repo import targets from a Python file's AST."""
    try:
        source_text = (repo_root / rel_path).read_text(encoding="utf-8")
        tree = ast.parse(source_text, filename=rel_path)
    except (OSError, SyntaxError, ValueError):
        return None

    known_quals = {n.qualified_name: n.id for n in previous_graph.nodes}
    resolved_targets: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in known_quals:
                    resolved_targets.add(known_quals[alias.name])
        elif isinstance(node, ast.ImportFrom):
            base_mod = (
                resolve_relative_module(rel_path, node.module, node.level)
                if node.level > 0
                else (node.module or "")
            )
            for alias in node.names:
                target_qual = f"{base_mod}.{alias.name}" if base_mod else alias.name
                if target_qual in known_quals:
                    resolved_targets.add(known_quals[target_qual])
                elif base_mod in known_quals:
                    resolved_targets.add(known_quals[base_mod])

    return resolved_targets


def _analyze_modified_source_file(
    repo_root: Path,
    scanned_file: ScannedFile,
    previous_graph: CanonicalGraph,
) -> tuple[list[str], bool]:
    """Compare a modified source file against previous_graph.

    Returns `(modified_symbol_ids, has_structural_or_signature_change)`.
    """
    if scanned_file.language not in ("python", "typescript", "javascript"):
        return [], False

    res = extract_all_adapters(repo_root, [scanned_file])
    if any(d.code == "python_syntax_error" for d in res.diagnostics):
        return [], True

    rel_path = scanned_file.path
    old_nodes = {
        n.id: n
        for n in previous_graph.nodes
        if n.provenance.source_path == rel_path and n.kind not in ("File", "Module")
    }
    new_nodes = {
        n.id: n
        for n in res.nodes
        if n.provenance.source_path == rel_path and n.kind not in ("File", "Module")
    }

    structural_change = False
    if scanned_file.language == "python":
        old_import_targets = {
            e.target_id
            for e in previous_graph.edges
            if e.provenance.source_path == rel_path and e.kind == "IMPORTS"
        }
        new_import_targets = _extract_internal_import_targets(repo_root, rel_path, previous_graph)
        if new_import_targets is None or old_import_targets != new_import_targets:
            structural_change = True
    else:
        # TypeScript/JS modifications always refresh partial graph (L2)
        structural_change = True

    if set(old_nodes.keys()) != set(new_nodes.keys()):
        structural_change = True

    modified_symbols: list[str] = []
    for sym_id in sorted(set(old_nodes.keys()) | set(new_nodes.keys())):
        old_sym = old_nodes.get(sym_id)
        new_sym = new_nodes.get(sym_id)
        if (
            old_sym is None
            or new_sym is None
            or _symbol_structural_key(old_sym) != _symbol_structural_key(new_sym)
        ):
            modified_symbols.append(sym_id)
            structural_change = True
        else:
            modified_symbols.append(sym_id)

    return modified_symbols, structural_change


def _classify_change_category(
    *,
    file_changes: list[JournalFileChange],
    scan_by_path: dict[str, ScannedFile],
    has_signature_change: bool,
    is_revert: bool,
    config_changed: bool,
) -> ChangeCategory:
    """Assign a deterministic ChangeCategory strictly from file and AST evidence (FR-09)."""
    if is_revert:
        return "revert"
    if config_changed:
        return "config_change"
    if not file_changes:
        return "unknown"

    paths = [fc.path for fc in file_changes]
    categories: set[str] = set()
    for p in paths:
        sf = scan_by_path.get(p)
        if sf is not None:
            categories.add(sf.category)
        elif p.endswith((".md", ".rst", ".txt")):
            categories.add("documentation")
        elif p.startswith("tests/") or "/test_" in p or p.startswith("test_"):
            categories.add("test")
        elif p in MANIFEST_FILENAMES:
            categories.add("manifest")
        elif p.endswith((".toml", ".yaml", ".yml", ".json", ".ini", ".cfg")):
            categories.add("config")
        else:
            categories.add("source_code")

    if categories == {"documentation"}:
        return "docs_change"
    if categories == {"test"}:
        return "test_change"
    if categories == {"manifest"}:
        return "dependency_change"
    if categories == {"config"}:
        return "config_change"
    if any("schema" in p.lower() or "models" in p.lower() for p in paths) and has_signature_change:
        return "schema_change"
    if has_signature_change:
        return "contract_change"
    return "unknown"


def detect_repository_changes(
    *,
    repo_root: Path,
    manifest: Manifest,
    previous_graph: CanonicalGraph,
    live_scan: ScanReport,
    existing_records: list[JournalRecord],
    baseline_tree_fingerprint: str | None = None,
    requested_level: str = "auto",
    developer_message: str | None = None,
) -> ChangeDetectionResult:
    """Diff live_scan against manifest and classify Update Level (L1/L2/L3) and Category."""
    live_fps = live_scan.file_fingerprints()
    recorded_fps = manifest.file_fingerprints
    live_tree_fp = compute_tree_fingerprint(live_fps)
    recorded_tree_fp = compute_tree_fingerprint(recorded_fps)
    config_changed = live_scan.config_fingerprint != manifest.config_fingerprint

    if live_tree_fp == recorded_tree_fp and not config_changed:
        return ChangeDetectionResult(
            is_noop=True,
            update_level="L1",
            category="unknown",
            intent=JournalIntent(
                summary="No changes detected.",
                origin="deterministic_classifier",
                confidence="high",
            ),
            file_changes=(),
            tree_fingerprint=live_tree_fp,
        )

    raw_added = {p: live_fps[p] for p in live_fps if p not in recorded_fps}
    raw_deleted = {p: recorded_fps[p] for p in recorded_fps if p not in live_fps}
    raw_modified = [
        p for p in sorted(live_fps) if p in recorded_fps and live_fps[p] != recorded_fps[p]
    ]

    deleted_by_hash: dict[str, list[str]] = {}
    for del_path, del_sha in sorted(raw_deleted.items()):
        deleted_by_hash.setdefault(del_sha, []).append(del_path)

    renamed_added: dict[str, str] = {}
    matched_deleted: set[str] = set()
    for add_path, add_sha in sorted(raw_added.items()):
        candidates = deleted_by_hash.get(add_sha, [])
        if candidates:
            old_path = candidates.pop(0)
            renamed_added[add_path] = old_path
            matched_deleted.add(old_path)

    scan_by_path = {sf.path: sf for sf in live_scan.files}
    file_changes: list[JournalFileChange] = []
    has_signature_change = False

    for add_path in sorted(raw_added):
        add_sha = raw_added[add_path]
        if add_path in renamed_added:
            has_signature_change = True
            file_changes.append(
                JournalFileChange(
                    path=add_path,
                    operation="renamed",
                    old_sha256=add_sha,
                    new_sha256=add_sha,
                    modified_symbols=(),
                )
            )
        else:
            has_signature_change = True
            file_changes.append(
                JournalFileChange(
                    path=add_path,
                    operation="added",
                    old_sha256=None,
                    new_sha256=add_sha,
                    modified_symbols=(),
                )
            )

    for mod_path in raw_modified:
        sf = scan_by_path.get(mod_path)
        mod_syms: list[str] = []
        if sf is not None and sf.language in ("python", "typescript", "javascript"):
            mod_syms, sig_changed = _analyze_modified_source_file(repo_root, sf, previous_graph)
            if sig_changed:
                has_signature_change = True
        file_changes.append(
            JournalFileChange(
                path=mod_path,
                operation="modified",
                old_sha256=recorded_fps[mod_path],
                new_sha256=live_fps[mod_path],
                modified_symbols=tuple(mod_syms),
            )
        )

    for del_path in sorted(raw_deleted):
        if del_path in matched_deleted:
            continue
        has_signature_change = True
        file_changes.append(
            JournalFileChange(
                path=del_path,
                operation="deleted",
                old_sha256=raw_deleted[del_path],
                new_sha256=None,
                modified_symbols=(),
            )
        )

    file_changes.sort(key=lambda fc: fc.path)

    historical_tree_fps = {rec.source_state.tree_fingerprint for rec in existing_records}
    if baseline_tree_fingerprint is not None:
        historical_tree_fps.add(baseline_tree_fingerprint)
    is_revert = len(existing_records) > 0 and live_tree_fp in historical_tree_fps

    total_tracked = max(1, len(recorded_fps))
    change_ratio = len(file_changes) / total_tracked

    req = requested_level.lower()
    if req in ("l1", "l2", "l3"):
        selected_level: UpdateLevel = req.upper()  # type: ignore[assignment]
    elif config_changed or (change_ratio > 0.30 and len(file_changes) >= 5):
        selected_level = "L3"
    elif has_signature_change or any(fc.operation != "modified" for fc in file_changes):
        selected_level = "L2"
    else:
        selected_level = "L1"

    category = _classify_change_category(
        file_changes=file_changes,
        scan_by_path=scan_by_path,
        has_signature_change=has_signature_change,
        is_revert=is_revert,
        config_changed=config_changed,
    )

    if developer_message and developer_message.strip():
        intent = JournalIntent(
            summary=developer_message.strip(),
            origin="developer_confirmed",
            confidence="high",
        )
    else:
        changed_paths_str = ", ".join(fc.path for fc in file_changes[:3])
        if not changed_paths_str and config_changed:
            changed_paths_str = ".ctxa.toml"
        summary = f"Detected {category} across {len(file_changes)} file(s) ({changed_paths_str})."
        intent = JournalIntent(
            summary=summary,
            origin="deterministic_classifier",
            confidence="high" if category != "unknown" else "medium",
        )

    return ChangeDetectionResult(
        is_noop=False,
        update_level=selected_level,
        category=category,
        intent=intent,
        file_changes=tuple(file_changes),
        tree_fingerprint=live_tree_fp,
    )
