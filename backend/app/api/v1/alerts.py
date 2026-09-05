"""Alert management endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, verify_holding_ownership
from app.database import get_db
from app.models.alert import Alert
from app.models.holding import Holding
from app.models.user import User
from app.models.watchlist import WatchlistItem
from app.schemas.alert import (
    AlertChannelUpdate,
    AlertCreate,
    AlertResponse,
    AlertUpdate,
    apply_once,
    validate_condition,
)
from app.services.alert_service import check_all_alerts_for_user, reset_edge_state

router = APIRouter()


def _as_utc_iso(value: datetime | None) -> str | None:
    """Serialise a (possibly naive-UTC) timestamp as an offset-aware ISO string.

    ``Alert.last_triggered`` is a naive UTC column. Emitted bare it reads as
    ``2026-08-29T10:00:00``, which JavaScript parses as *local* time — so in
    IST every alert appeared ~5.5 h in the future and the unread badge could
    never clear. Stamping the offset makes the instant unambiguous.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _as_response(alert: Alert) -> AlertResponse:
    """Build an ``AlertResponse`` with offset-aware timestamps.

    ``Alert.created_at`` / ``Alert.last_triggered`` are naive-UTC columns, and
    Pydantic serialises a naive datetime bare (``2026-08-29T10:00:00``), which
    JavaScript's ``Date`` parses as *local* time — so "Last triggered" landed on
    the wrong calendar day for any viewer whose UTC offset spanned the trigger.
    Stamping the offset on the response model (never on the ORM instance, which
    would dirty the row) makes the instant unambiguous, exactly as
    ``_as_utc_iso`` already does for /alerts/history.
    """
    response = AlertResponse.model_validate(alert)
    if response.created_at.tzinfo is None:
        response.created_at = response.created_at.replace(tzinfo=UTC)
    if response.last_triggered is not None and response.last_triggered.tzinfo is None:
        response.last_triggered = response.last_triggered.replace(tzinfo=UTC)
    return response


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
) -> list[AlertResponse]:
    """List all alerts for the current user."""
    result = await db.execute(
        select(Alert)
        .where(Alert.user_id == user.id)
        .order_by(Alert.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return [_as_response(a) for a in result.scalars().all()]


@router.post("/", response_model=AlertResponse, status_code=status.HTTP_201_CREATED)
async def create_alert(
    body: AlertCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AlertResponse:
    """Create a new alert.

    At least one of ``holding_id`` or ``watchlist_item_id`` should be provided
    to associate the alert with a specific stock.
    """
    # Validate holding ownership if provided
    if body.holding_id is not None:
        await verify_holding_ownership(body.holding_id, user, db)

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
    return _as_response(alert)


@router.put("/{alert_id}", response_model=AlertResponse)
async def update_alert(
    alert_id: int,
    body: AlertUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AlertResponse:
    """Update an alert's type, condition, one-shot flag, or active status."""
    alert = await _get_user_alert(alert_id, user, db)

    update_data = body.model_dump(exclude_unset=True)
    # ``once`` is a typed convenience for a key inside the condition JSON, not
    # a column — merge it rather than setattr-ing a stray attribute.
    once = update_data.pop("once", None)
    new_condition = update_data.pop("condition", None)

    previous_condition = alert.condition
    previous_type = alert.alert_type

    for key, value in update_data.items():
        setattr(alert, key, value)

    type_changed = alert.alert_type != previous_type
    if new_condition is not None or once is not None or type_changed:
        base = new_condition if new_condition is not None else alert.condition
        if not isinstance(base, dict):
            base = {}
        try:
            # Re-checked here against the alert's *effective* type, which the
            # schema validator cannot see: giving an RSI alert a bare price
            # threshold — or retyping a price alert to RSI and leaving its
            # ``above`` behind — would otherwise be stored and never fire.
            merged = validate_condition(apply_once(base, once), alert.alert_type)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        # Reassign rather than mutate: the JSON column has no mutation tracking.
        alert.condition = merged

    if alert.condition != previous_condition or type_changed:
        # Alerts are edge-triggered, and the latch says "the OLD condition was
        # already satisfied". Carrying it across an edit means a freshly raised
        # threshold that the price has *just* crossed reads as a continuation
        # and never notifies. Re-arm so the next evaluation is a clean edge.
        reset_edge_state(alert)

    await db.flush()
    await db.refresh(alert)
    return _as_response(alert)


@router.put("/{alert_id}/channels", response_model=AlertResponse)
async def update_alert_channels(
    alert_id: int,
    body: AlertChannelUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AlertResponse:
    """Update the notification channels for a specific alert."""
    alert = await _get_user_alert(alert_id, user, db)

    # Channel validity is enforced by the schema (AlertChannelUpdate uses the
    # Channel Literal), so an invalid name is rejected as 422 before we get here.
    alert.channels = body.channels
    await db.flush()
    await db.refresh(alert)
    return _as_response(alert)


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

    # Batch-resolve associated stock symbols in at most two queries instead of
    # one SELECT per triggered alert (previously an N+1).
    holding_ids = {a.holding_id for a in triggered_alerts if a.holding_id is not None}
    watchlist_ids = {
        a.watchlist_item_id
        for a in triggered_alerts
        if a.watchlist_item_id is not None
    }

    holding_symbols: dict[int, str] = {}
    if holding_ids:
        h_result = await db.execute(
            select(Holding.id, Holding.stock_symbol).where(
                Holding.id.in_(holding_ids)
            )
        )
        holding_symbols = {row[0]: row[1] for row in h_result.all()}

    watchlist_symbols: dict[int, str] = {}
    if watchlist_ids:
        w_result = await db.execute(
            select(WatchlistItem.id, WatchlistItem.stock_symbol).where(
                WatchlistItem.id.in_(watchlist_ids)
            )
        )
        watchlist_symbols = {row[0]: row[1] for row in w_result.all()}

    history: list[dict] = []
    for a in triggered_alerts:
        # Resolve the associated stock symbol from the batched lookups
        stock_symbol: str | None = None
        if a.holding_id is not None:
            stock_symbol = holding_symbols.get(a.holding_id)
        elif a.watchlist_item_id is not None:
            stock_symbol = watchlist_symbols.get(a.watchlist_item_id)

        history.append(
            {
                "alert_id": a.id,
                "alert_type": a.alert_type,
                "condition": a.condition,
                "triggered_at": _as_utc_iso(a.last_triggered),
                "stock_symbol": stock_symbol,
                "message": f"Alert {a.alert_type} triggered for {stock_symbol or 'unknown'}",
            }
        )

    # Also run a live check — read-only, so viewing this page doesn't put
    # alerts into cooldown and suppress the background dispatcher.
    live_triggered = await check_all_alerts_for_user(user.id, db, update_state=False)

    return {
        "history": history,
        "live_triggered": live_triggered,
    }
