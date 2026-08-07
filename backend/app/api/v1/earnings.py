"""Earnings Calendar API — upcoming earnings dates for holdings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, verify_portfolio_ownership
from app.api.errors import map_value_error
from app.database import get_db
from app.models.user import User
from app.schemas.earnings import PortfolioEarningsResponse, StockEarnings
from app.services.earnings_service import get_portfolio_earnings, get_stock_earnings

router = APIRouter()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/stock/{symbol}", response_model=StockEarnings)
async def stock_earnings(
    symbol: str,
    exchange: str = Query(default="NSE", description="Exchange code (NSE, BSE, XETRA, etc.)"),
    user: User = Depends(get_current_user),
) -> dict:
    """Get earnings calendar info for a single stock.

    Returns upcoming earnings dates, revenue estimates, and earnings estimates.
    """
    return await get_stock_earnings(symbol.upper().strip(), exchange)


@router.get("/{portfolio_id}", response_model=PortfolioEarningsResponse)
async def portfolio_earnings(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get upcoming earnings dates for all holdings in a portfolio.

    Returns earnings dates, revenue estimates, and earnings estimates
    for each holding. Holdings are sorted by nearest earnings date.
    """
    await verify_portfolio_ownership(portfolio_id, user, db)

    try:
        return await get_portfolio_earnings(portfolio_id, db)
    except ValueError as e:
        raise map_value_error(e) from e
