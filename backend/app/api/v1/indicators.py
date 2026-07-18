"""Technical indicators & risk metrics endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
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


@router.get("/hedge/{portfolio_id}")
async def get_hedge_estimate(
    portfolio_id: int,
    protection_pct: float = Query(default=80.0, ge=0, le=100),
    months: float = Query(default=3.0, gt=0, le=24),
    implied_vol_pct: float = Query(default=20.0, ge=0, le=200),
    index_price: float = Query(default=0.0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Rough informational estimate of the cost of hedging portfolio downside
    with index puts.

    NOT an options quote or trade advice — the premium is a crude heuristic,
    not a real option price (see ``hedge_service`` for details).
    """
    from app.models.holding import Holding
    from app.models.portfolio import Portfolio
    from app.services.hedge_service import DEFAULT_INDEX_PRICE, compute_hedge_estimate

    # Verify ownership (scoped to the authenticated user).
    port_result = await db.execute(
        select(Portfolio).where(
            Portfolio.id == portfolio_id,
            Portfolio.user_id == user.id,
        )
    )
    portfolio = port_result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found"
        )

    # Portfolio value = sum of holdings (qty * current_price, fall back to avg).
    h_result = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio_id)
    )
    holdings = h_result.scalars().all()
    portfolio_value = sum(
        float(h.cumulative_quantity) * float(h.current_price or h.average_price)
        for h in holdings
    )

    # Reuse the risk calculator's portfolio beta if readily available;
    # otherwise default to 1.0 (a market-neutral assumption).
    beta = 1.0
    try:
        from app.ml.risk_calculator import compute_portfolio_risk

        metrics = await compute_portfolio_risk(user.id, portfolio_id, db)
        if metrics.beta is not None:
            beta = metrics.beta
    except Exception:  # noqa: BLE001 - beta is best-effort; never block the estimate
        beta = 1.0

    resolved_index_price = index_price if index_price > 0 else DEFAULT_INDEX_PRICE

    return compute_hedge_estimate(
        portfolio_value=portfolio_value,
        beta=beta,
        index_price=resolved_index_price,
        protection_pct=protection_pct,
        months=months,
        implied_vol_pct=implied_vol_pct,
    )
