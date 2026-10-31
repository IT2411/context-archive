"""Integration tests for canonical graph determinism, provenance accuracy, and test linking."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from context_archive.adapters.python_ast import PythonAstAdapter
from context_archive.config import load_config
from context_archive.model.graph import CanonicalGraph
from context_archive.scanner.walker import scan_repository

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.integration
def test_graph_determinism_across_shuffled_file_orders(fixtures_dir: Path) -> None:
    """Verify serialized graph.json is byte-for-byte identical regardless of file input order."""
    py_lib = fixtures_dir / "fixture_py_lib"
    cfg = load_config(py_lib)
    scan_rep = scan_repository(py_lib, cfg)
    adapter = PythonAstAdapter()

    forward_res = adapter.extract_repository(py_lib, list(scan_rep.files))
    reverse_res = adapter.extract_repository(py_lib, list(reversed(scan_rep.files)))

    graph_forward = CanonicalGraph.build(
        repository_id=scan_rep.repository_id,
        base_snapshot_id="snapshot-0001",
        nodes=forward_res.nodes,
        edges=forward_res.edges,
        diagnostics=forward_res.diagnostics,
    )
    graph_reverse = CanonicalGraph.build(
        repository_id=scan_rep.repository_id,
        base_snapshot_id="snapshot-0001",
        nodes=reverse_res.nodes,
        edges=reverse_res.edges,
        diagnostics=reverse_res.diagnostics,
    )

    assert graph_forward.to_deterministic_json() == graph_reverse.to_deterministic_json()

    # Verify key nodes, provenance lines, and TESTED_BY edges on fixture_py_lib
    by_id = graph_forward.node_map()
    calc_id = "sym:py:src/sample_lib/calculator.py:calculate_total"
    round_id = "sym:py:src/sample_lib/utils.py:round_currency"
    test_id = "sym:py:tests/test_calculator.py:test_calculate_total_with_tax"

    assert calc_id in by_id
    assert round_id in by_id
    assert test_id in by_id
    assert by_id[test_id].kind == "Test"

    # Provenance accuracy check against actual source lines in calculator.py
    calc_lines = (
        (py_lib / "src" / "sample_lib" / "calculator.py").read_text(encoding="utf-8").splitlines()
    )
    calc_prov = by_id[calc_id].provenance
    assert calc_lines[calc_prov.line_start - 1].startswith("def calculate_total(")

    edge_ids = {e.id for e in graph_forward.edges}
    assert f"edge:CALLS:{calc_id}->{round_id}" in edge_ids
    assert f"edge:CALLS:{test_id}->{calc_id}" in edge_ids
    assert f"edge:TESTED_BY:{calc_id}->{test_id}" in edge_ids
