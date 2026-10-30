"""Pydantic request and response schemas."""

from __future__ import annotations

from pydantic import BaseModel


class OrderCreateRequest(BaseModel):
    """Payload for creating a new order."""

    sku: str
    quantity: int


class OrderResponse(BaseModel):
    """Serialized order response returned by the API."""

    order_id: int
    sku: str
    quantity: int
    total_cents: int
