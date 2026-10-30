"""Tests for sample_lib.calculator."""

from __future__ import annotations

from decimal import Decimal

from sample_lib.calculator import LineItem, calculate_total


def test_calculate_total_with_tax() -> None:
    """Verify subtotal and tax calculation."""
    items = [LineItem(sku="BOOK-1", unit_price=Decimal("10.00"), quantity=2)]
    assert calculate_total(items, tax_rate=Decimal("0.10")) == Decimal("22.00")
