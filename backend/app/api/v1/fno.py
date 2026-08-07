"""F&O (Futures & Options) API — position tracking and P&L."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, verify_portfolio_ownership
from app.api.errors import map_value_error
from app.database import get_db
from app.models.fno_position import FnoPosition
from app.models.portfolio import Portfolio
from app.models.user import User
from app.schemas.fno import (
    FnoPnlSummary,
    FnoPositionCreate,
    FnoPositionResponse,
    FnoPositionUpdate,
)
from app.services.fno_service import (
    _calculate_position_pnl,
    create_position,
    delete_position,
    get_pnl_summary,
    get_positions,
    update_position,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _verify_position_ownership(
    position_id: int,
    user: User,
    db: AsyncSession,
) -> FnoPosition:
    """Fetch an F&O position, verifying it belongs to one of the user's portfolios."""
    from sqlalchemy import select

    result = await db.execute(
        select(FnoPosition)
        .join(Portfolio, FnoPosition.portfolio_id == Portfolio.id)
        .where(FnoPosition.id == position_id, Portfolio.user_id == user.id)
    )
    position = result.scalar_one_or_none()
    if position is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="F&O position not found",
        )
    return position


def _position_out(pos: FnoPosition, unrealized_pnl: float | None) -> dict:
    """Serialise an F&O position for API responses (single source of truth)."""
    return {
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
        "unrealized_pnl": unrealized_pnl,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/positions/{portfolio_id}", response_model=list[FnoPositionResponse])
async def list_positions(
    portfolio_id: int,
    status_filter: str | None = Query(
        default=None, alias="status", description="Filter by status: OPEN, CLOSED, EXPIRED"
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List all F&O positions for a portfolio, optionally filtered by status."""
    await verify_portfolio_ownership(portfolio_id, user, db)

    positions = await get_positions(portfolio_id, db, status_filter=status_filter)

    # Enrich with unrealized P&L
    return [
        _position_out(pos, _calculate_position_pnl(pos)["unrealized_pnl"])
        for pos in positions
    ]


@router.post("/positions", response_model=FnoPositionResponse, status_code=status.HTTP_201_CREATED)
async def add_position(
    body: FnoPositionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Add a new F&O position (futures or options).

    For options (CE/PE), ``strike_price`` is required.
    For futures (FUT), ``strike_price`` should be null.
    """
    await verify_portfolio_ownership(body.portfolio_id, user, db)

    # Validate: options need strike price
    if body.instrument_type in ("CE", "PE") and body.strike_price is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="strike_price is required for options (CE/PE)",
        )

    position = await create_position(
        portfolio_id=body.portfolio_id,
        data=body.model_dump(),
        db=db,
    )

    # A freshly created position has no exit/current price yet, so no P&L.
    return _position_out(position, None)


@router.put("/positions/{position_id}", response_model=FnoPositionResponse)
async def modify_position(
    position_id: int,
    body: FnoPositionUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update an F&O position — set exit price, close position, update current price."""
    await _verify_position_ownership(position_id, user, db)

    try:
        position = await update_position(
            position_id=position_id,
            data=body.model_dump(exclude_unset=True),
            db=db,
        )
    except ValueError as e:
        raise map_value_error(e) from e

    pnl = _calculate_position_pnl(position)
    return _position_out(position, pnl["unrealized_pnl"])


@router.delete("/positions/{position_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_position(
    position_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete an F&O position."""
    await _verify_position_ownership(position_id, user, db)

    try:
        await delete_position(position_id, db)
    except ValueError as e:
        raise map_value_error(e) from e


@router.get("/pnl/{portfolio_id}", response_model=FnoPnlSummary)
async def fno_pnl(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get F&O P&L summary for a portfolio.

    Includes total realized P&L (closed positions), total unrealized P&L
    (open positions), and individual position details.
    """
    await verify_portfolio_ownership(portfolio_id, user, db)
    return await get_pnl_summary(portfolio_id, db)
