"""Canonical graph model (Nodes, Edges, Diagnostics) and deterministic serialization."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from context_archive.model.provenance import Provenance

NodeKind = Literal[
    "Repository",
    "Directory",
    "File",
    "Module",
    "Class",
    "Function",
    "Method",
    "Variable",
    "Endpoint",
    "Schema",
    "DataEntity",
    "Test",
    "Dependency",
    "Configuration",
    "Decision",
    "Constraint",
]

EdgeKind = Literal[
    "CONTAINS",
    "IMPORTS",
    "DEFINES",
    "INHERITS",
    "CALLS",
    "DECORATES",
    "EXPOSES",
    "CONSUMES",
    "VALIDATES_WITH",
    "READS",
    "WRITES",
    "TESTED_BY",
    "DEPENDS_ON",
    "CONSTRAINED_BY",
    "IMPACTS",
]

DiagnosticSeverity = Literal["info", "warning", "error"]


class Node(BaseModel):
    """Canonical entity node in the repository knowledge graph."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    kind: NodeKind
    name: str = Field(min_length=1)
    qualified_name: str = Field(min_length=1)
    attributes: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance


class Edge(BaseModel):
    """Directed relationship edge between two canonical nodes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    kind: EdgeKind
    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    attributes: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance


class Diagnostic(BaseModel):
    """Extraction warning, unresolved reference, or syntax error diagnostic."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1)
    severity: DiagnosticSeverity
    message: str = Field(min_length=1)
    source_path: str | None = Field(default=None)
    line: int | None = Field(default=None, ge=1)


class CanonicalGraph(BaseModel):
    """Schema-versioned canonical project graph conforming to docs/schemas/graph.schema.json."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    repository_id: str = Field(pattern=r"^repo:sha256:[a-f0-9]{32,64}$")
    base_snapshot_id: str = Field(pattern=r"^snapshot-[0-9]{4,}$")
    applied_journal_cursor: str | None = Field(default=None)
    nodes: tuple[Node, ...] = Field(default=())
    edges: tuple[Edge, ...] = Field(default=())
    diagnostics: tuple[Diagnostic, ...] = Field(default=())

    @classmethod
    def build(
        cls,
        *,
        repository_id: str,
        base_snapshot_id: str = "snapshot-0001",
        applied_journal_cursor: str | None = None,
        nodes: list[Node] | tuple[Node, ...] = (),
        edges: list[Edge] | tuple[Edge, ...] = (),
        diagnostics: list[Diagnostic] | tuple[Diagnostic, ...] = (),
    ) -> CanonicalGraph:
        """Construct a deduplicated, deterministically sorted CanonicalGraph."""
        unique_nodes = {node.id: node for node in nodes}
        unique_edges = {edge.id: edge for edge in edges}
        sorted_nodes = tuple(unique_nodes[nid] for nid in sorted(unique_nodes))
        sorted_edges = tuple(unique_edges[eid] for eid in sorted(unique_edges))
        sorted_diags = tuple(
            sorted(
                diagnostics,
                key=lambda d: (d.source_path or "", d.line or 0, d.code, d.message),
            )
        )
        return cls(
            repository_id=repository_id,
            base_snapshot_id=base_snapshot_id,
            applied_journal_cursor=applied_journal_cursor,
            nodes=sorted_nodes,
            edges=sorted_edges,
            diagnostics=sorted_diags,
        )

    def node_map(self) -> dict[str, Node]:
        """Return a dictionary mapping node ID -> Node."""
        return {node.id: node for node in self.nodes}

    def outbound_edges(
        self,
        node_id: str,
        *,
        kinds: set[EdgeKind] | None = None,
    ) -> list[Edge]:
        """Return all edges originating from node_id, optionally filtered by EdgeKind."""
        return [
            edge
            for edge in self.edges
            if edge.source_id == node_id and (kinds is None or edge.kind in kinds)
        ]

    def inbound_edges(
        self,
        node_id: str,
        *,
        kinds: set[EdgeKind] | None = None,
    ) -> list[Edge]:
        """Return all edges pointing into node_id, optionally filtered by EdgeKind."""
        return [
            edge
            for edge in self.edges
            if edge.target_id == node_id and (kinds is None or edge.kind in kinds)
        ]

    def neighbors(
        self,
        node_id: str,
        *,
        direction: Literal["outbound", "inbound", "both"] = "both",
        kinds: set[EdgeKind] | None = None,
    ) -> list[Node]:
        """Return neighboring Node objects connected to node_id."""
        by_id = self.node_map()
        neighbor_ids: set[str] = set()
        if direction in ("outbound", "both"):
            for edge in self.outbound_edges(node_id, kinds=kinds):
                if edge.target_id in by_id:
                    neighbor_ids.add(edge.target_id)
        if direction in ("inbound", "both"):
            for edge in self.inbound_edges(node_id, kinds=kinds):
                if edge.source_id in by_id:
                    neighbor_ids.add(edge.source_id)
        return [by_id[nid] for nid in sorted(neighbor_ids)]

    def slice_subgraph(self, seed_node_ids: set[str], *, max_hops: int = 1) -> CanonicalGraph:
        """Extract a deterministic subgraph within max_hops of seed_node_ids."""
        by_id = self.node_map()
        visited: set[str] = {nid for nid in seed_node_ids if nid in by_id}
        frontier: set[str] = set(visited)

        for _ in range(max_hops):
            next_frontier: set[str] = set()
            for nid in frontier:
                for edge in self.edges:
                    if edge.source_id == nid and edge.target_id in by_id:
                        if edge.target_id not in visited:
                            next_frontier.add(edge.target_id)
                    elif (
                        edge.target_id == nid
                        and edge.source_id in by_id
                        and edge.source_id not in visited
                    ):
                        next_frontier.add(edge.source_id)
            visited.update(next_frontier)
            frontier = next_frontier
            if not frontier:
                break

        kept_nodes = [by_id[nid] for nid in sorted(visited)]
        kept_edges = [
            edge for edge in self.edges if edge.source_id in visited and edge.target_id in visited
        ]
        return CanonicalGraph.build(
            repository_id=self.repository_id,
            base_snapshot_id=self.base_snapshot_id,
            applied_journal_cursor=self.applied_journal_cursor,
            nodes=kept_nodes,
            edges=kept_edges,
            diagnostics=list(self.diagnostics),
        )

    def to_deterministic_json(self, *, indent: int = 2) -> str:
        """Serialize the graph to a deterministic, schema-compliant JSON string."""
        canonical = CanonicalGraph.build(
            repository_id=self.repository_id,
            base_snapshot_id=self.base_snapshot_id,
            applied_journal_cursor=self.applied_journal_cursor,
            nodes=self.nodes,
            edges=self.edges,
            diagnostics=self.diagnostics,
        )
        payload = canonical.model_dump(mode="json")
        # Strip empty attributes on Edge if not populated so output stays compact and schema-valid
        for edge_dict in payload.get("edges", []):
            if isinstance(edge_dict, dict) and not edge_dict.get("attributes"):
                edge_dict.pop("attributes", None)
        for diag_dict in payload.get("diagnostics", []):
            if isinstance(diag_dict, dict) and diag_dict.get("line") is None:
                diag_dict.pop("line", None)
        return json.dumps(payload, indent=indent, sort_keys=True) + "\n"
