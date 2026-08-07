"""Portfolio statistics helpers: XIRR cash flows and dated market-value series.

Extracted from the portfolio routes (``/xirr`` and ``/benchmark``) so the
route layer stays thin. Both helpers raise ``ValueError("No holdings found in
this portfolio")`` for an empty portfolio; the routes map that to a 404.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.holding import Holding
from app.models.price_history import PriceHistory
from app.services.xirr_service import CashFlow

_NO_HOLDINGS_MESSAGE = "No holdings found in this portfolio"


@dataclass
class XirrCashflows:
    """Cash flows for a portfolio plus the metadata the XIRR route reports."""

    cash_flows: list[CashFlow] = field(default_factory=list)
    total_current_value: float = 0.0
    used_stale_prices: bool = False


async def build_xirr_cashflows(
    portfolio_id: int,
    db: AsyncSession,
) -> XirrCashflows:
    """Build the XIRR cash-flow ledger for a portfolio.

    BUY transactions become negative cash flows, SELLs positive, and the
    portfolio's current market value is appended as a final positive flow
    dated today. Holdings that were never price-refreshed fall back to their
    average price (flagged via ``used_stale_prices``) — otherwise they would
    contribute no terminal value at all and drag the computed return toward a
    total loss.

    Raises ``ValueError`` when the portfolio has no holdings.
    """
    result = await db.execute(
        select(Holding)
        .options(selectinload(Holding.transactions))
        .where(Holding.portfolio_id == portfolio_id)
    )
    holdings = result.scalars().all()

    if not holdings:
        raise ValueError(_NO_HOLDINGS_MESSAGE)

    cash_flows: list[CashFlow] = []
    total_current_value = 0.0
    used_stale_prices = False

    for h in holdings:
        for tx in h.transactions:
            amount = float(tx.quantity) * float(tx.price)
            if tx.transaction_type == "BUY":
                cash_flows.append(CashFlow(date=tx.date, amount=-amount))
            elif tx.transaction_type == "SELL":
                cash_flows.append(CashFlow(date=tx.date, amount=amount))

        terminal_price = (
            h.current_price if h.current_price is not None else h.average_price
        )
        if h.current_price is None:
            used_stale_prices = True
        if terminal_price is not None and h.cumulative_quantity:
            total_current_value += float(terminal_price) * float(h.cumulative_quantity)

    if total_current_value > 0:
        cash_flows.append(CashFlow(date=date.today(), amount=total_current_value))

    return XirrCashflows(
        cash_flows=cash_flows,
        total_current_value=total_current_value,
        used_stale_prices=used_stale_prices,
    )


async def build_daily_value_series(
    portfolio_id: int,
    days: int,
    db: AsyncSession,
) -> list[dict]:
    """Build a dated market-value series for a portfolio from stored prices.

    value_on_day = sum over holdings of (current quantity * that day's close),
    over the last ``days`` days. The PriceHistory query is scoped to the
    portfolio's own (symbol, exchange) pairs — not every symbol in the date
    window. Returns ``[{"date": ISO date, "value": float}, ...]`` sorted by
    date.

    Raises ``ValueError`` when the portfolio has no holdings.
    """
    result = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio_id)
    )
    holdings = result.scalars().all()

    if not holdings:
        raise ValueError(_NO_HOLDINGS_MESSAGE)

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    # Aggregate quantity per (symbol, exchange) so multiple lots collapse.
    qty_by_symbol: dict[tuple[str, str], float] = {}
    for h in holdings:
        key = (h.stock_symbol, h.exchange)
        qty_by_symbol[key] = qty_by_symbol.get(key, 0.0) + float(h.cumulative_quantity)

    pair_conditions = [
        and_(PriceHistory.stock_symbol == sym, PriceHistory.exchange == exch)
        for sym, exch in qty_by_symbol
    ]
    ph_result = await db.execute(
        select(PriceHistory).where(
            PriceHistory.date >= start_date,
            PriceHistory.date <= end_date,
            or_(*pair_conditions),
        )
    )
    price_rows = ph_result.scalars().all()

    daily_totals: dict[date, float] = {}
    for row in price_rows:
        qty = qty_by_symbol.get((row.stock_symbol, row.exchange))
        if qty is None:
            continue
        daily_totals[row.date] = daily_totals.get(row.date, 0.0) + qty * float(row.close)

    return [
        {"date": d.isoformat(), "value": v}
        for d, v in sorted(daily_totals.items())
    ]
