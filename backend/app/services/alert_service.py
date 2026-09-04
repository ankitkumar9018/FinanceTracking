"""Alert service: price-range action logic, alert checking, notification dispatch."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert
from app.models.holding import Holding
from app.models.watchlist import WatchlistItem

logger = logging.getLogger(__name__)

# Cooldown: don't re-trigger the same alert within this many seconds
ALERT_COOLDOWN_SECONDS = 300  # 5 minutes

# Condition keys that ask for a single notification: ``{"above": 1400,
# "once": true}``. ``Alert.condition`` is a free-form JSON dict that the API
# passes through untouched, so this needs no schema or model change.
ONE_SHOT_KEYS = ("one_shot", "once")

# ---------------------------------------------------------------------------
# Edge-trigger state
# ---------------------------------------------------------------------------
# Alerts used to be purely *level*-triggered: the 5-minute cooldown was the
# only de-duplication, so a threshold that got crossed once and then simply
# stayed crossed re-notified every 5 minutes forever — up to 288 emails/SMS a
# day for one alert. Dispatch now happens only on a false -> true transition
# of the condition (a *rising edge*).
#
# The previous truth value lives in this process-local map rather than in a new
# ``Alert`` column (that model is not owned here). Both consequences are
# benign: a restart forgets the latch, so a still-true alert notifies once more
# after startup (the cooldown still applies), and only the single scheduler
# process evaluates alerts, so there is no cross-process consistency problem.
# For a durable latch, see ``one_shot`` below, which persists via ``is_active``.
#
# Keyed by alert id *and* the alert's ``created_at`` so a recycled primary key
# (SQLite hands out max(id)+1 again once the last row is deleted) cannot
# inherit the latch of the alert it replaced and swallow its first
# notification.
_CONDITION_WAS_TRUE: dict[int, tuple[datetime | None, bool]] = {}


def reset_edge_state(alert_id: int | None = None) -> None:
    """Forget the latched truth value for one alert, or for all of them.

    Call this after an alert's condition is edited so the next evaluation is
    treated as a fresh rising edge rather than a continuation of the old one.
    """
    if alert_id is None:
        _CONDITION_WAS_TRUE.clear()
    else:
        _CONDITION_WAS_TRUE.pop(alert_id, None)


def _alert_identity(alert: Alert) -> datetime | None:
    """The alert's ``created_at``, or None if it isn't loaded on this instance.

    Guarded because a lazy attribute load from this synchronous helper would
    raise ``MissingGreenlet`` under the async session, and losing the identity
    check must never be able to take the alert job down.
    """
    try:
        return getattr(alert, "created_at", None)
    except Exception:  # pragma: no cover - defensive
        return None


def _remembered_condition_state(alert: Alert) -> tuple[datetime | None, bool]:
    """Return ``(identity, was_true)`` for *alert*'s remembered truth value."""
    identity = _alert_identity(alert)
    remembered_identity, was_true = _CONDITION_WAS_TRUE.get(alert.id, (None, False))
    if remembered_identity != identity:
        was_true = False  # recycled id — the remembered state isn't ours
    return identity, was_true


def _record_condition_state(alert: Alert, condition_true: bool) -> bool:
    """Store *alert*'s current truth value; report whether it just rose."""
    identity, was_true = _remembered_condition_state(alert)
    if condition_true:
        _CONDITION_WAS_TRUE[alert.id] = (identity, True)
    else:
        _CONDITION_WAS_TRUE.pop(alert.id, None)
    return condition_true and not was_true


def _in_cooldown(alert: Alert, now: datetime) -> bool:
    """Was this alert triggered less than ``ALERT_COOLDOWN_SECONDS`` ago?"""
    last_triggered = alert.last_triggered
    if not last_triggered:
        return False
    if last_triggered.tzinfo is None:
        last_triggered = last_triggered.replace(tzinfo=UTC)
    return (now - last_triggered).total_seconds() < ALERT_COOLDOWN_SECONDS


def _is_one_shot(condition: Any) -> bool:
    """Does this condition ask to fire only once and then deactivate?"""
    if not isinstance(condition, dict):
        return False
    return any(bool(condition.get(key)) for key in ONE_SHOT_KEYS)


def _as_float(value: Any, *, alert_id: int, key: str) -> float | None:
    """Coerce a stored condition value to float, or None when it isn't numeric.

    ``Alert.condition`` is a bare JSON dict with no value validation at the API
    boundary, so a threshold saved as text used to raise ValueError straight
    out of the evaluation — which aborted the alert cycle for *every* user, not
    just the owner of the malformed alert.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        logger.warning(
            "alert %s: ignoring non-numeric condition value %r for key %r",
            alert_id,
            value,
            key,
        )
        return None


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

    # Light red: at or below lower_mid_range_1 (and above lmr2 when set).
    # Works with only lmr1 configured — a partial setup must still trigger.
    if lmr1 is not None and price <= float(lmr1):
        return "Y_LOWER_MID"

    # --- Top zones (selling opportunities) ---
    # Dark green: price at or above upper_mid_range_2 (toward / above top)
    if umr2 is not None and price >= float(umr2):
        return "Y_DARK_GREEN"

    # Light green: at or above upper_mid_range_1 (and below umr2 when set).
    if umr1 is not None and price >= float(umr1):
        return "Y_UPPER_MID"

    # Neutral zone: between lmr1 and umr1, or outside all defined ranges
    return "N"


# ---------------------------------------------------------------------------
# Condition evaluation (shared by holdings and watchlist items)
# ---------------------------------------------------------------------------

def _evaluate_alert(
    alert: Alert, item: Any, price: float, rsi: float | None
) -> str | None:
    """Return the notification message when *alert*'s condition holds, else None.

    Shared by the holding and the watchlist paths, which used to carry two
    near-identical copies of this logic — and the watchlist copy silently
    ignored CUSTOM (zone) alerts entirely, so a watchlist zone alert could
    never fire.
    """
    condition = alert.condition if isinstance(alert.condition, dict) else {}
    symbol = getattr(item, "stock_symbol", "?")

    if alert.alert_type == "PRICE_RANGE":
        above = _as_float(condition.get("above"), alert_id=alert.id, key="above")
        below = _as_float(condition.get("below"), alert_id=alert.id, key="below")
        if above is not None and price >= above:
            return f"{symbol} price {price:.2f} is above threshold {above:.2f}"
        if below is not None and price <= below:
            return f"{symbol} price {price:.2f} is below threshold {below:.2f}"
        return None

    if alert.alert_type == "RSI":
        if rsi is None:
            return None
        rsi_above = _as_float(
            condition.get("rsi_above"), alert_id=alert.id, key="rsi_above"
        )
        rsi_below = _as_float(
            condition.get("rsi_below"), alert_id=alert.id, key="rsi_below"
        )
        if rsi_above is not None and rsi >= rsi_above:
            return f"{symbol} RSI {rsi:.1f} is above threshold {rsi_above:g}"
        if rsi_below is not None and rsi <= rsi_below:
            return f"{symbol} RSI {rsi:.1f} is below threshold {rsi_below:g}"
        return None

    if alert.alert_type == "CUSTOM":
        action = determine_action_needed(price, item)
        expected_action = condition.get("action_needed")
        if expected_action and action == expected_action:
            return f"{symbol} entered zone: {action} (price={price:.2f})"
        return None

    return None


def _consider_alert(
    alert: Alert,
    item: Any,
    price: float,
    rsi: float | None,
    now: datetime,
    *,
    update_state: bool,
) -> dict | None:
    """Evaluate one alert and decide whether it should notify right now.

    ``update_state=False`` is the read-only view used by the alerts UI: it
    reports every condition that currently holds and neither stamps
    ``last_triggered`` nor touches the edge-trigger latch.  The dispatcher path
    (``update_state=True``) additionally requires a *rising edge*, so an alert
    whose condition merely stays true does not re-notify.
    """
    # The cooldown is checked before the latch is touched, so a rising edge
    # that lands inside the cooldown window is deferred rather than consumed.
    if _in_cooldown(alert, now):
        return None

    message = _evaluate_alert(alert, item, price, rsi)

    if not update_state:
        if message is None:
            return None
        return _triggered_payload(alert, item, message, now)

    if not _record_condition_state(alert, message is not None) or message is None:
        return None

    triggered_at = datetime.now(UTC)
    alert.last_triggered = triggered_at
    if _is_one_shot(alert.condition):
        # Durable one-shot: the latch above is process-local, is_active is not.
        alert.is_active = False
        reset_edge_state(alert.id)
        logger.info("alert %s deactivated after its one-shot trigger", alert.id)
    return _triggered_payload(alert, item, message, triggered_at)


def _triggered_payload(
    alert: Alert, item: Any, message: str, triggered_at: datetime
) -> dict:
    """Build the dict the background dispatcher and the API both consume."""
    return {
        "alert_id": alert.id,
        "alert_type": alert.alert_type,
        "condition": alert.condition,
        "triggered_at": triggered_at,
        "stock_symbol": getattr(item, "stock_symbol", None),
        "message": message,
        "channels": alert.channels,
    }


# ---------------------------------------------------------------------------
# Check alerts for a specific holding
# ---------------------------------------------------------------------------

async def check_alerts_for_holding(
    holding: Holding, db: AsyncSession, *, update_state: bool = True
) -> list[dict]:
    """Check all active alerts associated with a holding and evaluate whether
    they should trigger based on the holding's current price.

    ``update_state=False`` makes the check a pure read: ``last_triggered``
    is not stamped and the edge-trigger latch is not updated. Use this from
    GET endpoints so a user viewing their alerts doesn't put alerts into
    cooldown and suppress the background dispatcher's real notifications.

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
    rsi = float(holding.current_rsi) if holding.current_rsi is not None else None
    now = datetime.now(UTC)

    for alert in alerts:
        payload = _consider_alert(
            alert, holding, price, rsi, now, update_state=update_state
        )
        if payload is not None:
            triggered.append(payload)

    if triggered and update_state:
        await db.flush()

    return triggered


# ---------------------------------------------------------------------------
# Check all holdings for a user (batch)
# ---------------------------------------------------------------------------

async def check_all_alerts_for_user(
    user_id: int, db: AsyncSession, *, update_state: bool = True
) -> list[dict]:
    """Check alerts across all holdings and watchlist items for a given user.

    ``update_state=False`` performs a pure read-only evaluation (no
    ``last_triggered`` stamping, no edge latch) — see ``check_alerts_for_holding``.

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
            triggered = await check_alerts_for_holding(
                holding, db, update_state=update_state
            )
            all_triggered.extend(triggered)

    # ── Watchlist-based alerts ──────────────────────────────────────
    wl_result = await db.execute(
        select(Alert)
        .where(Alert.user_id == user_id, Alert.is_active.is_(True))
        .where(Alert.watchlist_item_id.isnot(None))
    )
    wl_alerts = wl_result.scalars().all()

    if wl_alerts:
        wl_ids = {
            a.watchlist_item_id for a in wl_alerts if a.watchlist_item_id is not None
        }
        wl_items_result = await db.execute(
            select(WatchlistItem).where(WatchlistItem.id.in_(wl_ids))
        )
        wl_items = {w.id: w for w in wl_items_result.scalars().all()}

        now = datetime.now(UTC)
        wl_triggered = 0

        for alert in wl_alerts:
            wl_item = (
                wl_items.get(alert.watchlist_item_id)
                if alert.watchlist_item_id is not None
                else None
            )
            if not wl_item or wl_item.current_price is None:
                continue

            rsi = (
                float(wl_item.current_rsi)
                if wl_item.current_rsi is not None
                else None
            )
            payload = _consider_alert(
                alert,
                wl_item,
                float(wl_item.current_price),
                rsi,
                now,
                update_state=update_state,
            )
            if payload is not None:
                wl_triggered += 1
                all_triggered.append(payload)

        # Flush only when this pass actually changed something. The old
        # condition ("any alert has a last_triggered") flushed on every call
        # once a single alert had ever fired.
        if wl_triggered and update_state:
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
