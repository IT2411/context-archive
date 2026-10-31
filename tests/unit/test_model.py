"""Unit tests for canonical IDs, Provenance, and CanonicalGraph query primitives."""

from __future__ import annotations

import json

import pytest

from context_archive.model.graph import CanonicalGraph, Diagnostic, Edge, Node
from context_archive.model.ids import (
    make_edge_id,
    make_file_id,
    make_module_id,
    make_symbol_id,
    normalize_posix_path,
)
from context_archive.model.provenance import Provenance


@pytest.mark.unit
def test_canonical_id_generators_normalize_windows_and_posix_paths() -> None:
    """Verify ID generators normalize backslashes and leading './' segments."""
    assert normalize_posix_path(r".\src\sample_lib\calculator.py") == "src/sample_lib/calculator.py"
    assert normalize_posix_path("") == "."
    assert make_file_id(r"src\app\main.py") == "file:src/app/main.py"
    assert make_module_id("py", r"src\app\main.py", "app.main") == "mod:py:src/app/main.py:app.main"
    assert (
        make_symbol_id("py", r"src\app\main.py", "OrderService.create")
        == "sym:py:src/app/main.py:OrderService.create"
    )
    assert make_edge_id("CALLS", "sym:a", "sym:b") == "edge:CALLS:sym:a->sym:b"


@pytest.mark.unit
def test_provenance_normalizes_path_and_line_bounds() -> None:
    """Verify Provenance normalizes Windows paths and clamps line_end >= line_start."""
    prov = Provenance(
        source_path=r".\src\pkg\mod.py",
        line_start=20,
        line_end=15,
        extractor="python_ast:1.0",
    )
    assert prov.source_path == "src/pkg/mod.py"
    assert prov.line_start == 20
    assert prov.line_end == 20


@pytest.mark.unit
def test_canonical_graph_sorting_neighbors_and_subgraph_slicing() -> None:
    """Verify CanonicalGraph sorts deterministically and supports neighbor/subgraph queries."""
    prov = Provenance(
        source_path="src/mod.py",
        line_start=1,
        line_end=10,
        extractor="python_ast:1.0",
    )
    node_c = Node(
        id="sym:py:src/mod.py:c",
        kind="Function",
        name="c",
        qualified_name="mod.c",
        provenance=prov,
    )
    node_a = Node(
        id="sym:py:src/mod.py:a",
        kind="Function",
        name="a",
        qualified_name="mod.a",
        provenance=prov,
    )
    node_b = Node(
        id="sym:py:src/mod.py:b",
        kind="Function",
        name="b",
        qualified_name="mod.b",
        provenance=prov,
    )
    edge_ab = Edge(
        id=make_edge_id("CALLS", node_a.id, node_b.id),
        kind="CALLS",
        source_id=node_a.id,
        target_id=node_b.id,
        provenance=prov,
    )
    edge_bc = Edge(
        id=make_edge_id("CALLS", node_b.id, node_c.id),
        kind="CALLS",
        source_id=node_b.id,
        target_id=node_c.id,
        provenance=prov,
    )
    diag = Diagnostic(
        code="test_diag",
        severity="info",
        message="Sample diagnostic",
        source_path="src/mod.py",
        line=5,
    )

    graph = CanonicalGraph.build(
        repository_id="repo:sha256:0123456789abcdef0123456789abcdef",
        base_snapshot_id="snapshot-0001",
        nodes=[node_c, node_a, node_b],
        edges=[edge_bc, edge_ab],
        diagnostics=[diag],
    )

    # Nodes must be sorted lexicographically
    assert [n.id for n in graph.nodes] == [node_a.id, node_b.id, node_c.id]

    # Neighbor queries
    assert [n.id for n in graph.neighbors(node_a.id, direction="outbound")] == [node_b.id]
    assert [n.id for n in graph.neighbors(node_b.id, direction="inbound")] == [node_a.id]
    assert [n.id for n in graph.neighbors(node_b.id, direction="both")] == [node_a.id, node_c.id]

    # 1-hop subgraph from node_a includes node_a and node_b, but not node_c
    sub_1 = graph.slice_subgraph({node_a.id}, max_hops=1)
    assert [n.id for n in sub_1.nodes] == [node_a.id, node_b.id]
    assert [e.id for e in sub_1.edges] == [edge_ab.id]

    # 2-hop subgraph from node_a includes all 3 nodes
    sub_2 = graph.slice_subgraph({node_a.id}, max_hops=2)
    assert [n.id for n in sub_2.nodes] == [node_a.id, node_b.id, node_c.id]

    raw_json = graph.to_deterministic_json()
    parsed = json.loads(raw_json)
    assert parsed["schema_version"] == "1.0.0"
    assert len(parsed["nodes"]) == 3
