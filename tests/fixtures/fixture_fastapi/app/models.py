"""Database entity definitions."""

from __future__ import annotations


class DeclarativeBase:
    """Lightweight declarative base stub for static AST analysis."""


class OrderEntity(DeclarativeBase):
    """Persistent customer order record."""

    __tablename__ = "orders"

    id: int
    sku: str
    quantity: int
    total_cents: int
