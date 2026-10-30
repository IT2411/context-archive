"""Core pricing calculator module."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .utils import round_currency


@dataclass(frozen=True)
class LineItem:
    """Single purchasable line item."""

    sku: str
    unit_price: Decimal
    quantity: int = 1


def calculate_total(items: list[LineItem], tax_rate: Decimal = Decimal("0.00")) -> Decimal:
    """Calculate net checkout total including item quantities and applicable tax."""
    subtotal = sum((item.unit_price * item.quantity for item in items), start=Decimal("0.00"))
    tax = subtotal * tax_rate
    return round_currency(subtotal + tax)
