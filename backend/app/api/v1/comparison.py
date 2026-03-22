"""Stock comparison, analysis, and stop-loss tracking endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.user import User
from app.services.comparison_service import compare_stocks
from app.services.stop_loss_service import (
    get_stop_loss_holdings,
    remove_stop_loss,
    set_stop_loss,
)
from app.services.xirr_service import CashFlow, xirr

router = APIRouter()


# ---------------------------------------------------------------------------
# Stock Comparison
# ---------------------------------------------------------------------------

@router.get("/compare")
async def compare(
    symbols: str = Query(..., description="Comma-separated stock symbols (max 3)"),
    exchanges: str = Query("NSE", description="Comma-separated exchanges"),
    days: int = Query(90, ge=7, le=365),
    user: User = Depends(get_current_user),
):
    """Compare 2-3 stocks side by side with metrics and price history."""
    symbol_list = [s.strip().upper() for s in symbols.split(",")][:3]
    exchange_list = [e.strip().upper() for e in exchanges.split(",")]
    result = await compare_stocks(symbol_list, exchange_list, days)
    return {
        "stocks": [
            {
                "symbol": s.symbol,
                "name": s.name,
                "exchange": s.exchange,
                "current_price": s.current_price,
                "day_change_pct": s.day_change_pct,
                "week_52_high": s.week_52_high,
                "week_52_low": s.week_52_low,
                "pe_ratio": s.pe_ratio,
                "market_cap": s.market_cap,
                "volume": s.volume,
                "dividend_yield": s.dividend_yield,
                "beta": s.beta,
            }
            for s in result.stocks
        ],
        "price_history": result.price_history,
        "period_days": result.period_days,
    }


# ---------------------------------------------------------------------------
# Stop-Loss Tracking
# ---------------------------------------------------------------------------

async def _verify_portfolio_ownership(
    portfolio_id: int, user: User, db: AsyncSession
) -> Portfolio:
    """Ensure the portfolio belongs to the current user."""
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
            detail="Portfolio not found",
        )
    return portfolio


async def _verify_holding_ownership(
    holding_id: int, user: User, db: AsyncSession
) -> Holding:
    """Ensure the holding belongs to a portfolio owned by the current user."""
    result = await db.execute(
        select(Holding)
        .join(Portfolio, Holding.portfolio_id == Portfolio.id)
        .where(
            Holding.id == holding_id,
            Portfolio.user_id == user.id,
        )
    )
    holding = result.scalar_one_or_none()
    if holding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Holding not found",
        )
    return holding


@router.get("/stop-loss/{portfolio_id}")
async def get_stop_losses(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all stop-loss statuses for a portfolio."""
    await _verify_portfolio_ownership(portfolio_id, user, db)
    statuses = await get_stop_loss_holdings(portfolio_id, db)
    return {
        "portfolio_id": portfolio_id,
        "stop_losses": [
            {
                "holding_id": s.holding_id,
                "stock_symbol": s.stock_symbol,
                "stock_name": s.stock_name,
                "current_price": s.current_price,
                "stop_loss_price": s.stop_loss_price,
                "distance_pct": s.distance_pct,
                "is_triggered": s.is_triggered,
            }
            for s in statuses
        ],
        "triggered_count": sum(1 for s in statuses if s.is_triggered),
    }


@router.put("/stop-loss/{holding_id}")
async def set_stop_loss_endpoint(
    holding_id: int,
    price: float = Query(..., gt=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set stop-loss price for a holding."""
    await _verify_holding_ownership(holding_id, user, db)
    try:
        await set_stop_loss(holding_id, price, db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    return {"holding_id": holding_id, "stop_loss_price": price, "status": "set"}


@router.delete("/stop-loss/{holding_id}")
async def remove_stop_loss_endpoint(
    holding_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove stop-loss for a holding."""
    await _verify_holding_ownership(holding_id, user, db)
    try:
        await remove_stop_loss(holding_id, db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    return {"holding_id": holding_id, "status": "removed"}
