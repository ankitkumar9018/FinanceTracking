"""Earnings Calendar API — upcoming earnings dates for holdings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.portfolio import Portfolio
from app.models.user import User
from app.schemas.earnings import PortfolioEarningsResponse, StockEarnings
from app.services.earnings_service import get_portfolio_earnings, get_stock_earnings

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _verify_portfolio_ownership(
    portfolio_id: int,
    user: User,
    db: AsyncSession,
) -> Portfolio:
    """Ensure the portfolio exists and belongs to the user."""
    from sqlalchemy import select

    result = await db.execute(
        select(Portfolio).where(
            Portfolio.id == portfolio_id,
            Portfolio.user_id == user.id,
        )
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portfolio not found or does not belong to the current user",
        )
    return portfolio


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
    await _verify_portfolio_ownership(portfolio_id, user, db)

    try:
        return await get_portfolio_earnings(portfolio_id, db)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
