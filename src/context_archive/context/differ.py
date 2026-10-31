"""Semantic graph diffing and downstream impact traversal (`ctxa diff`) implementing FR-15."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from context_archive.state.journal import JournalImpactItem

if TYPE_CHECKING:
    from context_archive.model.graph import CanonicalGraph, Node

SymbolChangeKind = Literal["added", "removed", "modified"]
ImpactConfidenceLabel = Literal["direct", "inferred_downstream"]


class SymbolDiffItem(BaseModel):
    """Direct structural change to a canonical graph symbol."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol_id: str
    qualified_name: str
    kind: str
    change_kind: SymbolChangeKind
    source_path: str
    line_start: int
    old_signature: str | None = Field(default=None)
    new_signature: str | None = Field(default=None)
    confidence: ImpactConfidenceLabel = "direct"


class DownstreamImpactItem(BaseModel):
    """Downstream caller, importer, consumer, or test impacted by a symbol change."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_id: str
    target_qualified_name: str
    target_kind: str
    source_symbol_id: str
    relationship: str
    hop_distance: int = Field(ge=1)
    confidence: ImpactConfidenceLabel = "inferred_downstream"
    evidence_path: str

    def to_journal_impact(self) -> JournalImpactItem:
        """Convert to a compact JournalImpactItem for JSONL persistence."""
        return JournalImpactItem(
            target_id=self.target_id,
            relationship=self.relationship,
            confidence=self.confidence,
            evidence_path=self.evidence_path,
        )


class SemanticDiffReport(BaseModel):
    """Complete semantic diff and impact report between a baseline and current graph."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    baseline_id: str
    added_files: tuple[str, ...] = Field(default=())
    modified_files: tuple[str, ...] = Field(default=())
    deleted_files: tuple[str, ...] = Field(default=())
    symbol_changes: tuple[SymbolDiffItem, ...] = Field(default=())
    downstream_impacts: tuple[DownstreamImpactItem, ...] = Field(default=())
    unresolved_dynamic_warnings: tuple[str, ...] = Field(default=())

    @property
    def has_changes(self) -> bool:
        """Return True if any file or symbol changes exist."""
        return bool(
            self.added_files or self.modified_files or self.deleted_files or self.symbol_changes
        )

    def to_deterministic_json(self, *, indent: int = 2) -> str:
        """Serialize diff report to deterministically sorted JSON."""
        return json.dumps(self.model_dump(mode="json"), indent=indent, sort_keys=True) + "\n"

    def render_text(self) -> str:
        """Render a human-readable semantic diff and impact report."""
        lines: list[str] = [f"# Semantic Diff & Impact Report (Baseline: `{self.baseline_id}`)"]
        if not self.has_changes:
            lines.append("No structural or file changes detected.")
            return "\n".join(lines) + "\n"

        lines.append("\n## 1. File Mutations")
        for p in self.added_files:
            lines.append(f"- **[ADDED]** `{p}`")
        for p in self.modified_files:
            lines.append(f"- **[MODIFIED]** `{p}`")
        for p in self.deleted_files:
            lines.append(f"- **[DELETED]** `{p}`")

        lines.append("\n## 2. Direct Symbol & Contract Changes (`confidence: direct`)")
        if self.symbol_changes:
            for sc in self.symbol_changes:
                sig_detail = ""
                if sc.old_signature != sc.new_signature:
                    if sc.change_kind == "modified":
                        sig_detail = f" (`{sc.old_signature}` -> `{sc.new_signature}`)"
                    elif sc.change_kind == "added" and sc.new_signature:
                        sig_detail = f" (`{sc.new_signature}`)"
                    elif sc.change_kind == "removed" and sc.old_signature:
                        sig_detail = f" (`{sc.old_signature}`)"
                lines.append(
                    f"- **[{sc.change_kind.upper()}]** [{sc.kind}] `{sc.qualified_name}`"
                    f"{sig_detail} (`{sc.source_path}:{sc.line_start}`)"
                )
        else:
            lines.append("- _No public symbol signature additions/removals._")

        lines.append("\n## 3. Downstream Impact (`confidence: inferred_downstream`)")
        if self.downstream_impacts:
            for imp in self.downstream_impacts:
                lines.append(
                    f"- **[{imp.relationship} | hop={imp.hop_distance}]** "
                    f"[{imp.target_kind}] `{imp.target_qualified_name}` "
                    f"(`{imp.evidence_path}` | `{imp.confidence}`)"
                )
        else:
            lines.append("- _No downstream callers, importers, or tests impacted._")

        if self.unresolved_dynamic_warnings:
            lines.append("\n## 4. Dynamic Resolution Warnings")
            for warn in self.unresolved_dynamic_warnings:
                lines.append(f"- {warn}")

        return "\n".join(lines) + "\n"


def _node_signature_summary(node: Node) -> str:
    """Return a concise signature or structural summary for a Node."""
    sig = str(node.attributes.get("signature", ""))
    if sig:
        prefix = "async " if node.attributes.get("is_async") else ""
        return f"{prefix}{sig}"
    bases = node.attributes.get("bases", [])
    if bases:
        return f"bases=({', '.join(str(b) for b in bases)})"
    return ""


def compute_downstream_impacts(
    graph: CanonicalGraph,
    seed_symbol_ids: set[str],
    *,
    max_hops: int = 2,
) -> list[DownstreamImpactItem]:
    """Traverse up to `max_hops` from seed_symbol_ids to find impacted callers/importers/tests."""
    by_id = graph.node_map()
    impacts_by_target: dict[str, DownstreamImpactItem] = {}
    visited_seeds = set(seed_symbol_ids)
    frontier: set[tuple[str, str]] = {(sid, sid) for sid in seed_symbol_ids if sid in by_id}

    for hop in range(1, max_hops + 1):
        next_frontier: set[tuple[str, str]] = set()
        for current_id, root_seed_id in sorted(frontier):
            for edge in graph.edges:
                if edge.target_id == current_id and edge.kind in (
                    "CALLS",
                    "IMPORTS",
                    "INHERITS",
                    "CONSUMES",
                    "EXPOSES",
                    "VALIDATES_WITH",
                ):
                    dependent_id = edge.source_id
                    dep_node = by_id.get(dependent_id)
                    if (
                        dep_node is not None
                        and dependent_id not in visited_seeds
                        and dependent_id not in impacts_by_target
                    ):
                        rel_label = "TESTED_BY" if dep_node.kind == "Test" else edge.kind
                        ev_path = f"{dep_node.provenance.source_path}:{edge.provenance.line_start}"
                        impacts_by_target[dependent_id] = DownstreamImpactItem(
                            target_id=dependent_id,
                            target_qualified_name=dep_node.qualified_name,
                            target_kind=dep_node.kind,
                            source_symbol_id=root_seed_id,
                            relationship=rel_label,
                            hop_distance=hop,
                            confidence="inferred_downstream",
                            evidence_path=ev_path,
                        )
                        next_frontier.add((dependent_id, root_seed_id))

                elif edge.source_id == current_id and edge.kind == "TESTED_BY":
                    test_id = edge.target_id
                    test_node = by_id.get(test_id)
                    if (
                        test_node is not None
                        and test_id not in visited_seeds
                        and test_id not in impacts_by_target
                    ):
                        ev_path = (
                            f"{test_node.provenance.source_path}:{test_node.provenance.line_start}"
                        )
                        impacts_by_target[test_id] = DownstreamImpactItem(
                            target_id=test_id,
                            target_qualified_name=test_node.qualified_name,
                            target_kind=test_node.kind,
                            source_symbol_id=root_seed_id,
                            relationship="TESTED_BY",
                            hop_distance=hop,
                            confidence="inferred_downstream",
                            evidence_path=ev_path,
                        )
                        next_frontier.add((test_id, root_seed_id))

        frontier = next_frontier
        if not frontier:
            break

    return [impacts_by_target[tid] for tid in sorted(impacts_by_target)]


def compute_semantic_diff(
    *,
    baseline_id: str,
    baseline_graph: CanonicalGraph,
    baseline_fingerprints: dict[str, str],
    current_graph: CanonicalGraph,
    current_fingerprints: dict[str, str],
    body_modified_symbols: set[str] | None = None,
    max_hops: int = 2,
) -> SemanticDiffReport:
    """Compute direct file/symbol changes and N-hop downstream impact between two states."""
    added_files = sorted(p for p in current_fingerprints if p not in baseline_fingerprints)
    deleted_files = sorted(p for p in baseline_fingerprints if p not in current_fingerprints)
    modified_files = sorted(
        p
        for p in current_fingerprints
        if p in baseline_fingerprints and current_fingerprints[p] != baseline_fingerprints[p]
    )

    old_symbols = {
        n.id: n for n in baseline_graph.nodes if n.kind not in ("File", "Directory", "Repository")
    }
    new_symbols = {
        n.id: n for n in current_graph.nodes if n.kind not in ("File", "Directory", "Repository")
    }

    symbol_changes: list[SymbolDiffItem] = []
    seed_ids: set[str] = set(body_modified_symbols or set())

    for sym_id in sorted(set(old_symbols) | set(new_symbols)):
        old_node = old_symbols.get(sym_id)
        new_node = new_symbols.get(sym_id)

        if old_node is None and new_node is not None:
            if new_node.kind == "Module":
                continue
            symbol_changes.append(
                SymbolDiffItem(
                    symbol_id=sym_id,
                    qualified_name=new_node.qualified_name,
                    kind=new_node.kind,
                    change_kind="added",
                    source_path=new_node.provenance.source_path,
                    line_start=new_node.provenance.line_start,
                    old_signature=None,
                    new_signature=_node_signature_summary(new_node) or None,
                )
            )
            seed_ids.add(sym_id)

        elif old_node is not None and new_node is None:
            if old_node.kind == "Module":
                continue
            symbol_changes.append(
                SymbolDiffItem(
                    symbol_id=sym_id,
                    qualified_name=old_node.qualified_name,
                    kind=old_node.kind,
                    change_kind="removed",
                    source_path=old_node.provenance.source_path,
                    line_start=old_node.provenance.line_start,
                    old_signature=_node_signature_summary(old_node) or None,
                    new_signature=None,
                )
            )
            seed_ids.add(sym_id)

        elif old_node is not None and new_node is not None:
            if new_node.kind == "Module":
                continue
            old_sig = _node_signature_summary(old_node)
            new_sig = _node_signature_summary(new_node)
            file_was_modified = new_node.provenance.source_path in modified_files
            if old_sig != new_sig or sym_id in seed_ids or file_was_modified:
                symbol_changes.append(
                    SymbolDiffItem(
                        symbol_id=sym_id,
                        qualified_name=new_node.qualified_name,
                        kind=new_node.kind,
                        change_kind="modified",
                        source_path=new_node.provenance.source_path,
                        line_start=new_node.provenance.line_start,
                        old_signature=old_sig or None,
                        new_signature=new_sig or None,
                    )
                )
                seed_ids.add(sym_id)

    impacts_curr = compute_downstream_impacts(current_graph, seed_ids, max_hops=max_hops)
    impacts_base = compute_downstream_impacts(baseline_graph, seed_ids, max_hops=max_hops)
    merged_impacts = {imp.target_id: imp for imp in [*impacts_base, *impacts_curr]}
    sorted_impacts = [merged_impacts[tid] for tid in sorted(merged_impacts)]

    dyn_warnings = sorted(
        {
            f"{d.source_path}:{d.line} - {d.message}"
            for d in current_graph.diagnostics
            if d.code in ("unresolved_dynamic_call", "wildcard_import")
        }
    )

    return SemanticDiffReport(
        baseline_id=baseline_id,
        added_files=tuple(added_files),
        modified_files=tuple(modified_files),
        deleted_files=tuple(deleted_files),
        symbol_changes=tuple(symbol_changes),
        downstream_impacts=tuple(sorted_impacts),
        unresolved_dynamic_warnings=tuple(dyn_warnings),
    )
