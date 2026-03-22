"""Backtesting & portfolio optimisation endpoints."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response schemas (local to this module)
# ---------------------------------------------------------------------------


class BacktestRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=50)
    exchange: str = Field(default="NSE", min_length=1, max_length=20)
    strategy_name: str = Field(min_length=1, max_length=50)
    params: dict | None = None
    days: int = Field(default=365, ge=30, le=3650)


class OptimizeRequest(BaseModel):
    risk_tolerance: str = Field(
        default="moderate",
        description="One of: conservative, moderate, aggressive",
    )


# ---------------------------------------------------------------------------
# Backtest routes
# ---------------------------------------------------------------------------


@router.post("/")
async def run_backtest_endpoint(
    body: BacktestRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run a backtest for a symbol using a specified strategy."""
    from app.ml.backtester import run_backtest

    try:
        result = await run_backtest(
            symbol=body.symbol,
            exchange=body.exchange,
            strategy_name=body.strategy_name,
            strategy_params=body.params,
            days=body.days,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    return asdict(result)


@router.get("/strategies")
async def list_strategies_endpoint(
    user: User = Depends(get_current_user),
) -> list[dict]:
    """List available backtesting strategies with descriptions and default params."""
    from app.ml.backtester import STRATEGY_REGISTRY

    return [
        {
            "name": name,
            "description": info["description"],
            "default_params": info["default_params"],
        }
        for name, info in STRATEGY_REGISTRY.items()
    ]


# ---------------------------------------------------------------------------
# Portfolio optimisation routes
# ---------------------------------------------------------------------------


@router.post("/optimize/{portfolio_id}")
async def optimize_portfolio_endpoint(
    portfolio_id: int,
    body: OptimizeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run mean-variance portfolio optimisation."""
    from app.ml.portfolio_optimizer import optimize_portfolio

    valid_tolerances = {"conservative", "moderate", "aggressive"}
    if body.risk_tolerance not in valid_tolerances:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"risk_tolerance must be one of: {', '.join(sorted(valid_tolerances))}",
        )

    try:
        optimization, suggestions = await optimize_portfolio(
            portfolio_id=portfolio_id,
            user_id=user.id,
            risk_tolerance=body.risk_tolerance,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    return {
        **asdict(optimization),
        "suggestions": [asdict(s) for s in suggestions],
    }


@router.get("/optimize/{portfolio_id}/suggestions")
async def get_rebalance_suggestions_endpoint(
    portfolio_id: int,
    risk_tolerance: str = "moderate",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Get rebalance suggestions for a portfolio based on optimisation."""
    from app.ml.portfolio_optimizer import optimize_portfolio

    valid_tolerances = {"conservative", "moderate", "aggressive"}
    if risk_tolerance not in valid_tolerances:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"risk_tolerance must be one of: {', '.join(sorted(valid_tolerances))}",
        )

    try:
        _, suggestions = await optimize_portfolio(
            portfolio_id=portfolio_id,
            user_id=user.id,
            risk_tolerance=risk_tolerance,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    return [asdict(s) for s in suggestions]
