"""Dividend service: recording, DRIP handling, yield calculation."""

from __future__ import annotations

import asyncio
import logging
import math
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.dividend import Dividend
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.schemas.dividend import DividendCreate
from app.services.market_data_service import _ticker_symbol

logger = logging.getLogger(__name__)

# Bound concurrent yfinance calls during forecasting.
_FORECAST_CONCURRENCY = 6
_FORECAST_TIMEOUT_S = 12.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_holding_for_user(
    holding_id: int,
    user_id: int,
    db: AsyncSession,
) -> Holding:
    """Fetch a holding ensuring it belongs to a portfolio owned by the user."""
    result = await db.execute(
        select(Holding)
        .join(Portfolio, Holding.portfolio_id == Portfolio.id)
        .where(Holding.id == holding_id, Portfolio.user_id == user_id)
    )
    holding = result.scalar_one_or_none()
    if holding is None:
        raise ValueError("Holding not found or does not belong to the current user")
    return holding


# ---------------------------------------------------------------------------
# Create dividend
# ---------------------------------------------------------------------------

async def create_dividend(
    data: DividendCreate,
    user_id: int,
    db: AsyncSession,
) -> Dividend:
    """Record a dividend payment for a holding.

    If the dividend is reinvested (DRIP) and reinvest_shares is provided,
    the holding's cumulative_quantity and average_price are updated
    accordingly.
    """
    holding = await _get_holding_for_user(data.holding_id, user_id, db)

    dividend = Dividend(
        holding_id=data.holding_id,
        ex_date=data.ex_date,
        payment_date=data.payment_date,
        amount_per_share=data.amount_per_share,
        total_amount=data.total_amount,
        is_reinvested=data.is_reinvested,
        reinvest_price=data.reinvest_price,
        reinvest_shares=data.reinvest_shares,
    )
    db.add(dividend)
    await db.flush()

    # DRIP: add reinvested shares to holding
    if data.is_reinvested and data.reinvest_shares is not None:
        old_qty = Decimal(str(float(holding.cumulative_quantity)))
        old_avg = Decimal(str(float(holding.average_price)))
        drip_shares = Decimal(str(data.reinvest_shares))
        drip_price = (
            Decimal(str(data.reinvest_price))
            if data.reinvest_price is not None
            else old_avg
        )

        new_qty = old_qty + drip_shares
        if new_qty > 0:
            total_cost = (old_qty * old_avg) + (drip_shares * drip_price)
            new_avg = total_cost / new_qty
        else:
            new_avg = Decimal("0")

        holding.cumulative_quantity = float(new_qty)
        holding.average_price = float(new_avg)
        await db.flush()

    await db.refresh(dividend)
    return dividend


# ---------------------------------------------------------------------------
# List dividends
# ---------------------------------------------------------------------------

async def list_dividends(
    holding_id: int | None,
    user_id: int,
    db: AsyncSession,
) -> list[dict]:
    """List dividends for a specific holding or all user's holdings.

    Results are ordered by ex_date descending.  Each dict includes
    ``holding_symbol`` and ``holding_name`` resolved from the related holding.
    """
    stmt = (
        select(Dividend)
        .join(Holding, Dividend.holding_id == Holding.id)
        .join(Portfolio, Holding.portfolio_id == Portfolio.id)
        .where(Portfolio.user_id == user_id)
        .options(joinedload(Dividend.holding))
    )

    if holding_id is not None:
        stmt = stmt.where(Dividend.holding_id == holding_id)

    stmt = stmt.order_by(Dividend.ex_date.desc())
    result = await db.execute(stmt)
    dividends = list(result.unique().scalars().all())

    enriched: list[dict] = []
    for div in dividends:
        d = {
            "id": div.id,
            "holding_id": div.holding_id,
            "ex_date": div.ex_date,
            "payment_date": div.payment_date,
            "amount_per_share": float(div.amount_per_share),
            "total_amount": float(div.total_amount),
            "is_reinvested": div.is_reinvested,
            "reinvest_price": float(div.reinvest_price) if div.reinvest_price is not None else None,
            "reinvest_shares": float(div.reinvest_shares) if div.reinvest_shares else None,
            "created_at": div.created_at,
            "holding_symbol": div.holding.stock_symbol if div.holding else None,
            "holding_name": div.holding.stock_name if div.holding else None,
        }
        enriched.append(d)
    return enriched


# ---------------------------------------------------------------------------
# Dividend summary
# ---------------------------------------------------------------------------

async def get_dividend_summary(user_id: int, db: AsyncSession) -> dict:
    """Compute a dividend summary for the user.

    Returns:
        total_dividends: sum of all total_amount values
        total_reinvested: sum of total_amount where is_reinvested is True
        dividend_yield: (total annual dividends / total portfolio value) * 100
        count: number of dividend records
        calendar: list of {month, amount} grouped by YYYY-MM
    """
    # Fetch all dividends for the user
    stmt = (
        select(Dividend)
        .join(Holding, Dividend.holding_id == Holding.id)
        .join(Portfolio, Holding.portfolio_id == Portfolio.id)
        .where(Portfolio.user_id == user_id)
        .order_by(Dividend.ex_date.asc())
    )
    result = await db.execute(stmt)
    dividends = result.scalars().all()

    total_dividends = 0.0
    total_reinvested = 0.0
    annual_dividends = 0.0  # Trailing 12 months only
    monthly: dict[str, float] = defaultdict(float)
    one_year_ago = date.today() - timedelta(days=365)

    for div in dividends:
        amount = float(div.total_amount)
        total_dividends += amount

        if div.is_reinvested:
            total_reinvested += amount

        if div.ex_date >= one_year_ago:
            annual_dividends += amount

        month_key = div.ex_date.strftime("%Y-%m")
        monthly[month_key] += amount

    # Dividend yield: trailing 12-month dividends / total portfolio value
    holdings_stmt = (
        select(Holding)
        .join(Portfolio, Holding.portfolio_id == Portfolio.id)
        .where(Portfolio.user_id == user_id)
    )
    holdings_result = await db.execute(holdings_stmt)
    holdings = holdings_result.scalars().all()

    total_portfolio_value = 0.0
    total_invested = 0.0
    for h in holdings:
        qty = float(h.cumulative_quantity)
        avg = float(h.average_price)
        price = float(h.current_price) if h.current_price is not None else avg
        total_portfolio_value += qty * price
        total_invested += qty * avg

    dividend_yield: float | None = None
    if total_portfolio_value > 0 and annual_dividends > 0:
        dividend_yield = round((annual_dividends / total_portfolio_value) * 100, 2)

    # Portfolio-wide yield-on-cost: trailing 12-month dividends over cost basis.
    yield_on_cost: float | None = None
    if total_invested > 0 and annual_dividends > 0:
        yield_on_cost = round((annual_dividends / total_invested) * 100, 2)

    calendar = [
        {"month": month, "amount": round(amount, 2)}
        for month, amount in sorted(monthly.items())
    ]

    return {
        "total_dividends": round(total_dividends, 2),
        "dividend_yield": dividend_yield,
        "yield_on_cost": yield_on_cost,
        "total_reinvested": round(total_reinvested, 2),
        "count": len(dividends),
        "calendar": calendar,
    }


# ---------------------------------------------------------------------------
# Forward dividend income forecast
# ---------------------------------------------------------------------------

def _sync_fetch_dividend_forecast(ticker_str: str) -> dict | None:
    """Fetch dividend history + rate for a symbol (runs in a thread).

    Returns forecast primitives ``{annual_rate, pay_months, frequency}`` where
    ``annual_rate`` is the estimated annual dividend *per share*, ``pay_months``
    is the sorted set of calendar months (1-12) historically paid in the
    trailing year, and ``frequency`` is the number of payments per year.

    Returns ``None`` when no usable dividend data is available.
    """
    ticker = yf.Ticker(ticker_str)

    # Prefer explicit rate fields from .info when present.
    annual_rate = None
    try:
        info = ticker.info or {}
        annual_rate = info.get("dividendRate") or info.get("trailingAnnualDividendRate")
    except Exception:
        pass

    pay_months: list[int] = []
    frequency: int | None = None

    # Derive the trailing pay pattern / frequency from the dividend history.
    try:
        divs = ticker.dividends
    except Exception:
        divs = None

    if divs is not None and len(divs) > 0:
        events: list[tuple[date, float]] = []
        for ts, val in divs.items():
            try:
                d = ts.date() if hasattr(ts, "date") else None
                amt = float(val)
            except (TypeError, ValueError, AttributeError):
                continue
            if d is not None and amt > 0:
                events.append((d, amt))

        if events:
            events.sort(key=lambda e: e[0])
            last_date = events[-1][0]
            cutoff = last_date - timedelta(days=365)
            recent = [(d, a) for (d, a) in events if d > cutoff]
            if recent:
                pay_months = sorted({d.month for (d, a) in recent})
                frequency = len(recent)
                trailing_sum = sum(a for (d, a) in recent)
                # Fall back to trailing-sum when .info gave nothing usable.
                if not annual_rate or float(annual_rate) <= 0:
                    annual_rate = trailing_sum

    try:
        annual_rate = float(annual_rate) if annual_rate is not None else 0.0
    except (TypeError, ValueError):
        annual_rate = 0.0

    # Guard against NaN / non-positive rates.
    if math.isnan(annual_rate) or annual_rate <= 0:
        return None

    if not frequency or frequency <= 0:
        frequency = len(pay_months) if pay_months else 4

    return {
        "annual_rate": annual_rate,
        "pay_months": pay_months,
        "frequency": frequency,
    }


def _forward_months(start_year: int, start_month: int) -> list[tuple[int, int]]:
    """Return 12 (year, month) tuples starting at the given year/month."""
    months: list[tuple[int, int]] = []
    y, m = start_year, start_month
    for _ in range(12):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def _holding_monthly_schedule(
    prim: dict, forward_months: list[tuple[int, int]]
) -> dict[str, float]:
    """Per-share dividend amount keyed by ``YYYY-MM`` across the forward window.

    The per-share amounts always sum to ``annual_rate`` over the 12-month
    window (each calendar month appears exactly once in any 12 consecutive
    months), keeping the forward total consistent with the annual estimate.
    """
    annual_rate: float = prim["annual_rate"]
    pay_months: list[int] = prim["pay_months"]
    frequency: int = prim["frequency"]
    schedule: dict[str, float] = {}

    if pay_months:
        per = annual_rate / len(pay_months)
        for (y, m) in forward_months:
            if m in pay_months:
                schedule[f"{y:04d}-{m:02d}"] = per
    else:
        # No historical months known: spread `frequency` payments evenly.
        n = max(1, min(12, frequency))
        per = annual_rate / n
        step = max(1, 12 // n)
        placed = 0
        idx = 0
        while placed < n and idx < 12:
            y, m = forward_months[idx]
            schedule[f"{y:04d}-{m:02d}"] = per
            idx += step
            placed += 1
    return schedule


async def get_dividend_forecast(user_id: int, db: AsyncSession) -> dict:
    """Estimate the next 12 months of dividend income for the user's holdings.

    Best-effort: symbols without dividend data are skipped. yfinance calls run
    in threads with bounded concurrency.

    Returns::

        {
            "monthly": [{"month": "YYYY-MM", "amount": float}, ...],  # 12 entries
            "total_forward_12m": float,
            "forward_yield_pct": float | None,
            "by_holding": [
                {"symbol", "exchange", "annual_estimate",
                 "yield_pct", "yield_on_cost_pct"}, ...
            ],
        }
    """
    holdings_stmt = (
        select(Holding)
        .join(Portfolio, Holding.portfolio_id == Portfolio.id)
        .where(Portfolio.user_id == user_id)
    )
    holdings_result = await db.execute(holdings_stmt)
    holdings = list(holdings_result.scalars().all())

    sem = asyncio.Semaphore(_FORECAST_CONCURRENCY)

    async def _fetch(h: Holding) -> tuple[Holding, dict | None]:
        async with sem:
            try:
                prim = await asyncio.wait_for(
                    asyncio.to_thread(
                        _sync_fetch_dividend_forecast,
                        _ticker_symbol(h.stock_symbol, h.exchange),
                    ),
                    timeout=_FORECAST_TIMEOUT_S,
                )
            except Exception:
                logger.debug("Dividend forecast fetch failed for %s", h.stock_symbol)
                prim = None
            return h, prim

    results = await asyncio.gather(*[_fetch(h) for h in holdings]) if holdings else []

    today = date.today()
    forward_months = _forward_months(today.year, today.month)

    monthly_totals: dict[str, float] = defaultdict(float)
    by_holding: list[dict] = []
    total_current_value = 0.0
    total_forward = 0.0

    for h, prim in results:
        qty = float(h.cumulative_quantity)
        avg = float(h.average_price)
        price = float(h.current_price) if h.current_price is not None else avg
        total_current_value += qty * price

        if not prim:
            continue

        annual_rate = prim["annual_rate"]
        annual_estimate = annual_rate * qty

        schedule = _holding_monthly_schedule(prim, forward_months)
        for month_key, per_share in schedule.items():
            amount = per_share * qty
            monthly_totals[month_key] += amount
            total_forward += amount

        yield_pct = round(annual_rate / price * 100, 2) if price > 0 else None
        yield_on_cost_pct = round(annual_rate / avg * 100, 2) if avg > 0 else None

        by_holding.append(
            {
                "symbol": h.stock_symbol,
                "exchange": h.exchange,
                "annual_estimate": round(annual_estimate, 2),
                "yield_pct": yield_pct,
                "yield_on_cost_pct": yield_on_cost_pct,
            }
        )

    monthly = [
        {"month": f"{y:04d}-{m:02d}", "amount": round(monthly_totals.get(f"{y:04d}-{m:02d}", 0.0), 2)}
        for (y, m) in forward_months
    ]

    forward_yield_pct: float | None = None
    if total_current_value > 0 and total_forward > 0:
        forward_yield_pct = round(total_forward / total_current_value * 100, 2)

    by_holding.sort(key=lambda x: x["annual_estimate"], reverse=True)

    return {
        "monthly": monthly,
        "total_forward_12m": round(total_forward, 2),
        "forward_yield_pct": forward_yield_pct,
        "by_holding": by_holding,
    }


# ---------------------------------------------------------------------------
# Delete dividend
# ---------------------------------------------------------------------------

async def delete_dividend(
    dividend_id: int,
    user_id: int,
    db: AsyncSession,
) -> None:
    """Delete a dividend record.

    If the dividend was reinvested, reverses the DRIP adjustment on the
    holding's cumulative_quantity and average_price.
    """
    # Fetch the dividend with ownership verification
    stmt = (
        select(Dividend)
        .join(Holding, Dividend.holding_id == Holding.id)
        .join(Portfolio, Holding.portfolio_id == Portfolio.id)
        .where(Dividend.id == dividend_id, Portfolio.user_id == user_id)
    )
    result = await db.execute(stmt)
    dividend = result.scalar_one_or_none()
    if dividend is None:
        raise ValueError("Dividend not found or does not belong to the current user")

    # If it was reinvested, reverse the quantity/avg_price adjustment
    if dividend.is_reinvested and dividend.reinvest_shares is not None:
        holding = await _get_holding_for_user(dividend.holding_id, user_id, db)

        old_qty = Decimal(str(float(holding.cumulative_quantity)))
        old_avg = Decimal(str(float(holding.average_price)))
        drip_shares = Decimal(str(float(dividend.reinvest_shares)))
        drip_price = (
            Decimal(str(float(dividend.reinvest_price)))
            if dividend.reinvest_price is not None
            else old_avg
        )

        new_qty = old_qty - drip_shares
        if new_qty > 0:
            # Reverse: total_cost = (old_qty * old_avg) - (drip_shares * drip_price)
            total_cost = (old_qty * old_avg) - (drip_shares * drip_price)
            new_avg = total_cost / new_qty
        else:
            new_qty = Decimal("0")
            new_avg = Decimal("0")

        holding.cumulative_quantity = float(new_qty)
        holding.average_price = float(new_avg)

    await db.delete(dividend)
    await db.flush()
