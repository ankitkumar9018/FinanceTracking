"""Portfolio business logic: cumulative holding calculations, summary table, action logic."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.transaction import Transaction
from app.services import forex_service
from app.services.alert_service import determine_action_needed


# ---------------------------------------------------------------------------
# Cumulative holding recalculation
# ---------------------------------------------------------------------------

async def calculate_cumulative_holding(holding_id: int, db: AsyncSession) -> Holding:
    """Recalculate a holding's cumulative_quantity and average_price from all
    its transactions.

    Uses a standard weighted-average approach:
    - BUY: adds to quantity and adjusts the weighted average price.
    - SELL: reduces quantity (average price stays the same).

    Returns the updated Holding instance (already flushed).
    """
    result = await db.execute(select(Holding).where(Holding.id == holding_id))
    holding = result.scalar_one_or_none()
    if holding is None:
        raise ValueError(f"Holding {holding_id} not found")

    tx_result = await db.execute(
        select(Transaction)
        .where(Transaction.holding_id == holding_id)
        .order_by(Transaction.date, Transaction.id)
    )
    transactions = tx_result.scalars().all()

    cumulative_qty = Decimal("0")
    total_cost = Decimal("0")

    for tx in transactions:
        qty = Decimal(str(tx.quantity))
        price = Decimal(str(tx.price))

        if tx.transaction_type == "BUY":
            total_cost += qty * price
            cumulative_qty += qty
        elif tx.transaction_type == "SELL":
            if cumulative_qty > 0:
                # Reduce cost proportionally; clamp sell qty to available
                sell_qty = min(qty, cumulative_qty)
                avg = total_cost / cumulative_qty
                cumulative_qty -= sell_qty
                total_cost = avg * cumulative_qty
            else:
                # Edge case: selling with 0 quantity — just set to 0
                cumulative_qty = Decimal("0")
                total_cost = Decimal("0")

    avg_price = (total_cost / cumulative_qty) if cumulative_qty > 0 else Decimal("0")

    holding.cumulative_quantity = float(cumulative_qty)
    holding.average_price = float(avg_price)

    # Also recalculate action_needed if current_price is known
    holding.action_needed = determine_action_needed(holding.current_price, holding)

    await db.flush()
    await db.refresh(holding)
    return holding


# ---------------------------------------------------------------------------
# Portfolio summary (the main output table)
# ---------------------------------------------------------------------------

async def get_portfolio_summary(
    portfolio_id: int,
    db: AsyncSession,
    display_currency: str | None = None,
) -> dict:
    """Build the main output table for a portfolio.

    Returns a dict matching ``PortfolioSummaryResponse`` with one
    ``HoldingSummaryRow`` per holding.

    ``display_currency`` is an *optional, additive* convenience: when provided
    and an actual conversion is needed, extra ``*_display`` fields are appended
    (see ``_add_display_currency``). Every existing field is left untouched and
    stays in its native currency — the display fields are purely additive.
    """
    result = await db.execute(
        select(Portfolio)
        .options(selectinload(Portfolio.holdings))
        .where(Portfolio.id == portfolio_id)
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise ValueError(f"Portfolio {portfolio_id} not found")

    rows: list[dict] = []
    total_invested = 0.0
    total_current_value = 0.0

    for h in portfolio.holdings:
        qty = float(h.cumulative_quantity)
        avg = float(h.average_price)
        invested = qty * avg

        current = float(h.current_price) if h.current_price is not None else avg
        current_value = qty * current

        pnl_percent: float | None = None
        if h.current_price is not None and invested > 0:
            pnl_percent = round(((current_value - invested) / invested) * 100, 2)

        total_invested += invested
        total_current_value += current_value

        rows.append(
            {
                "holding_id": h.id,
                "stock_symbol": h.stock_symbol,
                "stock_name": h.stock_name,
                "exchange": h.exchange,
                "currency": h.currency or portfolio.currency,
                "quantity": qty,
                "avg_price": avg,
                "current_price": current,
                "action_needed": h.action_needed,
                "rsi": h.current_rsi,
                "pnl_percent": pnl_percent,
                "sector": h.sector,
                "base_level": float(h.base_level) if h.base_level else None,
                "lower_mid_range_1": float(h.lower_mid_range_1) if h.lower_mid_range_1 else None,
                "lower_mid_range_2": float(h.lower_mid_range_2) if h.lower_mid_range_2 else None,
                "upper_mid_range_1": float(h.upper_mid_range_1) if h.upper_mid_range_1 else None,
                "upper_mid_range_2": float(h.upper_mid_range_2) if h.upper_mid_range_2 else None,
                "top_level": float(h.top_level) if h.top_level else None,
            }
        )

    total_pnl_percent: float | None = None
    if total_invested > 0:
        total_pnl_percent = round(
            ((total_current_value - total_invested) / total_invested) * 100, 2
        )

    summary = {
        "portfolio_id": portfolio.id,
        "portfolio_name": portfolio.name,
        "currency": portfolio.currency,
        "total_invested": round(total_invested, 2),
        "total_current_value": round(total_current_value, 2),
        "total_pnl_percent": total_pnl_percent,
        "holdings": rows,
    }

    if display_currency:
        # Additive only — never mutates the native fields above. Degrades
        # gracefully: if forex is unavailable, the summary is returned as-is
        # (no ``*_display`` fields) so callers transparently fall back.
        summary = await _add_display_currency(
            summary, portfolio.currency, display_currency, db
        )

    return summary


# ---------------------------------------------------------------------------
# Optional display-currency conversion (additive convenience fields)
# ---------------------------------------------------------------------------

async def _add_display_currency(
    summary: dict,
    base_currency: str,
    display_currency: str,
    db: AsyncSession,
) -> dict:
    """Append converted ``*_display`` convenience fields to a summary dict.

    Converts each holding row from its own native currency into
    ``display_currency`` (so mixed-currency portfolios total correctly), then
    adds portfolio-level ``total_*_display`` figures plus a headline
    ``display_fx_rate`` (base currency -> display currency).

    Returns the summary **unchanged** when no conversion is actually needed
    (target already matches every currency) or when a rate lookup fails — in
    both cases no ``*_display`` fields are added, so existing behaviour and
    callers relying on native values are unaffected.
    """
    target = (display_currency or "").upper()
    base = (base_currency or "INR").upper()
    if not target:
        return summary

    rows = summary.get("holdings", [])
    source_currencies = {
        (row.get("currency") or base).upper() for row in rows
    }
    source_currencies.add(base)

    # Nothing to convert — every value is already in the target currency.
    if source_currencies == {target}:
        return summary

    rate_cache: dict[str, float] = {}

    async def rate_for(src: str) -> float:
        src = (src or base).upper()
        if src == target:
            return 1.0
        if src not in rate_cache:
            rate_cache[src] = await forex_service.get_exchange_rate(
                src, target, None, db
            )
        return rate_cache[src]

    try:
        total_invested_display = 0.0
        total_current_value_display = 0.0

        for row in rows:
            src = (row.get("currency") or base).upper()
            rate = await rate_for(src)
            qty = float(row.get("quantity") or 0.0)
            avg = float(row.get("avg_price") or 0.0)
            current = row.get("current_price")
            current = float(current) if current is not None else avg

            invested_display = qty * avg * rate
            value_display = qty * current * rate
            total_invested_display += invested_display
            total_current_value_display += value_display

            # Per-row convenience values (additive; safe to ignore).
            row["invested_display"] = round(invested_display, 2)
            row["current_value_display"] = round(value_display, 2)

        headline_rate = await rate_for(base)
    except Exception:
        # Forex unavailable — strip any partial per-row display fields so the
        # response stays consistently native, and return unchanged.
        for row in rows:
            row.pop("invested_display", None)
            row.pop("current_value_display", None)
        return summary

    pnl_percent_display: float | None = None
    if total_invested_display > 0:
        pnl_percent_display = round(
            ((total_current_value_display - total_invested_display)
             / total_invested_display) * 100,
            2,
        )

    summary["display_currency"] = target
    summary["display_base_currency"] = base
    summary["display_fx_rate"] = round(headline_rate, 6)
    summary["total_invested_display"] = round(total_invested_display, 2)
    summary["total_current_value_display"] = round(total_current_value_display, 2)
    summary["total_pnl_percent_display"] = pnl_percent_display
    return summary
