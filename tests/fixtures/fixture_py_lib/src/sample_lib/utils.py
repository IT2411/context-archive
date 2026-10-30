"""Currency rounding utilities."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def round_currency(value: Decimal) -> Decimal:
    """Round a decimal value to two decimal places using half-up rounding."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
