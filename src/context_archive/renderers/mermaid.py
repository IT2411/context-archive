"""Deterministic Mermaid diagram renderer for canonical graphs and semantic diffs."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from context_archive.context.differ import SemanticDiffReport
    from context_archive.model.graph import CanonicalGraph

_MERMAID_ID_RE = re.compile(r"[^a-zA-Z0-9_]")


def _sanitize_mermaid_id(raw_id: str) -> str:
    """Convert a canonical node ID into a safe Mermaid node identifier."""
    cleaned = _MERMAID_ID_RE.sub("_", raw_id)
    return f"N_{cleaned}"


def _escape_label(text: str) -> str:
    """Escape quotes in Mermaid node labels."""
    return text.replace('"', "'")


def render_graph_mermaid(graph: CanonicalGraph) -> str:
    """Render a deterministic Mermaid flowchart of modules, symbols, and structural edges."""
    lines: list[str] = ["flowchart TD"]
    by_id = graph.node_map()

    visible_nodes = [n for n in graph.nodes if n.kind != "File"]
    for node in visible_nodes:
        m_id = _sanitize_mermaid_id(node.id)
        label = _escape_label(f"[{node.kind}] {node.qualified_name}")
        lines.append(f'    {m_id}["{label}"]')

    visible_ids = {n.id for n in visible_nodes}
    for edge in graph.edges:
        if edge.kind == "CONTAINS":
            continue
        if edge.source_id in visible_ids and edge.target_id in visible_ids:
            src_m = _sanitize_mermaid_id(edge.source_id)
            tgt_m = _sanitize_mermaid_id(edge.target_id)
            lines.append(f"    {src_m} -->|{edge.kind}| {tgt_m}")
            _ = by_id

    return "\n".join(lines) + "\n"


def render_diff_mermaid(diff_report: SemanticDiffReport) -> str:
    """Render a deterministic Mermaid flowchart of direct changes and downstream impacts."""
    lines: list[str] = ["flowchart TD"]
    declared: set[str] = set()

    for sc in diff_report.symbol_changes:
        m_id = _sanitize_mermaid_id(sc.symbol_id)
        declared.add(sc.symbol_id)
        label = _escape_label(f"[{sc.change_kind.upper()}: {sc.kind}] {sc.qualified_name}")
        lines.append(f'    {m_id}["{label}"]')

    for imp in diff_report.downstream_impacts:
        tgt_m = _sanitize_mermaid_id(imp.target_id)
        if imp.target_id not in declared:
            declared.add(imp.target_id)
            label = _escape_label(f"[IMPACTED: {imp.target_kind}] {imp.target_qualified_name}")
            lines.append(f'    {tgt_m}["{label}"]')

        src_m = _sanitize_mermaid_id(imp.source_symbol_id)
        if imp.source_symbol_id not in declared:
            declared.add(imp.source_symbol_id)
            lines.append(f'    {src_m}["{_escape_label(imp.source_symbol_id)}"]')

        lines.append(f"    {src_m} -.->|{imp.relationship} hop={imp.hop_distance}| {tgt_m}")

    if len(lines) == 1:
        lines.append('    N_CLEAN["No structural changes detected"]')

    return "\n".join(lines) + "\n"
