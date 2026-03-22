"""Stop-loss tracking — alert when stocks approach stop-loss levels."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.holding import Holding
from app.models.portfolio import Portfolio


@dataclass
class StopLossStatus:
    holding_id: int
    stock_symbol: str
    stock_name: str
    current_price: float | None
    stop_loss_price: float
    distance_pct: float | None  # How far from stop-loss (negative = below)
    is_triggered: bool  # Price <= stop_loss


async def get_stop_loss_holdings(
    portfolio_id: int, db: AsyncSession
) -> list[StopLossStatus]:
    """Get all holdings with stop-loss levels and their current status."""
    result = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio_id)
    )
    holdings = result.scalars().all()

    statuses = []
    for h in holdings:
        custom = h.custom_fields or {}
        sl_price = custom.get("stop_loss_price")
        if sl_price is None:
            continue

        sl_price = float(sl_price)
        distance = None
        triggered = False

        if h.current_price and sl_price > 0:
            distance = ((float(h.current_price) - sl_price) / sl_price) * 100
            triggered = float(h.current_price) <= sl_price

        statuses.append(StopLossStatus(
            holding_id=h.id,
            stock_symbol=h.stock_symbol,
            stock_name=h.stock_name or h.stock_symbol,
            current_price=float(h.current_price) if h.current_price is not None else None,
            stop_loss_price=sl_price,
            distance_pct=round(distance, 2) if distance is not None else None,
            is_triggered=triggered,
        ))

    return statuses


async def set_stop_loss(
    holding_id: int, stop_loss_price: float, db: AsyncSession, *, user_id: int | None = None
) -> None:
    """Set or update stop-loss price for a holding (stored in custom_fields)."""
    if stop_loss_price <= 0:
        raise ValueError("Stop-loss price must be positive")
    query = select(Holding).where(Holding.id == holding_id)
    if user_id is not None:
        query = query.join(Portfolio).where(Portfolio.user_id == user_id)
    result = await db.execute(query)
    holding = result.scalar_one_or_none()
    if not holding:
        raise ValueError(f"Holding {holding_id} not found")

    custom = dict(holding.custom_fields or {})
    custom["stop_loss_price"] = stop_loss_price
    holding.custom_fields = custom
    await db.flush()


async def remove_stop_loss(holding_id: int, db: AsyncSession, *, user_id: int | None = None) -> None:
    """Remove stop-loss for a holding."""
    query = select(Holding).where(Holding.id == holding_id)
    if user_id is not None:
        query = query.join(Portfolio).where(Portfolio.user_id == user_id)
    result = await db.execute(query)
    holding = result.scalar_one_or_none()
    if not holding:
        raise ValueError(f"Holding {holding_id} not found")

    custom = dict(holding.custom_fields or {})
    custom.pop("stop_loss_price", None)
    holding.custom_fields = custom
    await db.flush()
