"""Alert service: price-range action logic, alert checking, notification dispatch."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert
from app.models.holding import Holding
from app.models.watchlist import WatchlistItem

logger = logging.getLogger(__name__)

# Cooldown: don't re-trigger the same alert within this many seconds
ALERT_COOLDOWN_SECONDS = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Core action-needed / colour logic
# ---------------------------------------------------------------------------

def determine_action_needed(current_price: float | None, holding_or_item) -> str:
    """Determine the action status for a holding or watchlist item based on
    where the current price sits relative to its range levels.

    Zone layout (ascending price):

        base_level
          |
        lower_mid_range_2   <-- at or below here = Y_DARK_RED   (dark red / strong buy)
          |
        lower_mid_range_1   <-- between lmr2..lmr1 = Y_LOWER_MID (light red / buy zone)
          |
        (neutral zone)      <-- between lmr1..umr1 = N            (no action)
          |
        upper_mid_range_1   <-- between umr1..umr2 = Y_UPPER_MID (light green / sell zone)
          |
        upper_mid_range_2   <-- at or above here = Y_DARK_GREEN  (dark green / strong sell)
          |
        top_level

    Parameters
    ----------
    current_price : float | None
        The current market price.
    holding_or_item
        Any object with attributes: lower_mid_range_1, lower_mid_range_2,
        upper_mid_range_1, upper_mid_range_2 (and optionally base_level, top_level).

    Returns
    -------
    str
        One of: "N", "Y_LOWER_MID", "Y_UPPER_MID", "Y_DARK_RED", "Y_DARK_GREEN"
    """
    if current_price is None:
        return "N"

    lmr2 = getattr(holding_or_item, "lower_mid_range_2", None)
    lmr1 = getattr(holding_or_item, "lower_mid_range_1", None)
    umr1 = getattr(holding_or_item, "upper_mid_range_1", None)
    umr2 = getattr(holding_or_item, "upper_mid_range_2", None)

    # If no range levels are defined, nothing to evaluate
    if all(v is None for v in (lmr2, lmr1, umr1, umr2)):
        return "N"

    price = float(current_price)

    # --- Bottom zones (buying opportunities) ---
    # Dark red: price at or below lower_mid_range_2 (toward / below base)
    if lmr2 is not None and price <= float(lmr2):
        return "Y_DARK_RED"

    # Light red: price between lower_mid_range_2 and lower_mid_range_1
    if lmr2 is not None and lmr1 is not None:
        if float(lmr2) < price <= float(lmr1):
            return "Y_LOWER_MID"

    # --- Top zones (selling opportunities) ---
    # Dark green: price at or above upper_mid_range_2 (toward / above top)
    if umr2 is not None and price >= float(umr2):
        return "Y_DARK_GREEN"

    # Light green: price between upper_mid_range_1 and upper_mid_range_2
    if umr1 is not None and umr2 is not None:
        if float(umr1) <= price < float(umr2):
            return "Y_UPPER_MID"

    # Neutral zone: between lmr1 and umr1, or outside all defined ranges
    return "N"


# ---------------------------------------------------------------------------
# Check alerts for a specific holding
# ---------------------------------------------------------------------------

async def check_alerts_for_holding(holding: Holding, db: AsyncSession) -> list[dict]:
    """Check all active alerts associated with a holding and evaluate whether
    they should trigger based on the holding's current price.

    Returns a list of triggered alert descriptions (dicts).
    """
    result = await db.execute(
        select(Alert).where(
            Alert.holding_id == holding.id,
            Alert.is_active.is_(True),
        )
    )
    alerts = result.scalars().all()
    triggered: list[dict] = []

    price = holding.current_price
    if price is None:
        return triggered

    price = float(price)

    now = datetime.now(UTC)

    for alert in alerts:
        # Deduplication: skip if triggered recently
        if alert.last_triggered:
            last_triggered = alert.last_triggered
            if last_triggered.tzinfo is None:
                last_triggered = last_triggered.replace(tzinfo=UTC)
            elapsed = (now - last_triggered).total_seconds()
            if elapsed < ALERT_COOLDOWN_SECONDS:
                continue

        should_trigger = False
        message = ""

        if alert.alert_type == "PRICE_RANGE":
            # Check condition keys: above, below, between
            above = alert.condition.get("above")
            below = alert.condition.get("below")

            if above is not None and price >= float(above):
                should_trigger = True
                message = (
                    f"{holding.stock_symbol} price {price:.2f} is above "
                    f"threshold {float(above):.2f}"
                )
            elif below is not None and price <= float(below):
                should_trigger = True
                message = (
                    f"{holding.stock_symbol} price {price:.2f} is below "
                    f"threshold {float(below):.2f}"
                )

        elif alert.alert_type == "RSI":
            rsi = holding.current_rsi
            if rsi is not None:
                rsi_above = alert.condition.get("rsi_above")
                rsi_below = alert.condition.get("rsi_below")

                if rsi_above is not None and rsi >= float(rsi_above):
                    should_trigger = True
                    message = (
                        f"{holding.stock_symbol} RSI {rsi:.1f} is above "
                        f"threshold {float(rsi_above)}"
                    )
                elif rsi_below is not None and rsi <= float(rsi_below):
                    should_trigger = True
                    message = (
                        f"{holding.stock_symbol} RSI {rsi:.1f} is below "
                        f"threshold {float(rsi_below)}"
                    )

        elif alert.alert_type == "CUSTOM":
            # Action-needed change detection
            action = determine_action_needed(price, holding)
            expected_action = alert.condition.get("action_needed")
            if expected_action and action == expected_action:
                should_trigger = True
                message = (
                    f"{holding.stock_symbol} entered zone: {action} "
                    f"(price={price:.2f})"
                )

        if should_trigger:
            alert.last_triggered = datetime.now(UTC)
            triggered.append(
                {
                    "alert_id": alert.id,
                    "alert_type": alert.alert_type,
                    "condition": alert.condition,
                    "triggered_at": alert.last_triggered,
                    "stock_symbol": holding.stock_symbol,
                    "message": message,
                    "channels": alert.channels,
                }
            )

    if triggered:
        await db.flush()

    return triggered


# ---------------------------------------------------------------------------
# Check all holdings for a user (batch)
# ---------------------------------------------------------------------------

async def check_all_alerts_for_user(user_id: int, db: AsyncSession) -> list[dict]:
    """Check alerts across all holdings and watchlist items for a given user.

    Returns a flat list of all triggered alert dicts.
    """
    all_triggered: list[dict] = []

    # ── Holding-based alerts ────────────────────────────────────────
    result = await db.execute(
        select(Alert)
        .where(Alert.user_id == user_id, Alert.is_active.is_(True))
        .where(Alert.holding_id.isnot(None))
    )
    holding_alerts = result.scalars().all()

    holding_ids = {a.holding_id for a in holding_alerts if a.holding_id is not None}
    if holding_ids:
        h_result = await db.execute(
            select(Holding).where(Holding.id.in_(holding_ids))
        )
        holdings = {h.id: h for h in h_result.scalars().all()}

        for holding in holdings.values():
            triggered = await check_alerts_for_holding(holding, db)
            all_triggered.extend(triggered)

    # ── Watchlist-based alerts ──────────────────────────────────────
    wl_result = await db.execute(
        select(Alert)
        .where(Alert.user_id == user_id, Alert.is_active.is_(True))
        .where(Alert.watchlist_item_id.isnot(None))
    )
    wl_alerts = wl_result.scalars().all()

    if wl_alerts:
        wl_ids = {a.watchlist_item_id for a in wl_alerts if a.watchlist_item_id is not None}
        wl_items_result = await db.execute(
            select(WatchlistItem).where(WatchlistItem.id.in_(wl_ids))
        )
        wl_items = {w.id: w for w in wl_items_result.scalars().all()}

        now = datetime.now(UTC)

        for alert in wl_alerts:
            wl_item = wl_items.get(alert.watchlist_item_id)
            if not wl_item or wl_item.current_price is None:
                continue

            # Cooldown check
            if alert.last_triggered:
                lt = alert.last_triggered
                if lt.tzinfo is None:
                    lt = lt.replace(tzinfo=UTC)
                elapsed = (now - lt).total_seconds()
                if elapsed < ALERT_COOLDOWN_SECONDS:
                    continue

            price = float(wl_item.current_price)
            should_trigger = False
            message = ""

            if alert.alert_type == "PRICE_RANGE":
                above = alert.condition.get("above")
                below = alert.condition.get("below")
                if above is not None and price >= float(above):
                    should_trigger = True
                    message = f"{wl_item.stock_symbol} price {price:.2f} above {float(above):.2f}"
                elif below is not None and price <= float(below):
                    should_trigger = True
                    message = f"{wl_item.stock_symbol} price {price:.2f} below {float(below):.2f}"
            elif alert.alert_type == "RSI" and wl_item.current_rsi is not None:
                rsi = float(wl_item.current_rsi)
                rsi_above = alert.condition.get("rsi_above")
                rsi_below = alert.condition.get("rsi_below")
                if rsi_above is not None and rsi >= float(rsi_above):
                    should_trigger = True
                    message = f"{wl_item.stock_symbol} RSI {rsi:.1f} above {float(rsi_above)}"
                elif rsi_below is not None and rsi <= float(rsi_below):
                    should_trigger = True
                    message = f"{wl_item.stock_symbol} RSI {rsi:.1f} below {float(rsi_below)}"

            if should_trigger:
                alert.last_triggered = datetime.now(UTC)
                all_triggered.append({
                    "alert_id": alert.id,
                    "alert_type": alert.alert_type,
                    "condition": alert.condition,
                    "triggered_at": alert.last_triggered,
                    "stock_symbol": wl_item.stock_symbol,
                    "message": message,
                    "channels": alert.channels,
                })

        if any(a.last_triggered for a in wl_alerts):
            await db.flush()

    return all_triggered


# ---------------------------------------------------------------------------
# Zone-change detection (auto-alerts without explicit alert creation)
# ---------------------------------------------------------------------------

def detect_zone_change(
    old_action: str | None,
    new_action: str,
    holding,
) -> dict | None:
    """Detect when a holding transitions from one action zone to another.

    Returns a dict describing the zone change, or None if no change.
    """
    if old_action == new_action:
        return None

    # Map zone codes to human-readable descriptions
    zone_labels = {
        "N": "Neutral",
        "Y_LOWER_MID": "Lower Mid Range (light red)",
        "Y_UPPER_MID": "Upper Mid Range (light green)",
        "Y_DARK_RED": "Below Base Level (dark red)",
        "Y_DARK_GREEN": "Above Top Level (dark green)",
    }

    old_label = zone_labels.get(old_action or "N", old_action or "N")
    new_label = zone_labels.get(new_action, new_action)

    # Determine severity for notification routing
    severity = "info"
    if new_action in ("Y_DARK_RED", "Y_DARK_GREEN"):
        severity = "critical"
    elif new_action in ("Y_LOWER_MID", "Y_UPPER_MID"):
        severity = "warning"

    return {
        "stock_symbol": holding.stock_symbol,
        "exchange": getattr(holding, "exchange", ""),
        "old_zone": old_action or "N",
        "new_zone": new_action,
        "old_label": old_label,
        "new_label": new_label,
        "severity": severity,
        "current_price": float(holding.current_price) if holding.current_price else None,
        "message": (
            f"{holding.stock_symbol} moved from {old_label} to {new_label}"
            f" (price: {holding.current_price})"
        ),
    }


# ---------------------------------------------------------------------------
# Batch alert check for all users (used by background tasks)
# ---------------------------------------------------------------------------

async def check_all_alerts(db: AsyncSession) -> list[dict]:
    """Check alerts for ALL users with active alerts.

    Returns a flat list of all triggered alert dicts, each including user_id.
    """
    # Get distinct user IDs with active alerts
    result = await db.execute(
        select(Alert.user_id).where(Alert.is_active.is_(True)).distinct()
    )
    user_ids = [row[0] for row in result.all()]

    all_triggered: list[dict] = []
    for user_id in user_ids:
        triggered = await check_all_alerts_for_user(user_id, db)
        for t in triggered:
            t["user_id"] = user_id
        all_triggered.extend(triggered)

    logger.info(
        "Alert check complete: %d users, %d alerts triggered",
        len(user_ids),
        len(all_triggered),
    )
    return all_triggered
