"""Dividend service: recording, DRIP handling, yield calculation."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.dividend import Dividend
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.schemas.dividend import DividendCreate

logger = logging.getLogger(__name__)


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
        drip_price = Decimal(str(data.reinvest_price)) if data.reinvest_price else Decimal("0")

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
            "reinvest_price": float(div.reinvest_price) if div.reinvest_price else None,
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
    for h in holdings:
        qty = float(h.cumulative_quantity)
        price = float(h.current_price) if h.current_price is not None else float(h.average_price)
        total_portfolio_value += qty * price

    dividend_yield: float | None = None
    if total_portfolio_value > 0 and annual_dividends > 0:
        dividend_yield = round((annual_dividends / total_portfolio_value) * 100, 2)

    calendar = [
        {"month": month, "amount": round(amount, 2)}
        for month, amount in sorted(monthly.items())
    ]

    return {
        "total_dividends": round(total_dividends, 2),
        "dividend_yield": dividend_yield,
        "total_reinvested": round(total_reinvested, 2),
        "count": len(dividends),
        "calendar": calendar,
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
        drip_price = Decimal(str(float(dividend.reinvest_price))) if dividend.reinvest_price else Decimal("0")

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
