"""ESG scoring API — environmental, social, and governance scores."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.portfolio import Portfolio
from app.models.user import User
from app.schemas.esg import PortfolioESGResponse, StockESGScore
from app.services.esg_service import get_esg_scores, get_portfolio_esg

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


@router.get("/stock/{symbol}", response_model=StockESGScore)
async def stock_esg_scores(
    symbol: str,
    exchange: str = Query(default="NSE", description="Exchange code (NSE, BSE, XETRA, etc.)"),
    user: User = Depends(get_current_user),
) -> dict:
    """Get ESG scores for a single stock.

    Returns total ESG score plus environment, social, and governance sub-scores.
    If ESG data is unavailable for the stock, scores will be null.
    """
    results = await get_esg_scores([symbol.upper().strip()], exchange)
    if results:
        return results[0]
    return {
        "symbol": symbol,
        "total_esg": None,
        "environment_score": None,
        "social_score": None,
        "governance_score": None,
        "esg_available": False,
    }


@router.get("/{portfolio_id}", response_model=PortfolioESGResponse)
async def portfolio_esg_dashboard(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get ESG dashboard data for a portfolio.

    Returns weighted average ESG scores across all holdings, plus individual
    stock ESG scores. Weights are based on holding market value.
    """
    await _verify_portfolio_ownership(portfolio_id, user, db)

    try:
        return await get_portfolio_esg(portfolio_id, db)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
