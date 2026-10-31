"""Unit tests for FastAPI route, Depends, and Pydantic BaseModel contract extraction."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from context_archive.adapters.fastapi import FastApiContractExtractor
from context_archive.adapters.python_ast import PythonAstAdapter
from context_archive.config import load_config
from context_archive.scanner.walker import scan_repository

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_fastapi_and_pydantic_extractor_on_fixture(fixtures_dir: Path) -> None:
    """Verify FastAPI routes, Pydantic schemas, and Depends edges are extracted accurately."""
    target = fixtures_dir / "fixture_fastapi"
    cfg = load_config(target)
    scan_rep = scan_repository(target, cfg)

    py_res = PythonAstAdapter().extract_repository(target, scan_rep.files)
    extractor = FastApiContractExtractor()
    assert extractor.adapter_id == "fastapi_pydantic:1.0"
    res = extractor.extract_repository(target, scan_rep.files, existing_nodes=py_res.nodes)

    by_id = {n.id: n for n in res.nodes}
    endpoint_id = "sym:endpoint:py:app/main.py:POST:/orders"
    req_schema_id = "sym:schema:py:app/schemas.py:OrderCreateRequest"
    resp_schema_id = "sym:schema:py:app/schemas.py:OrderResponse"

    assert endpoint_id in by_id
    ep_node = by_id[endpoint_id]
    assert ep_node.kind == "Endpoint"
    assert ep_node.attributes["http_method"] == "POST"
    assert ep_node.attributes["route_path"] == "/orders"
    assert ep_node.attributes["response_model"] == "OrderResponse"
    assert ep_node.attributes["status_code"] == 201

    assert req_schema_id in by_id
    assert resp_schema_id in by_id
    assert by_id[resp_schema_id].kind == "Schema"
    assert "total_cents: int" in by_id[resp_schema_id].attributes["signature"]

    edge_ids = {e.id for e in res.edges}
    handler_id = "sym:py:app/main.py:create_order"
    dep_id = "sym:py:app/main.py:get_db_session"
    assert f"edge:EXPOSES:{handler_id}->{endpoint_id}" in edge_ids
    assert f"edge:VALIDATES_WITH:{endpoint_id}->{req_schema_id}" in edge_ids
    assert f"edge:VALIDATES_WITH:{endpoint_id}->{resp_schema_id}" in edge_ids
    assert f"edge:DEPENDS_ON:{endpoint_id}->{dep_id}" in edge_ids
