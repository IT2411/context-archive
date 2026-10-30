"""FastAPI routes and dependency wiring."""

from __future__ import annotations

from typing import Any

from app.models import OrderEntity
from app.schemas import OrderCreateRequest, OrderResponse


class FastAPI:
    """Minimal FastAPI stub for static AST decorator inspection."""

    def get(self, path: str, **kwargs: Any) -> Any:
        def decorator(func: Any) -> Any:
            return func

        return decorator

    def post(self, path: str, **kwargs: Any) -> Any:
        def decorator(func: Any) -> Any:
            return func

        return decorator


def Depends(dependency: Any) -> Any:
    """Minimal Depends marker for static AST inspection."""
    return dependency


app = FastAPI()


def get_db_session() -> dict[str, str]:
    """Provide database session dependency."""
    return {"status": "connected"}


@app.post("/orders", response_model=OrderResponse, status_code=201)
async def create_order(
    payload: OrderCreateRequest,
    session: dict[str, str] = Depends(get_db_session),
) -> OrderResponse:
    """Create a customer order and return the persisted representation."""
    _ = (OrderEntity, session)
    return OrderResponse(
        order_id=1,
        sku=payload.sku,
        quantity=payload.quantity,
        total_cents=payload.quantity * 500,
    )
