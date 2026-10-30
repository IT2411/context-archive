"""Tests for FastAPI order endpoints."""

from __future__ import annotations

import asyncio

from app.main import create_order
from app.schemas import OrderCreateRequest


def test_create_order_endpoint() -> None:
    """Verify create_order returns calculated total_cents."""
    req = OrderCreateRequest(sku="ITEM-9", quantity=3)
    res = asyncio.run(create_order(req, session={"status": "test"}))
    assert res.total_cents == 1500
