"""Unit tests for SQLAlchemy and SQLModel DataEntity extraction."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from context_archive.adapters.sqlalchemy import SqlAlchemyEntityExtractor
from context_archive.config import load_config
from context_archive.scanner.walker import scan_repository

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_sqlalchemy_entity_and_writes_edge_extraction(fixtures_dir: Path) -> None:
    """Verify OrderEntity table, columns, and WRITES edges from create_order are extracted."""
    target = fixtures_dir / "fixture_fastapi"
    cfg = load_config(target)
    scan_rep = scan_repository(target, cfg)

    extractor = SqlAlchemyEntityExtractor()
    assert extractor.adapter_id == "sqlalchemy_entity:1.0"
    res = extractor.extract_repository(target, scan_rep.files)

    by_id = {n.id: n for n in res.nodes}
    entity_id = "sym:entity:py:app/models.py:OrderEntity"
    assert entity_id in by_id

    ent_node = by_id[entity_id]
    assert ent_node.kind == "DataEntity"
    assert ent_node.attributes["table_name"] == "orders"
    assert "total_cents: int" in ent_node.attributes["signature"]

    edge_ids = {e.id for e in res.edges}
    assert f"edge:WRITES:sym:py:app/main.py:create_order->{entity_id}" in edge_ids
