"""F&O (Futures & Options) Service — position management and P&L calculations."""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fno_position import FnoPosition
from app.models.portfolio import Portfolio

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Position CRUD
# ---------------------------------------------------------------------------

async def create_position(
    portfolio_id: int,
    data: dict,
    db: AsyncSession,
) -> FnoPosition:
    """Create a new F&O position."""
    position = FnoPosition(
        portfolio_id=portfolio_id,
        symbol=data["symbol"].upper().strip(),
        exchange=data.get("exchange", "NSE").upper().strip(),
        instrument_type=data["instrument_type"],
        strike_price=data.get("strike_price"),
        expiry_date=data["expiry_date"],
        lot_size=data["lot_size"],
        quantity=data["quantity"],
        entry_price=data["entry_price"],
        side=data.get("side", "BUY"),
        notes=data.get("notes"),
    )
    db.add(position)
    await db.flush()
    await db.refresh(position)
    return position


async def get_positions(
    portfolio_id: int,
    db: AsyncSession,
    status_filter: str | None = None,
) -> list[FnoPosition]:
    """Get all F&O positions for a portfolio, optionally filtered by status."""
    stmt = select(FnoPosition).where(FnoPosition.portfolio_id == portfolio_id)
    if status_filter:
        stmt = stmt.where(FnoPosition.status == status_filter.upper())
    stmt = stmt.order_by(FnoPosition.expiry_date, FnoPosition.symbol)

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_position(
    position_id: int,
    data: dict,
    db: AsyncSession,
) -> FnoPosition:
    """Update an existing F&O position (close, modify price, etc.)."""
    result = await db.execute(
        select(FnoPosition).where(FnoPosition.id == position_id)
    )
    position = result.scalar_one_or_none()
    if position is None:
        raise ValueError(f"F&O position {position_id} not found")

    for key, value in data.items():
        if value is not None and hasattr(position, key):
            setattr(position, key, value)

    await db.flush()
    await db.refresh(position)
    return position


async def delete_position(position_id: int, db: AsyncSession) -> None:
    """Delete an F&O position."""
    result = await db.execute(
        select(FnoPosition).where(FnoPosition.id == position_id)
    )
    position = result.scalar_one_or_none()
    if position is None:
        raise ValueError(f"F&O position {position_id} not found")

    await db.delete(position)
    await db.flush()


# ---------------------------------------------------------------------------
# P&L calculation
# ---------------------------------------------------------------------------

def _calculate_position_pnl(position: FnoPosition) -> dict:
    """Calculate P&L for a single F&O position.

    For BUY positions:
      - Unrealized P&L = (current_price - entry_price) * quantity * lot_size
      - Realized P&L   = (exit_price - entry_price) * quantity * lot_size

    For SELL (short) positions:
      - Unrealized P&L = (entry_price - current_price) * quantity * lot_size
      - Realized P&L   = (entry_price - exit_price) * quantity * lot_size
    """
    entry = float(position.entry_price)
    lot_size = position.lot_size
    qty = position.quantity
    total_lots = qty * lot_size

    is_long = position.side == "BUY"

    unrealized_pnl: float | None = None
    realized_pnl: float | None = None

    if position.status == "CLOSED" and position.exit_price is not None:
        exit_p = float(position.exit_price)
        if is_long:
            realized_pnl = (exit_p - entry) * total_lots
        else:
            realized_pnl = (entry - exit_p) * total_lots
    elif position.status == "OPEN" and position.current_price is not None:
        current = float(position.current_price)
        if is_long:
            unrealized_pnl = (current - entry) * total_lots
        else:
            unrealized_pnl = (entry - current) * total_lots
    elif position.status == "EXPIRED":
        if position.instrument_type in ("CE", "PE"):
            # Expired options: premium lost (buyer) or kept (seller)
            if is_long:
                realized_pnl = -entry * total_lots  # premium lost
            else:
                realized_pnl = entry * total_lots  # premium kept
        else:
            # Expired futures: use exit_price (settlement price) if available
            if position.exit_price is not None:
                exit_p = float(position.exit_price)
                if is_long:
                    realized_pnl = (exit_p - entry) * total_lots
                else:
                    realized_pnl = (entry - exit_p) * total_lots

    return {
        "unrealized_pnl": round(unrealized_pnl, 2) if unrealized_pnl is not None else None,
        "realized_pnl": round(realized_pnl, 2) if realized_pnl is not None else None,
    }


async def get_pnl_summary(portfolio_id: int, db: AsyncSession) -> dict:
    """Calculate P&L summary for all F&O positions in a portfolio.

    Returns a dict matching FnoPnlSummary schema.
    """
    positions = await get_positions(portfolio_id, db)

    total_realized = 0.0
    total_unrealized = 0.0
    open_count = 0
    closed_count = 0

    position_responses: list[dict] = []

    for pos in positions:
        pnl = _calculate_position_pnl(pos)

        if pos.status == "OPEN":
            open_count += 1
            if pnl["unrealized_pnl"] is not None:
                total_unrealized += pnl["unrealized_pnl"]
        else:
            closed_count += 1
            if pnl["realized_pnl"] is not None:
                total_realized += pnl["realized_pnl"]

        position_responses.append({
            "id": pos.id,
            "portfolio_id": pos.portfolio_id,
            "symbol": pos.symbol,
            "exchange": pos.exchange,
            "instrument_type": pos.instrument_type,
            "strike_price": float(pos.strike_price) if pos.strike_price is not None else None,
            "expiry_date": pos.expiry_date,
            "lot_size": pos.lot_size,
            "quantity": pos.quantity,
            "entry_price": float(pos.entry_price),
            "exit_price": float(pos.exit_price) if pos.exit_price is not None else None,
            "current_price": float(pos.current_price) if pos.current_price is not None else None,
            "side": pos.side,
            "status": pos.status,
            "notes": pos.notes,
            "created_at": pos.created_at,
            "updated_at": pos.updated_at,
            "unrealized_pnl": pnl["unrealized_pnl"],
        })

    return {
        "portfolio_id": portfolio_id,
        "total_realized_pnl": round(total_realized, 2),
        "total_unrealized_pnl": round(total_unrealized, 2),
        "total_pnl": round(total_realized + total_unrealized, 2),
        "open_positions": open_count,
        "closed_positions": closed_count,
        "positions": position_responses,
    }
