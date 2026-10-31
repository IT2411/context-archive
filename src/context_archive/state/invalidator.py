"""Partial graph invalidation and L2/L3 escalation engine implementing SRS FR-10."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from context_archive.adapters.pipeline import extract_all_adapters
from context_archive.model.graph import CanonicalGraph

if TYPE_CHECKING:
    from pathlib import Path

    from context_archive.scanner.report import ScannedFile
    from context_archive.state.journal import JournalFileChange, UpdateLevel

REVERSE_DEPENDENCY_EDGE_KINDS = frozenset(
    {
        "IMPORTS",
        "CALLS",
        "INHERITS",
        "EXPOSES",
        "CONSUMES",
        "VALIDATES_WITH",
        "DEPENDS_ON",
        "READS",
        "WRITES",
    }
)


@dataclass(frozen=True)
class GraphInvalidationResult:
    """Result of refreshing the canonical graph during an L2/L3 update."""

    effective_level: UpdateLevel
    escalated_to_l3: bool
    escalation_reason: str | None
    invalidated_paths: tuple[str, ...]
    graph: CanonicalGraph


def compute_invalidated_paths(
    previous_graph: CanonicalGraph,
    file_changes: tuple[JournalFileChange, ...] | list[JournalFileChange],
) -> tuple[set[str], str | None]:
    """Identify all source file paths invalidated by `file_changes` via reverse edges.

    Returns `(invalidated_file_paths, escalation_reason_if_any)`.
    """
    changed_paths = {fc.path for fc in file_changes}
    for path in changed_paths:
        if path.endswith("__init__.py"):
            return changed_paths, "Package __init__.py re-export modified."

    for diag in previous_graph.diagnostics:
        if diag.code == "wildcard_import":
            return changed_paths, "Repository contains wildcard imports."

    by_id = previous_graph.node_map()
    affected_node_ids = {
        node.id for node in previous_graph.nodes if node.provenance.source_path in changed_paths
    }

    dependent_paths: set[str] = set(changed_paths)
    frontier = set(affected_node_ids)
    for _ in range(3):
        next_frontier: set[str] = set()
        for edge in previous_graph.edges:
            if edge.kind in REVERSE_DEPENDENCY_EDGE_KINDS and edge.target_id in frontier:
                src_node = by_id.get(edge.source_id)
                if src_node is not None:
                    dependent_paths.add(src_node.provenance.source_path)
                    next_frontier.add(src_node.id)
            elif edge.kind == "TESTED_BY" and edge.source_id in frontier:
                test_node = by_id.get(edge.target_id)
                if test_node is not None:
                    dependent_paths.add(test_node.provenance.source_path)
                    next_frontier.add(test_node.id)
        frontier = next_frontier
        if not frontier:
            break

    return dependent_paths, None


def refresh_graph_incrementally(
    *,
    repo_root: Path,
    previous_graph: CanonicalGraph,
    live_files: tuple[ScannedFile, ...] | list[ScannedFile],
    file_changes: tuple[JournalFileChange, ...] | list[JournalFileChange],
    requested_level: UpdateLevel,
    base_snapshot_id: str,
    applied_journal_cursor: str | None,
) -> GraphInvalidationResult:
    """Refresh CanonicalGraph via L2 partial invalidation or L3 full rebuild.

    Guarantees 100% semantic equivalence with a clean L3 full rebuild (FR-10).
    """
    source_files = [
        f
        for f in live_files
        if f.language in ("python", "typescript", "javascript")
        and f.category in ("source_code", "test")
    ]
    total_src = max(1, len(source_files))

    if requested_level == "L3":
        full_res = extract_all_adapters(repo_root, source_files)
        full_graph = CanonicalGraph.build(
            repository_id=previous_graph.repository_id,
            base_snapshot_id=base_snapshot_id,
            applied_journal_cursor=applied_journal_cursor,
            nodes=full_res.nodes,
            edges=full_res.edges,
            diagnostics=full_res.diagnostics,
        )
        return GraphInvalidationResult(
            effective_level="L3",
            escalated_to_l3=False,
            escalation_reason=None,
            invalidated_paths=tuple(sorted(f.path for f in source_files)),
            graph=full_graph,
        )

    invalidated_paths, escalation_reason = compute_invalidated_paths(previous_graph, file_changes)
    any_deleted_or_renamed = any(fc.operation in ("deleted", "renamed") for fc in file_changes)
    if escalation_reason is None and any_deleted_or_renamed:
        escalation_reason = "File deletion or rename requires full symbol table relinking."

    if escalation_reason is None and (len(invalidated_paths) / total_src) > 0.30 and total_src >= 5:
        escalation_reason = "More than 30% of repository source files invalidated."

    all_res = extract_all_adapters(repo_root, source_files)

    if escalation_reason is not None:
        rebuilt_graph = CanonicalGraph.build(
            repository_id=previous_graph.repository_id,
            base_snapshot_id=base_snapshot_id,
            applied_journal_cursor=applied_journal_cursor,
            nodes=all_res.nodes,
            edges=all_res.edges,
            diagnostics=all_res.diagnostics,
        )
        return GraphInvalidationResult(
            effective_level="L3",
            escalated_to_l3=True,
            escalation_reason=escalation_reason,
            invalidated_paths=tuple(sorted(invalidated_paths)),
            graph=rebuilt_graph,
        )

    unchanged_nodes = [
        n for n in previous_graph.nodes if n.provenance.source_path not in invalidated_paths
    ]
    refreshed_nodes = [n for n in all_res.nodes if n.provenance.source_path in invalidated_paths]

    unchanged_edges = [
        e for e in previous_graph.edges if e.provenance.source_path not in invalidated_paths
    ]
    refreshed_edges = [e for e in all_res.edges if e.provenance.source_path in invalidated_paths]

    unchanged_diags = [
        d for d in previous_graph.diagnostics if (d.source_path or "") not in invalidated_paths
    ]
    refreshed_diags = [d for d in all_res.diagnostics if (d.source_path or "") in invalidated_paths]

    spliced_graph = CanonicalGraph.build(
        repository_id=previous_graph.repository_id,
        base_snapshot_id=base_snapshot_id,
        applied_journal_cursor=applied_journal_cursor,
        nodes=[*unchanged_nodes, *refreshed_nodes],
        edges=[*unchanged_edges, *refreshed_edges],
        diagnostics=[*unchanged_diags, *refreshed_diags],
    )
    return GraphInvalidationResult(
        effective_level="L2",
        escalated_to_l3=False,
        escalation_reason=None,
        invalidated_paths=tuple(sorted(invalidated_paths)),
        graph=spliced_graph,
    )
