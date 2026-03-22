"""Watchlist endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.models.watchlist import WatchlistItem
from app.schemas.watchlist import WatchlistCreate, WatchlistPatch, WatchlistResponse
from app.services.alert_service import determine_action_needed

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_user_watchlist_item(
    item_id: int,
    user: User,
    db: AsyncSession,
) -> WatchlistItem:
    """Fetch a watchlist item ensuring it belongs to the current user."""
    result = await db.execute(
        select(WatchlistItem).where(
            WatchlistItem.id == item_id,
            WatchlistItem.user_id == user.id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Watchlist item not found",
        )
    return item


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[WatchlistResponse])
async def list_watchlist(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[WatchlistItem]:
    """List all watchlist items for the current user."""
    result = await db.execute(
        select(WatchlistItem)
        .where(WatchlistItem.user_id == user.id)
        .order_by(WatchlistItem.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/", response_model=WatchlistResponse, status_code=status.HTTP_201_CREATED)
async def add_to_watchlist(
    body: WatchlistCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WatchlistItem:
    """Add a stock to the watchlist."""
    # Check for duplicates
    result = await db.execute(
        select(WatchlistItem).where(
            WatchlistItem.user_id == user.id,
            WatchlistItem.stock_symbol == body.stock_symbol.upper().strip(),
            WatchlistItem.exchange == body.exchange.upper().strip(),
        )
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{body.stock_symbol} on {body.exchange} is already in your watchlist",
        )

    item = WatchlistItem(
        user_id=user.id,
        stock_symbol=body.stock_symbol.upper().strip(),
        stock_name=body.stock_name.strip(),
        exchange=body.exchange.upper().strip(),
        target_buy_price=body.target_buy_price,
        lower_mid_range_1=body.lower_mid_range_1,
        lower_mid_range_2=body.lower_mid_range_2,
        upper_mid_range_1=body.upper_mid_range_1,
        upper_mid_range_2=body.upper_mid_range_2,
        base_level=body.base_level,
        top_level=body.top_level,
        notes=body.notes,
    )

    # Calculate initial action_needed (will be "N" until current_price is fetched)
    item.action_needed = determine_action_needed(item.current_price, item)

    db.add(item)
    await db.flush()
    await db.refresh(item)
    return item


@router.patch("/{item_id}", response_model=WatchlistResponse)
async def update_watchlist_item(
    item_id: int,
    body: WatchlistPatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WatchlistItem:
    """Update a watchlist item (target price, range levels, notes, etc.)."""
    item = await _get_user_watchlist_item(item_id, user, db)

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(item, key, value)

    # Recalculate action_needed when range levels change
    item.action_needed = determine_action_needed(item.current_price, item)

    await db.flush()
    await db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_watchlist(
    item_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a stock from the watchlist."""
    item = await _get_user_watchlist_item(item_id, user, db)
    await db.delete(item)
    await db.flush()
