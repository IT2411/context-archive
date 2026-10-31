"""Unit tests for the TypeScript/JavaScript adapter and API client call site extraction."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from context_archive.adapters.typescript import TypeScriptAdapter
from context_archive.config import load_config
from context_archive.model.graph import Node
from context_archive.model.provenance import Provenance
from context_archive.scanner.walker import scan_repository

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_typescript_exports_interfaces_imports_and_api_client_linking(
    tmp_path: Path,
) -> None:
    """Verify TS interfaces, exported functions, imports, and fetch/axios CONSUMES edges."""
    web_dir = tmp_path / "src" / "web"
    web_dir.mkdir(parents=True)
    (web_dir / "types.ts").write_text(
        "export interface OrderPayload {\n  sku: string;\n  quantity: number;\n}\n",
        encoding="utf-8",
    )
    (web_dir / "api.ts").write_text(
        "import { OrderPayload } from './types';\n\n"
        "export async function submitOrder(payload: OrderPayload): Promise<Response> {\n"
        "  return fetch('/orders', { method: 'POST' });\n"
        "}\n\n"
        "export const fetchOrderById = async (orderId: number): Promise<void> => {\n"
        "  await axios.get(`/orders/${orderId}`);\n"
        "};\n",
        encoding="utf-8",
    )

    ep_post = Node(
        id="sym:endpoint:py:app/main.py:POST:/orders",
        kind="Endpoint",
        name="POST /orders",
        qualified_name="POST /orders",
        attributes={"http_method": "POST", "route_path": "/orders"},
        provenance=Provenance(
            source_path="app/main.py",
            line_start=10,
            line_end=20,
            extractor="fastapi_pydantic:1.0",
        ),
    )
    ep_get = Node(
        id="sym:endpoint:py:app/main.py:GET:/orders/{order_id}",
        kind="Endpoint",
        name="GET /orders/{order_id}",
        qualified_name="GET /orders/{order_id}",
        attributes={"http_method": "GET", "route_path": "/orders/{order_id}"},
        provenance=Provenance(
            source_path="app/main.py",
            line_start=25,
            line_end=35,
            extractor="fastapi_pydantic:1.0",
        ),
    )

    cfg = load_config(tmp_path)
    scan_rep = scan_repository(tmp_path, cfg)
    adapter = TypeScriptAdapter()
    assert adapter.adapter_id == "typescript:1.0"
    res = adapter.extract_repository(
        tmp_path,
        scan_rep.files,
        existing_nodes=(ep_post, ep_get),
    )

    by_id = {n.id: n for n in res.nodes}
    assert "sym:schema:ts:src/web/types.ts:OrderPayload" in by_id
    assert "sym:ts:src/web/api.ts:submitOrder" in by_id
    assert "sym:ts:src/web/api.ts:fetchOrderById" in by_id

    edges_by_id = {e.id: e for e in res.edges}
    imp_edge_id = "edge:IMPORTS:mod:ts:src/web/api.ts:web.api->mod:ts:src/web/types.ts:web.types"
    assert imp_edge_id in edges_by_id

    consumes_post_id = (
        "edge:CONSUMES:sym:ts:src/web/api.ts:submitOrder->"
        "sym:endpoint:py:app/main.py:POST:/orders"
    )
    assert consumes_post_id in edges_by_id
    assert edges_by_id[consumes_post_id].provenance.evidence_kind == "deterministic"
    assert edges_by_id[consumes_post_id].provenance.confidence == "high"

    consumes_get_id = (
        "edge:CONSUMES:sym:ts:src/web/api.ts:fetchOrderById->"
        "sym:endpoint:py:app/main.py:GET:/orders/{order_id}"
    )
    assert consumes_get_id in edges_by_id
    assert edges_by_id[consumes_get_id].provenance.evidence_kind == "heuristic"
    assert edges_by_id[consumes_get_id].provenance.confidence == "medium"
