"""Mutual fund service: NAV fetching, XIRR calculation, portfolio tracking."""

from __future__ import annotations

import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mutual_fund import MutualFund
from app.models.portfolio import Portfolio
from app.schemas.mutual_fund import MutualFundCreate, MutualFundUpdate

logger = logging.getLogger(__name__)

MFAPI_BASE = "https://api.mfapi.in/mf"
HTTP_TIMEOUT = 10.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_portfolio_for_user(
    portfolio_id: int,
    user_id: int,
    db: AsyncSession,
) -> Portfolio:
    """Fetch a portfolio ensuring it belongs to the user."""
    result = await db.execute(
        select(Portfolio).where(
            Portfolio.id == portfolio_id,
            Portfolio.user_id == user_id,
        )
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise ValueError("Portfolio not found or does not belong to the current user")
    return portfolio


async def _get_fund_for_user(
    fund_id: int,
    user_id: int,
    db: AsyncSession,
) -> MutualFund:
    """Fetch a mutual fund ensuring it belongs to a portfolio owned by the user."""
    result = await db.execute(
        select(MutualFund)
        .join(Portfolio, MutualFund.portfolio_id == Portfolio.id)
        .where(MutualFund.id == fund_id, Portfolio.user_id == user_id)
    )
    fund = result.scalar_one_or_none()
    if fund is None:
        raise ValueError("Mutual fund not found or does not belong to the current user")
    return fund


# ---------------------------------------------------------------------------
# NAV fetching from mfapi.in
# ---------------------------------------------------------------------------

async def fetch_nav(scheme_code: str) -> float | None:
    """Fetch the latest NAV for a mutual fund scheme from mfapi.in.

    Returns the NAV as a float, or None on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(f"{MFAPI_BASE}/{scheme_code}/latest")
            resp.raise_for_status()
            data = resp.json()

            # mfapi.in returns {"meta": {...}, "data": [{"date": "...", "nav": "..."}]}
            nav_data = data.get("data")
            if nav_data and len(nav_data) > 0:
                nav_str = nav_data[0].get("nav")
                if nav_str is not None:
                    return float(nav_str)
    except Exception:
        logger.warning("Failed to fetch NAV for scheme %s", scheme_code, exc_info=True)

    return None


async def search_schemes(query: str) -> list[dict]:
    """Search mutual fund schemes by name on mfapi.in.

    Returns a list of {scheme_code, scheme_name} dicts.
    """
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(f"{MFAPI_BASE}/search", params={"q": query})
            resp.raise_for_status()
            data = resp.json()

            # mfapi.in returns a list of {"schemeCode": ..., "schemeName": ...}
            results: list[dict] = []
            if isinstance(data, list):
                for item in data:
                    results.append({
                        "scheme_code": str(item.get("schemeCode", "")),
                        "scheme_name": item.get("schemeName", ""),
                    })
            return results
    except Exception:
        logger.warning("Failed to search schemes for query %r", query, exc_info=True)

    return []


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------

async def create_mutual_fund(
    data: MutualFundCreate,
    user_id: int,
    db: AsyncSession,
) -> MutualFund:
    """Create a new mutual fund record in a user's portfolio.

    Attempts to fetch the current NAV and set current_value automatically.
    """
    await _get_portfolio_for_user(data.portfolio_id, user_id, db)

    fund = MutualFund(
        portfolio_id=data.portfolio_id,
        scheme_code=data.scheme_code,
        scheme_name=data.scheme_name,
        folio_number=data.folio_number,
        units=data.units,
        nav=data.nav,
        invested_amount=data.invested_amount,
    )

    # Try to fetch the current NAV and compute current value
    current_nav = await fetch_nav(data.scheme_code)
    if current_nav is not None:
        fund.nav = current_nav
        fund.current_value = round(data.units * current_nav, 4)
    else:
        # Fall back to user-provided NAV for current value
        fund.current_value = round(data.units * data.nav, 4)

    db.add(fund)
    await db.flush()
    await db.refresh(fund)
    return fund


async def list_mutual_funds(
    portfolio_id: int | None,
    user_id: int,
    db: AsyncSession,
) -> list[MutualFund]:
    """List mutual funds for a specific portfolio or all user's portfolios."""
    stmt = (
        select(MutualFund)
        .join(Portfolio, MutualFund.portfolio_id == Portfolio.id)
        .where(Portfolio.user_id == user_id)
    )

    if portfolio_id is not None:
        stmt = stmt.where(MutualFund.portfolio_id == portfolio_id)

    stmt = stmt.order_by(MutualFund.scheme_name.asc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_mutual_fund(
    fund_id: int,
    user_id: int,
    data: MutualFundUpdate,
    db: AsyncSession,
) -> MutualFund:
    """Update a mutual fund's fields."""
    fund = await _get_fund_for_user(fund_id, user_id, db)

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(fund, key, value)

    await db.flush()
    await db.refresh(fund)
    return fund


async def delete_mutual_fund(
    fund_id: int,
    user_id: int,
    db: AsyncSession,
) -> None:
    """Delete a mutual fund record after verifying ownership."""
    fund = await _get_fund_for_user(fund_id, user_id, db)
    await db.delete(fund)
    await db.flush()


# ---------------------------------------------------------------------------
# Refresh NAVs
# ---------------------------------------------------------------------------

async def refresh_all_navs(user_id: int, db: AsyncSession) -> dict:
    """Refresh current_value for all of a user's mutual funds by fetching
    the latest NAV from mfapi.in.

    Returns a dict with counts of updated and failed funds.
    """
    funds = await list_mutual_funds(portfolio_id=None, user_id=user_id, db=db)

    updated = 0
    failed = 0

    for fund in funds:
        nav = await fetch_nav(fund.scheme_code)
        if nav is not None:
            fund.nav = nav
            fund.current_value = round(float(fund.units) * nav, 4)
            updated += 1
        else:
            failed += 1

    if updated > 0:
        await db.flush()

    return {"updated": updated, "failed": failed, "total": len(funds)}


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

async def get_mf_summary(user_id: int, db: AsyncSession) -> dict:
    """Compute a mutual fund summary for the user.

    Returns:
        total_invested: sum of invested_amount
        total_current_value: sum of current_value (or invested_amount if null)
        total_gain: total_current_value - total_invested
        gain_percent: (total_gain / total_invested) * 100
        xirr: None (placeholder -- needs cash flow history)
        fund_count: number of MF records
    """
    funds = await list_mutual_funds(portfolio_id=None, user_id=user_id, db=db)

    total_invested = 0.0
    total_current_value = 0.0

    for fund in funds:
        invested = float(fund.invested_amount)
        current = float(fund.current_value) if fund.current_value is not None else invested
        total_invested += invested
        total_current_value += current

    total_gain = total_current_value - total_invested
    gain_percent: float | None = None
    if total_invested > 0:
        gain_percent = round((total_gain / total_invested) * 100, 2)

    return {
        "total_invested": round(total_invested, 2),
        "total_current_value": round(total_current_value, 2),
        "total_gain": round(total_gain, 2),
        "gain_percent": gain_percent,
        "xirr": None,  # Placeholder: needs cash flow history for proper calculation
        "fund_count": len(funds),
    }
