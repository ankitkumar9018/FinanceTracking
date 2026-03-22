"""Holdings CRUD + manual data entry endpoints."""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import update as sa_update

from app.api.deps import get_current_user
from app.database import get_db
from app.models.alert import Alert
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.holding import HoldingCreate, HoldingPatch, HoldingResponse
from app.services.alert_service import determine_action_needed
from app.services.market_data_service import fetch_current_price

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _verify_portfolio_ownership(
    portfolio_id: int,
    user: User,
    db: AsyncSession,
) -> Portfolio:
    """Ensure the portfolio exists and belongs to the user."""
    result = await db.execute(
        select(Portfolio).where(
            Portfolio.id == portfolio_id,
            Portfolio.user_id == user.id,
        )
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portfolio not found or does not belong to the current user",
        )
    return portfolio


async def _get_user_holding(
    holding_id: int,
    user: User,
    db: AsyncSession,
) -> Holding:
    """Fetch a holding, verifying it belongs to one of the user's portfolios."""
    result = await db.execute(
        select(Holding)
        .join(Portfolio, Holding.portfolio_id == Portfolio.id)
        .where(Holding.id == holding_id, Portfolio.user_id == user.id)
    )
    holding = result.scalar_one_or_none()
    if holding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Holding not found",
        )
    return holding


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[HoldingResponse])
async def list_holdings(
    portfolio_id: int | None = Query(default=None, description="Filter by portfolio"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(500, ge=1, le=1000, description="Max records to return"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Holding]:
    """List holdings, optionally filtered by portfolio_id."""
    stmt = (
        select(Holding)
        .join(Portfolio, Holding.portfolio_id == Portfolio.id)
        .where(Portfolio.user_id == user.id)
    )
    if portfolio_id is not None:
        stmt = stmt.where(Holding.portfolio_id == portfolio_id)

    stmt = stmt.order_by(Holding.stock_symbol).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("/", response_model=HoldingResponse, status_code=status.HTTP_201_CREATED)
async def create_holding(
    body: HoldingCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Holding:
    """Add a stock manually with all range levels."""
    await _verify_portfolio_ownership(body.portfolio_id, user, db)

    symbol = body.stock_symbol.upper().strip()
    exchange = body.exchange.upper().strip()

    # Check if this stock already exists in the portfolio
    dup_result = await db.execute(
        select(Holding).where(
            Holding.portfolio_id == body.portfolio_id,
            Holding.stock_symbol == symbol,
            Holding.exchange == exchange,
        )
    )
    existing = dup_result.scalar_one_or_none()

    # Try to fetch current price
    current_price = None
    try:
        quote = await fetch_current_price(symbol, exchange)
        current_price = quote.get("current_price")
    except Exception:
        logger.debug("Failed to fetch current price for %s:%s", symbol, exchange, exc_info=True)

    if existing is not None:
        # Merge: weighted average price, add quantities
        old_qty = float(existing.cumulative_quantity)
        old_avg = float(existing.average_price)
        new_qty = float(body.cumulative_quantity)
        new_avg = float(body.average_price)

        total_qty = old_qty + new_qty
        if total_qty > 0:
            existing.average_price = round(
                ((old_qty * old_avg) + (new_qty * new_avg)) / total_qty, 2
            )
        existing.cumulative_quantity = total_qty

        if current_price is not None:
            existing.current_price = current_price

        # Update optional fields only if provided
        for field in (
            "sector", "notes", "base_level", "lower_mid_range_1",
            "lower_mid_range_2", "upper_mid_range_1", "upper_mid_range_2",
            "top_level",
        ):
            val = getattr(body, field, None)
            if val is not None:
                setattr(existing, field, val)

        existing.action_needed = determine_action_needed(existing.current_price, existing)

        await db.flush()

        # Record BUY transaction for the new purchase
        tx = Transaction(
            holding_id=existing.id,
            transaction_type="BUY",
            date=date.today(),
            quantity=body.cumulative_quantity,
            price=body.average_price,
            brokerage=0,
            source="MANUAL",
        )
        db.add(tx)
        await db.flush()

        await db.refresh(existing)
        return existing

    holding = Holding(
        portfolio_id=body.portfolio_id,
        stock_symbol=symbol,
        stock_name=body.stock_name.strip() if body.stock_name else symbol,
        exchange=exchange,
        cumulative_quantity=body.cumulative_quantity,
        average_price=body.average_price,
        current_price=current_price,
        lower_mid_range_1=body.lower_mid_range_1,
        lower_mid_range_2=body.lower_mid_range_2,
        upper_mid_range_1=body.upper_mid_range_1,
        upper_mid_range_2=body.upper_mid_range_2,
        base_level=body.base_level,
        top_level=body.top_level,
        sector=body.sector,
        notes=body.notes,
        custom_fields=body.custom_fields or {},
        currency=body.currency,
    )

    holding.action_needed = determine_action_needed(holding.current_price, holding)

    db.add(holding)
    await db.flush()

    # Record initial BUY transaction
    tx = Transaction(
        holding_id=holding.id,
        transaction_type="BUY",
        date=date.today(),
        quantity=body.cumulative_quantity,
        price=body.average_price,
        brokerage=0,
        source="MANUAL",
    )
    db.add(tx)
    await db.flush()

    await db.refresh(holding)
    return holding


@router.get("/{holding_id}", response_model=HoldingResponse)
async def get_holding(
    holding_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Holding:
    """Get a single holding by ID."""
    return await _get_user_holding(holding_id, user, db)


@router.patch("/{holding_id}", response_model=HoldingResponse)
async def patch_holding(
    holding_id: int,
    body: HoldingPatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Holding:
    """Inline edit any field: range levels, notes, custom_fields, etc."""
    holding = await _get_user_holding(holding_id, user, db)

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(holding, key, value)

    # Recalculate action_needed whenever range levels change
    holding.action_needed = determine_action_needed(holding.current_price, holding)

    await db.flush()
    await db.refresh(holding)
    return holding


@router.delete("/{holding_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_holding(
    holding_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a holding and all its transactions (cascade)."""
    holding = await _get_user_holding(holding_id, user, db)
    # Deactivate any alerts linked to this holding before deletion
    # (ondelete="SET NULL" would leave them orphaned and active)
    await db.execute(
        sa_update(Alert)
        .where(Alert.holding_id == holding_id)
        .values(is_active=False)
    )
    await db.delete(holding)
    await db.flush()
