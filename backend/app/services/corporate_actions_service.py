"""Corporate-actions service — detect and apply stock splits / bonus issues.

Splits are fetched from yfinance (``Ticker.splits``), which reports both true
stock splits *and* bonus issues as a single multiplicative ratio (a 2:1 split
and a 1:1 bonus both surface as ``2.0``). yfinance does not distinguish the two,
so every detected action is recorded with ``action_type == "SPLIT"``. The
adjustment maths for a split and a bonus are identical anyway: quantity is
multiplied by the ratio and average price divided by it, leaving the total
cost basis unchanged.

Applying an action directly adjusts ``holding.cumulative_quantity`` /
``average_price`` (authoritative) and, for ratios > 1 (the split/bonus case),
also writes a zero-cost adjustment ``Transaction`` dated at the ex-date so a
later ``calculate_cumulative_holding`` recompute reproduces the same numbers.
Every apply is idempotent — an already-APPLIED action is a no-op.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime

import yfinance as yf
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_action import CorporateAction
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.transaction import Transaction
from app.services.alert_service import determine_action_needed
from app.services.market_data_service import _ticker_symbol

logger = logging.getLogger(__name__)

# Bound how many yfinance calls run at once so detection over a large
# portfolio doesn't open dozens of concurrent HTTP requests.
_MAX_CONCURRENCY = 5
_FETCH_TIMEOUT = 15.0


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def _serialize(action: CorporateAction, symbol: str, exchange: str) -> dict:
    """Render a corporate action as a JSON-friendly dict with the holding's
    stock symbol / exchange joined in."""
    return {
        "id": action.id,
        "holding_id": action.holding_id,
        "stock_symbol": symbol,
        "exchange": exchange,
        "action_type": action.action_type,
        "ex_date": action.ex_date.isoformat() if action.ex_date else None,
        "ratio": float(action.ratio),
        "status": action.status,
        "applied_at": action.applied_at.isoformat() if action.applied_at else None,
        "details": action.details or {},
        "created_at": action.created_at.isoformat() if action.created_at else None,
    }


# ---------------------------------------------------------------------------
# yfinance split fetch (best-effort, bounded concurrency)
# ---------------------------------------------------------------------------

async def _fetch_splits(
    symbol: str,
    exchange: str,
    since: date | None,
    sem: asyncio.Semaphore,
) -> list[tuple[date, float]]:
    """Fetch (ex_date, ratio) split events for a symbol on/after *since*.

    Returns an empty list on any failure or if the ticker has no splits.
    """
    ticker_str = _ticker_symbol(symbol, exchange)

    def _sync():
        return yf.Ticker(ticker_str).splits

    async with sem:
        try:
            splits = await asyncio.wait_for(
                asyncio.to_thread(_sync), timeout=_FETCH_TIMEOUT
            )
        except Exception:
            logger.debug("Split fetch failed for %s", ticker_str, exc_info=True)
            return []

    out: list[tuple[date, float]] = []
    if splits is None or len(splits) == 0:
        return out

    for ts, raw_ratio in splits.items():
        try:
            ex = ts.date() if hasattr(ts, "date") else ts
            ratio = float(raw_ratio)
        except (ValueError, TypeError, AttributeError):
            continue
        # Skip no-ops and anything nonsensical.
        if ratio <= 0 or ratio == 1.0:
            continue
        if since is not None and ex < since:
            continue
        out.append((ex, ratio))
    return out


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

async def detect_corporate_actions(user_id: int, db: AsyncSession) -> dict:
    """Detect splits/bonuses for all of the user's holdings.

    For each holding, splits are fetched since the holding's earliest
    transaction date (falling back to its creation date). Any split not
    already recorded — deduped by (holding_id, ex_date, action_type) — is
    stored as a new ``CorporateAction`` with status ``DETECTED``.

    Returns ``{"newly_detected": int, "checked_holdings": int, "pending": [...]}``
    where ``pending`` is every DETECTED action (new + pre-existing).
    """
    result = await db.execute(
        select(Holding)
        .join(Portfolio, Holding.portfolio_id == Portfolio.id)
        .where(Portfolio.user_id == user_id)
    )
    holdings = list(result.scalars().all())

    if not holdings:
        return {"newly_detected": 0, "checked_holdings": 0, "pending": []}

    holding_ids = [h.id for h in holdings]

    # Earliest transaction date per holding (the window start for splits).
    tx_rows = await db.execute(
        select(Transaction.holding_id, func.min(Transaction.date))
        .where(Transaction.holding_id.in_(holding_ids))
        .group_by(Transaction.holding_id)
    )
    earliest: dict[int, date] = {hid: d for hid, d in tx_rows.all()}

    # Existing (holding_id, ex_date, action_type) keys for dedupe.
    existing_rows = await db.execute(
        select(
            CorporateAction.holding_id,
            CorporateAction.ex_date,
            CorporateAction.action_type,
        ).where(CorporateAction.holding_id.in_(holding_ids))
    )
    existing: set[tuple[int, date, str]] = {
        (hid, exd, atype) for hid, exd, atype in existing_rows.all()
    }

    def _window_start(h: Holding) -> date | None:
        if h.id in earliest and earliest[h.id] is not None:
            return earliest[h.id]
        if h.created_at is not None:
            return h.created_at.date()
        return None

    # ── Concurrent, bounded external fetch ──────────────────────────────
    sem = asyncio.Semaphore(_MAX_CONCURRENCY)
    tasks = [
        _fetch_splits(h.stock_symbol, h.exchange, _window_start(h), sem)
        for h in holdings
    ]
    fetch_results = await asyncio.gather(*tasks, return_exceptions=True)

    # ── Sequential DB writes ────────────────────────────────────────────
    newly_detected = 0
    for holding, res in zip(holdings, fetch_results):
        if isinstance(res, Exception) or not res:
            continue
        for ex_date, ratio in res:
            key = (holding.id, ex_date, "SPLIT")
            if key in existing:
                continue
            db.add(
                CorporateAction(
                    holding_id=holding.id,
                    action_type="SPLIT",
                    ex_date=ex_date,
                    ratio=ratio,
                    status="DETECTED",
                    details={"source": "yfinance", "detected_ratio": ratio},
                )
            )
            existing.add(key)
            newly_detected += 1

    await db.flush()

    pending = await list_corporate_actions(user_id, db, status_filter="DETECTED")
    return {
        "newly_detected": newly_detected,
        "checked_holdings": len(holdings),
        "pending": pending,
    }


# ---------------------------------------------------------------------------
# Ownership-scoped fetch of a single action
# ---------------------------------------------------------------------------

async def _get_user_action(
    action_id: int, user_id: int, db: AsyncSession
) -> tuple[CorporateAction, Holding]:
    """Fetch a corporate action + its holding, verifying it belongs to the
    user (via holding -> portfolio -> user). Raises ``ValueError`` if not."""
    result = await db.execute(
        select(CorporateAction, Holding)
        .join(Holding, CorporateAction.holding_id == Holding.id)
        .join(Portfolio, Holding.portfolio_id == Portfolio.id)
        .where(CorporateAction.id == action_id, Portfolio.user_id == user_id)
    )
    row = result.first()
    if row is None:
        raise ValueError("Corporate action not found")
    return row[0], row[1]


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

async def apply_corporate_action(
    action_id: int, user_id: int, db: AsyncSession
) -> dict:
    """Apply a DETECTED split/bonus to its holding.

    Adjusts ``cumulative_quantity *= ratio`` and ``average_price /= ratio``
    (cost basis unchanged) and marks the action APPLIED. Idempotent: an
    already-APPLIED action is returned unchanged. A DISMISSED action cannot
    be applied.
    """
    action, holding = await _get_user_action(action_id, user_id, db)

    if action.status == "APPLIED":
        # Idempotent no-op.
        return _serialize(action, holding.stock_symbol, holding.exchange)
    if action.status == "DISMISSED":
        raise ValueError("Cannot apply a dismissed corporate action")

    ratio = float(action.ratio)
    if ratio <= 0:
        raise ValueError("Invalid corporate-action ratio")

    old_qty = float(holding.cumulative_quantity)
    old_avg = float(holding.average_price)
    cost_basis = old_qty * old_avg

    new_qty = old_qty * ratio
    new_avg = round(old_avg / ratio, 4)

    holding.cumulative_quantity = new_qty
    holding.average_price = new_avg

    # For a split/bonus (ratio > 1) record a zero-cost adjustment BUY dated at
    # the ex-date so a future calculate_cumulative_holding recompute stays
    # consistent. Skipped for reverse splits (ratio < 1) to avoid a
    # negative-quantity transaction — those rely on the direct adjustment only.
    txn_written = False
    if ratio > 1 and old_qty > 0:
        db.add(
            Transaction(
                holding_id=holding.id,
                transaction_type="BUY",
                date=action.ex_date,
                quantity=old_qty * (ratio - 1),
                price=0,
                brokerage=0,
                notes=f"{action.action_type} adjustment (ratio {ratio}) — auto",
                source="MANUAL",
            )
        )
        txn_written = True

    holding.action_needed = determine_action_needed(holding.current_price, holding)

    action.status = "APPLIED"
    action.applied_at = datetime.now(UTC)
    # Reassign the dict so SQLAlchemy flags the JSON column dirty.
    action.details = {
        **(action.details or {}),
        "applied": {
            "old_quantity": old_qty,
            "new_quantity": new_qty,
            "old_average_price": old_avg,
            "new_average_price": new_avg,
            "cost_basis": round(cost_basis, 2),
            "ratio": ratio,
            "adjustment_transaction": txn_written,
        },
    }

    await db.flush()
    return _serialize(action, holding.stock_symbol, holding.exchange)


# ---------------------------------------------------------------------------
# Dismiss
# ---------------------------------------------------------------------------

async def dismiss_corporate_action(
    action_id: int, user_id: int, db: AsyncSession
) -> dict:
    """Mark a corporate action DISMISSED. No-op if already dismissed;
    an already-APPLIED action cannot be dismissed."""
    action, holding = await _get_user_action(action_id, user_id, db)

    if action.status == "APPLIED":
        raise ValueError("Cannot dismiss an already-applied corporate action")

    if action.status != "DISMISSED":
        action.status = "DISMISSED"
        await db.flush()

    return _serialize(action, holding.stock_symbol, holding.exchange)


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

async def list_corporate_actions(
    user_id: int,
    db: AsyncSession,
    status_filter: str | None = None,
) -> list[dict]:
    """List the user's corporate actions with the holding symbol joined in.

    Optionally filter by ``status`` (DETECTED / APPLIED / DISMISSED).
    Ordered newest ex-date first.
    """
    stmt = (
        select(CorporateAction, Holding.stock_symbol, Holding.exchange)
        .join(Holding, CorporateAction.holding_id == Holding.id)
        .join(Portfolio, Holding.portfolio_id == Portfolio.id)
        .where(Portfolio.user_id == user_id)
    )
    if status_filter:
        stmt = stmt.where(CorporateAction.status == status_filter.upper())
    stmt = stmt.order_by(CorporateAction.ex_date.desc(), CorporateAction.id.desc())

    rows = await db.execute(stmt)
    return [_serialize(ca, symbol, exchange) for ca, symbol, exchange in rows.all()]
