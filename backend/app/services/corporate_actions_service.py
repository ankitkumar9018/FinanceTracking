"""Corporate-actions service — detect and apply stock splits / bonus issues.

Splits are fetched from yfinance (``Ticker.splits``), which reports both true
stock splits *and* bonus issues as a single multiplicative ratio (a 2:1 split
and a 1:1 bonus both surface as ``2.0``), so every DETECTED action is recorded
with ``action_type == "SPLIT"``.

A SPLIT IS NOT AN ACQUISITION
----------------------------
Both regimes treat a subdivision as a re-basing of shares the taxpayer already
owns, not as a fresh purchase:

- India — s.55(2)(b)(v) with s.2(42A) Expl. 1(i)(d)/(e): the original cost is
  spread over the enlarged number of shares and the holding period of the
  original shares is INHERITED. No fresh cost, no fresh acquisition date.
- Germany — s.20 EStG / BMF: a Split is a *steuerneutraler Vorgang*. The
  Anschaffungskosten je Stueck are divided by the ratio, the
  Anschaffungszeitpunkt is unchanged, and the FIFO-Verbrauchsfolge
  (s.20(4) S.7 EStG) runs over the re-based original lots.

So applying a SPLIT re-bases every ledger row dated on/before the ex-date::

    new_quantity = old_quantity * ratio      (rounded to the column's 6 dp)
    new_price    = old_quantity * old_price / new_quantity   (4 dp)

Each row's total consideration is invariant, so already-realized gains, gain
types and purchase dates survive the restatement; the FIFO queue keeps exactly
the same number of lots, each re-based. SELL rows on/before the ex-date are
restated too — otherwise the residual quantity would be wrong (100 bought,
40 sold, 2:1 must leave 120, not 160) — and because quantity x r and price / r
cancel, restating a past SELL does not restate its realized gain. Rows dated
after the ex-date already print at post-split size/price and are untouched.

Writing a zero-price adjustment BUY instead (what this module used to do) gives
the split shares a NIL cost basis with the ex-date as their acquisition date:
the next sale then books a fabricated loss on the original lot and a fabricated
short-term gain on the phantom one. On the headline case (100 @ Rs 1000, 2:1,
two sales of 100 @ Rs 600) that billed Rs 12,000 of STCG against a true
liability of Rs 0.

BONUS ISSUES ARE THE EXCEPTION (INDIA)
--------------------------------------
A genuine bonus issue out of reserves *is* an acquisition under Indian law:
cost of acquisition is NIL (s.55(2)(aa)(iiia)) and the holding period runs from
the date of allotment (s.2(42A) Expl. 1(i)(f)) — i.e. exactly a zero-cost lot
dated at the ex-date. So an action explicitly typed ``BONUS`` on an Indian
exchange keeps the zero-cost allotment row. German Gratisaktien are re-based
(s.3 KapErhStG), so the exception is India-only. yfinance cannot tell a bonus
from a split, so only a deliberately typed ``BONUS`` action takes that path.

Applying also recomputes the tax records of every SELL on the holding that
already has them, in ``(sale_date, transaction_id)`` order — the FY exemption /
Freibetrag netting in ``tax_service`` is strictly order-based. Every apply is
idempotent: an already-APPLIED action is a no-op.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

import yfinance as yf
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.markets import JURISDICTION
from app.models.corporate_action import CorporateAction
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.tax_record import TaxRecord
from app.models.transaction import Transaction
from app.services.alert_service import determine_action_needed
from app.services.market_data_service import _ticker_symbol
from app.services.portfolio_service import calculate_cumulative_holding

logger = logging.getLogger(__name__)

# Bound how many yfinance calls run at once so detection over a large
# portfolio doesn't open dozens of concurrent HTTP requests.
_MAX_CONCURRENCY = 5
_FETCH_TIMEOUT = 15.0

# Column scales: Transaction.quantity is Numeric(18, 6), price Numeric(18, 4).
_QTY_QUANT = Decimal("0.000001")
_PRICE_QUANT = Decimal("0.0001")

# Re-base the existing lots (a split: no acquisition) vs. write a nil-cost
# allotment lot dated at the ex-date (an Indian bonus issue).
_REBASE = "REBASE"
_ALLOTMENT = "NIL_COST_ALLOTMENT"


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
        if isinstance(res, BaseException) or not res:
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
# Re-basing helpers
# ---------------------------------------------------------------------------

def _treatment_for(action: CorporateAction, holding: Holding) -> str:
    """Whether this action re-bases the existing lots or creates a new one.

    A split/subdivision re-bases (it is not an acquisition). A genuine Indian
    bonus issue is an acquisition at NIL cost with the allotment date as its
    acquisition date, so it keeps the zero-cost lot. German Gratisaktien are
    re-based (s.3 KapErhStG), so the exception is India-only.
    """
    action_type = (action.action_type or "").strip().upper()
    exchange = (holding.exchange or "").strip().upper()
    if action_type == "BONUS" and JURISDICTION.get(exchange) == "IN":
        return _ALLOTMENT
    return _REBASE


def _rebase_row(tx: Transaction, ratio: Decimal) -> bool:
    """Re-base one pre-ex-date ledger row in place, preserving its total
    consideration. Returns whether the row was restated.

    The new price is derived from the ROUNDED quantity, so ``quantity * price``
    as STORED reproduces the original consideration; dividing by the unrounded
    product would leave the stored pair off by the rounding delta.

    Only ``quantity`` and ``price`` are touched. ``notes`` deliberately is not:
    ``dividend_service`` finds a reinvestment BUY by an exact ``notes ==``
    match, so stamping an audit line there would orphan DRIP rows when their
    dividend is deleted. The operation is described by ``details.applied``
    (ratio, ex-date, row count) and reverses by scaling with ``1 / ratio``.
    """
    qty = Decimal(str(tx.quantity))
    if qty == 0:
        return False
    price = Decimal(str(tx.price))
    consideration = qty * price

    new_qty = (qty * ratio).quantize(_QTY_QUANT, rounding=ROUND_HALF_UP)
    if new_qty == 0:
        # Would need a division by zero, and would silently delete quantity.
        logger.warning(
            "Split rebase: txn=%s quantity %s x %s rounds to zero — left as-is",
            tx.id, qty, ratio,
        )
        return False
    new_price = (consideration / new_qty).quantize(
        _PRICE_QUANT, rounding=ROUND_HALF_UP
    )

    tx.quantity = float(new_qty)
    tx.price = float(new_price)
    return True


async def _sell_txn_ids_with_tax_records(
    holding_id: int, user_id: int, db: AsyncSession
) -> list[int]:
    """SELL transactions on this holding that already carry TaxRecords, in
    ``(sale_date, transaction_id)`` order — the order the FY netting cascade
    requires."""
    rows = await db.execute(
        select(Transaction.id, Transaction.date)
        .join(TaxRecord, TaxRecord.transaction_id == Transaction.id)
        .where(
            Transaction.holding_id == holding_id,
            Transaction.transaction_type == "SELL",
            TaxRecord.user_id == user_id,
        )
        .order_by(Transaction.date, Transaction.id)
    )
    seen: list[int] = []
    for txn_id, _sale_date in rows.all():
        if txn_id not in seen:
            seen.append(txn_id)
    return seen


async def _txn_ids_with_tax_records(user_id: int, db: AsyncSession) -> set[int]:
    rows = await db.execute(
        select(TaxRecord.transaction_id).where(
            TaxRecord.user_id == user_id, TaxRecord.transaction_id.isnot(None)
        )
    )
    return {txn_id for (txn_id,) in rows.all() if txn_id is not None}


async def recompute_tax_after_ledger_change(
    holding_id: int, user_id: int, db: AsyncSession
) -> dict:
    """Recompute the tax records invalidated by a corporate action.

    Every SELL on the holding that already has TaxRecords is recomputed in
    ``(sale_date, transaction_id)`` order, because the FY exemption /
    Freibetrag netting in ``tax_service`` is strictly order-based and each
    compute cascades over the later sells of the same FY.

    Pre-ex-date sells are recomputed too. They are NOT invariant under the
    re-basing: Indian s.55(2)(ac) grandfathering compares the per-share cost
    against an absolute 31-Jan-2018 FMV, which does not scale with the ratio,
    so a pre-2018 lot's grandfathered basis genuinely changes (for the better —
    the FMV yfinance returns is already split-adjusted). Leaving those records
    stale would not freeze them either: the next FY cascade would silently
    rewrite them.

    That cascade reaches every later sale in the same FY across ALL holdings,
    and a sale whose purchase rows have since been deleted loses its (already
    unbackable) records rather than being recomputed. Those losses are
    reported, not just logged, so applying a split on one stock can never
    silently drop another stock's realized gains.
    """
    # Local import: keeps this module importable from tax_service without a
    # circular import if that direction is ever added.
    from app.services.tax_service import compute_tax_for_transaction

    report: dict = {"recomputed": [], "failed": [], "records_removed": []}
    targets = await _sell_txn_ids_with_tax_records(holding_id, user_id, db)
    if not targets:
        return report

    before = await _txn_ids_with_tax_records(user_id, db)
    for txn_id in targets:
        try:
            await compute_tax_for_transaction(txn_id, user_id, db)
            report["recomputed"].append(txn_id)
        except ValueError as exc:
            # e.g. "No purchase lots available" — a sale the re-based ledger
            # can no longer back. Never abort the corporate-action apply.
            logger.warning(
                "Corporate action: tax recompute of txn=%d failed (%s)", txn_id, exc
            )
            report["failed"].append(txn_id)

    after = await _txn_ids_with_tax_records(user_id, db)
    removed = sorted(before - after)
    if removed:
        report["records_removed"] = removed
        logger.warning(
            "Corporate action on holding=%d dropped the tax records of "
            "transactions %s — they no longer match any FIFO buy lot and must "
            "be re-entered or recomputed by hand",
            holding_id,
            removed,
        )
    return report


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

async def apply_corporate_action(
    action_id: int, user_id: int, db: AsyncSession
) -> dict:
    """Apply a DETECTED split/bonus to its holding.

    Only shares held *as of the ex-date* are adjusted; shares bought after it
    already trade at the post-split price, and multiplying the *current*
    cumulative quantity would double-adjust them.

    A SPLIT re-bases the ledger rows dated on/before the ex-date in place —
    ``quantity * ratio``, ``price / ratio`` — because a subdivision is not an
    acquisition: the cost is spread over the enlarged share count and the
    original acquisition date is inherited (India s.55(2)(b)(v) / s.2(42A)
    Expl. 1; Germany s.20 EStG, steuerneutral). Each row's total consideration
    is unchanged, so realized gains, gain types and purchase dates survive the
    restatement, and the FIFO queue keeps exactly the lots it had.

    An Indian BONUS issue instead writes the zero-cost allotment row dated at
    the ex-date that its nil cost of acquisition (s.55(2)(aa)(iiia)) and
    allotment-date holding period require.

    Tax records already computed for this holding's sells are then recomputed
    in ``(sale_date, transaction_id)`` order — see
    :func:`recompute_tax_after_ledger_change`.

    Idempotent: an already-APPLIED action is returned unchanged. A DISMISSED
    action cannot be applied.
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

    # Quantity held as of the ex-date, from the transaction ledger.
    tx_result = await db.execute(
        select(Transaction).where(Transaction.holding_id == holding.id)
    )
    transactions = list(tx_result.scalars().all())
    qty_at_ex = 0.0
    for tx in transactions:
        if action.ex_date is not None and tx.date > action.ex_date:
            continue
        if tx.transaction_type == "BUY":
            qty_at_ex += float(tx.quantity)
        elif tx.transaction_type == "SELL":
            qty_at_ex -= float(tx.quantity)

    treatment = _treatment_for(action, holding)
    txn_written = False
    rebased = 0
    if transactions:
        # ``qty_at_ex > 0`` guard: with nothing held on the ex-date there is
        # nothing to re-base (or to allot against). Ledgers that oversell at a
        # point in time — reachable via a backdated SELL, which is validated
        # against the CURRENT quantity — land here, and touching them would
        # change the holding's quantity rather than just its unit of account.
        if qty_at_ex > 0 and ratio != 1.0:
            if treatment == _ALLOTMENT:
                # Indian bonus issue: a genuine acquisition at NIL cost, dated
                # at the allotment (ex-)date. ``qty_at_ex * (ratio - 1)`` is
                # the number of shares allotted.
                db.add(
                    Transaction(
                        holding_id=holding.id,
                        transaction_type="BUY",
                        date=action.ex_date,
                        quantity=qty_at_ex * (ratio - 1),
                        price=0,
                        brokerage=0,
                        notes=(
                            f"{action.action_type} allotment (ratio {ratio}) "
                            "— nil cost of acquisition, auto"
                        ),
                        source="MANUAL",
                    )
                )
                txn_written = True
            else:
                # Split/subdivision: re-base the rows dated on/before the
                # ex-date. BUYs and SELLs alike — skipping the SELLs would
                # leave the residual quantity wrong. ``brokerage`` is left
                # alone: it is a per-transaction amount that tax_service
                # amortises as brokerage/quantity, so the per-share load
                # re-bases with the quantity and its total is invariant.
                r = Decimal(str(ratio))
                for tx in transactions:
                    if action.ex_date is not None and tx.date > action.ex_date:
                        continue
                    if _rebase_row(tx, r):
                        rebased += 1
            await db.flush()

        # Recompute quantity/average from the ledger so the stored numbers
        # derive from the transactions (post-ex-date buys stay untouched).
        holding = await calculate_cumulative_holding(holding.id, db)
    else:
        # No ledger to derive from (holding seeded directly): fall back to a
        # direct adjustment of the stored quantity/average.
        holding.cumulative_quantity = old_qty * ratio
        holding.average_price = round(old_avg / ratio, 4)
        holding.action_needed = determine_action_needed(
            holding.current_price, holding
        )

    new_qty = float(holding.cumulative_quantity)
    new_avg = float(holding.average_price)

    # Recompute the tax records this action invalidated. Never let a tax
    # failure abort the apply — the ledger change is already correct.
    tax_recompute: dict = {"recomputed": [], "failed": [], "records_removed": []}
    if rebased or txn_written:
        try:
            tax_recompute = await recompute_tax_after_ledger_change(
                holding.id, user_id, db
            )
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "Corporate action %s: tax recompute failed for holding=%d",
                action.id, holding.id,
            )
            tax_recompute = {
                "recomputed": [], "failed": [], "records_removed": [], "error": True
            }

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
            "quantity_at_ex_date": qty_at_ex,
            "cost_basis": round(cost_basis, 2),
            "ratio": ratio,
            "treatment": treatment,
            "adjustment_transaction": txn_written,
            # Count only: the restatement is fully described by (ratio,
            # ex_date) and reverses by scaling with 1 / ratio, so a per-row
            # snapshot here would only bloat every list response.
            "rebased_transactions": rebased,
            "tax_recompute": tax_recompute,
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
