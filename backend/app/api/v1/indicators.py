"""Technical indicators & risk metrics endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User

router = APIRouter()


@router.get("/technical/{symbol}")
async def get_technical_indicators(
    symbol: str,
    exchange: str = Query(default="NSE"),
    days: int = Query(default=90, ge=7, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get all technical indicators for a stock."""
    from app.ml.technical_indicators import get_all_indicators

    return await get_all_indicators(symbol, exchange, db, days)


@router.get("/risk/{portfolio_id}")
async def get_portfolio_risk(
    portfolio_id: int,
    days: int = Query(default=252, ge=30, le=1000),
    benchmark: str = Query(default="^NSEI"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get portfolio-level risk metrics."""
    from dataclasses import asdict

    from app.ml.risk_calculator import compute_portfolio_risk

    metrics = await compute_portfolio_risk(
        user.id, portfolio_id, db, days, benchmark
    )
    return asdict(metrics)


@router.get("/risk/{portfolio_id}/holdings")
async def get_holdings_risk(
    portfolio_id: int,
    days: int = Query(default=252, ge=30, le=1000),
    benchmark: str = Query(default="^NSEI"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Get per-holding risk metrics."""
    from dataclasses import asdict

    from app.ml.risk_calculator import compute_holding_risks

    results = await compute_holding_risks(
        user.id, portfolio_id, db, days, benchmark
    )
    return [asdict(r) for r in results]
