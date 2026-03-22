"""Alert management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.alert import Alert
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.user import User
from app.models.watchlist import WatchlistItem
from app.schemas.alert import (
    AlertChannelUpdate,
    AlertCreate,
    AlertResponse,
    AlertUpdate,
)
from app.services.alert_service import check_all_alerts_for_user

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_user_alert(
    alert_id: int,
    user: User,
    db: AsyncSession,
) -> Alert:
    """Fetch an alert ensuring it belongs to the current user."""
    result = await db.execute(
        select(Alert).where(Alert.id == alert_id, Alert.user_id == user.id)
    )
    alert = result.scalar_one_or_none()
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found",
        )
    return alert


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[AlertResponse])
async def list_alerts(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(200, ge=1, le=1000, description="Max records to return"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Alert]:
    """List all alerts for the current user."""
    result = await db.execute(
        select(Alert)
        .where(Alert.user_id == user.id)
        .order_by(Alert.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


@router.post("/", response_model=AlertResponse, status_code=status.HTTP_201_CREATED)
async def create_alert(
    body: AlertCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Alert:
    """Create a new alert.

    At least one of ``holding_id`` or ``watchlist_item_id`` should be provided
    to associate the alert with a specific stock.
    """
    # Validate holding ownership if provided
    if body.holding_id is not None:
        result = await db.execute(
            select(Holding)
            .join(Portfolio, Holding.portfolio_id == Portfolio.id)
            .where(Holding.id == body.holding_id, Portfolio.user_id == user.id)
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Holding not found or does not belong to the current user",
            )

    # Validate watchlist item ownership if provided
    if body.watchlist_item_id is not None:
        result = await db.execute(
            select(WatchlistItem).where(
                WatchlistItem.id == body.watchlist_item_id,
                WatchlistItem.user_id == user.id,
            )
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Watchlist item not found or does not belong to the current user",
            )

    alert = Alert(
        user_id=user.id,
        holding_id=body.holding_id,
        watchlist_item_id=body.watchlist_item_id,
        alert_type=body.alert_type,
        condition=body.condition,
        is_active=body.is_active,
        channels=body.channels,
    )
    db.add(alert)
    await db.flush()
    await db.refresh(alert)
    return alert


@router.put("/{alert_id}", response_model=AlertResponse)
async def update_alert(
    alert_id: int,
    body: AlertUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Alert:
    """Update an alert's type, condition, or active status."""
    alert = await _get_user_alert(alert_id, user, db)

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(alert, key, value)

    await db.flush()
    await db.refresh(alert)
    return alert


@router.put("/{alert_id}/channels", response_model=AlertResponse)
async def update_alert_channels(
    alert_id: int,
    body: AlertChannelUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Alert:
    """Update the notification channels for a specific alert."""
    alert = await _get_user_alert(alert_id, user, db)

    # Validate channels
    valid_channels = {"in_app", "email", "telegram", "whatsapp", "sms"}
    for channel in body.channels:
        if channel not in valid_channels:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid channel '{channel}'. Valid: {sorted(valid_channels)}",
            )

    alert.channels = body.channels
    await db.flush()
    await db.refresh(alert)
    return alert


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(
    alert_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete an alert."""
    alert = await _get_user_alert(alert_id, user, db)
    await db.delete(alert)
    await db.flush()


@router.get("/history")
async def alert_history(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get notification log / history.

    Returns all triggered alerts (those with a last_triggered timestamp),
    ordered by most recent trigger first, plus runs a live check of all
    current alerts.
    """
    # Historical triggers
    result = await db.execute(
        select(Alert)
        .where(
            Alert.user_id == user.id,
            Alert.last_triggered.isnot(None),
        )
        .order_by(Alert.last_triggered.desc())
    )
    triggered_alerts = result.scalars().all()

    history: list[dict] = []
    for a in triggered_alerts:
        # Try to get the associated stock symbol
        stock_symbol: str | None = None
        if a.holding_id is not None:
            h_result = await db.execute(
                select(Holding.stock_symbol).where(Holding.id == a.holding_id)
            )
            row = h_result.first()
            stock_symbol = row[0] if row else None
        elif a.watchlist_item_id is not None:
            w_result = await db.execute(
                select(WatchlistItem.stock_symbol).where(
                    WatchlistItem.id == a.watchlist_item_id
                )
            )
            row = w_result.first()
            stock_symbol = row[0] if row else None

        history.append(
            {
                "alert_id": a.id,
                "alert_type": a.alert_type,
                "condition": a.condition,
                "triggered_at": a.last_triggered.isoformat() if a.last_triggered else None,
                "stock_symbol": stock_symbol,
                "message": f"Alert {a.alert_type} triggered for {stock_symbol or 'unknown'}",
            }
        )

    # Also run a live check
    live_triggered = await check_all_alerts_for_user(user.id, db)

    return {
        "history": history,
        "live_triggered": live_triggered,
    }
