"""Integration tests for full-stack contract rendering, cross-stack impact, and conformance."""

from __future__ import annotations

import json
import shutil
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from context_archive.cli import app
from context_archive.exceptions import ExitCode
from context_archive.model.graph import CanonicalGraph

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


@pytest.mark.integration
def test_fullstack_contract_handoff_cross_stack_impact_and_incremental_conformance(
    fixtures_dir: Path,
    tmp_path: Path,
) -> None:
    """Verify Section 6 contracts, Schema -> Endpoint -> TS impact, and L2==L3 equivalence."""
    repo = tmp_path / "fullstack_repo"
    shutil.copytree(fixtures_dir / "fixture_fastapi", repo)

    # Add a TypeScript frontend client calling POST /orders
    frontend_dir = repo / "frontend"
    frontend_dir.mkdir()
    client_ts = frontend_dir / "ordersClient.ts"
    client_ts.write_text(
        "export interface CreateOrderDto {\n  sku: string;\n  quantity: number;\n}\n\n"
        "export async function postNewOrder(dto: CreateOrderDto): Promise<Response> {\n"
        "  return fetch('/orders', { method: 'POST' });\n"
        "}\n",
        encoding="utf-8",
    )

    assert runner.invoke(app, ["init", str(repo), "--deterministic"]).exit_code == 0

    md_text = (repo / "PROJECT_CONTEXT.md").read_text(encoding="utf-8")
    # Section 6 must list FastAPI Endpoint, Pydantic Schemas, SQLAlchemy DataEntity, and TS Schema
    assert "[Endpoint] `POST /orders`" in md_text
    assert "[Schema] `app.schemas.OrderCreateRequest`" in md_text
    assert "[Schema] `app.schemas.OrderResponse`" in md_text
    assert "[DataEntity] `app.models.OrderEntity`" in md_text
    assert "[Schema] `frontend.ordersClient.CreateOrderDto`" in md_text

    # Modify Pydantic response schema `OrderResponse` in `app/schemas.py`
    schemas_path = repo / "app" / "schemas.py"
    schemas_src = schemas_path.read_text(encoding="utf-8")
    schemas_path.write_text(
        schemas_src + "    currency: str = 'USD'\n",
        encoding="utf-8",
    )

    # Run `ctxa diff --format json` and verify cross-stack impact:
    # Schema (OrderResponse) -> Endpoint (POST /orders) -> TS Function (postNewOrder)
    diff_res = runner.invoke(app, ["diff", str(repo), "--format", "json"])
    assert diff_res.exit_code == int(ExitCode.SUCCESS)
    diff_payload = json.loads(diff_res.stdout)

    impact_targets = {imp["target_id"]: imp for imp in diff_payload["downstream_impacts"]}
    ep_id = "sym:endpoint:py:app/main.py:POST:/orders"
    ts_caller_id = "sym:ts:frontend/ordersClient.ts:postNewOrder"
    py_handler_id = "sym:py:app/main.py:create_order"

    assert ep_id in impact_targets
    assert impact_targets[ep_id]["relationship"] == "VALIDATES_WITH"
    assert impact_targets[ep_id]["hop_distance"] == 1

    assert py_handler_id in impact_targets
    assert ts_caller_id in impact_targets
    assert impact_targets[ts_caller_id]["relationship"] == "CONSUMES"
    assert impact_targets[ts_caller_id]["hop_distance"] == 2

    # Adapter Conformance Check: L2 incremental update must match clean L3 rebuild
    assert runner.invoke(app, ["update", str(repo), "--deterministic"]).exit_code == 0

    rebuild_clone = tmp_path / "fullstack_rebuild_clone"
    shutil.copytree(
        repo,
        rebuild_clone,
        ignore=shutil.ignore_patterns(".context", "PROJECT_CONTEXT.md"),
    )
    assert runner.invoke(app, ["rebuild", str(rebuild_clone), "--deterministic"]).exit_code == 0

    inc_graph = CanonicalGraph.model_validate(
        json.loads((repo / ".context" / "graph.json").read_text(encoding="utf-8"))
    )
    reb_graph = CanonicalGraph.model_validate(
        json.loads((rebuild_clone / ".context" / "graph.json").read_text(encoding="utf-8"))
    )
    assert inc_graph.nodes == reb_graph.nodes
    assert inc_graph.edges == reb_graph.edges
