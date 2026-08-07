"""Portfolio CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, verify_portfolio_ownership
from app.database import get_db
from app.models.portfolio import Portfolio
from app.models.user import User
from app.schemas.portfolio import (
    PortfolioCreate,
    PortfolioResponse,
    PortfolioSummaryResponse,
    PortfolioUpdate,
)
from app.services.benchmark_service import compare_with_benchmark
from app.services.portfolio_service import get_portfolio_summary
from app.services.portfolio_stats_service import (
    build_daily_value_series,
    build_xirr_cashflows,
)
from app.services.xirr_service import xirr

router = APIRouter()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[PortfolioResponse])
async def list_portfolios(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Portfolio]:
    """List all portfolios belonging to the current user."""
    result = await db.execute(
        select(Portfolio)
        .where(Portfolio.user_id == user.id)
        .order_by(Portfolio.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/", response_model=PortfolioResponse, status_code=status.HTTP_201_CREATED)
async def create_portfolio(
    body: PortfolioCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Portfolio:
    """Create a new portfolio for the current user."""
    # If this is set as default, unset any existing default
    if body.is_default:
        result = await db.execute(
            select(Portfolio).where(
                Portfolio.user_id == user.id,
                Portfolio.is_default.is_(True),
            )
        )
        for existing in result.scalars().all():
            existing.is_default = False

    portfolio = Portfolio(
        user_id=user.id,
        name=body.name,
        description=body.description,
        currency=body.currency,
        is_default=body.is_default,
    )
    db.add(portfolio)
    await db.flush()
    await db.refresh(portfolio)
    return portfolio


@router.get("/{portfolio_id}", response_model=PortfolioResponse)
async def get_portfolio(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Portfolio:
    """Get a single portfolio by ID."""
    return await verify_portfolio_ownership(portfolio_id, user, db)


@router.get("/{portfolio_id}/summary", response_model=PortfolioSummaryResponse)
async def get_portfolio_summary_endpoint(
    portfolio_id: int,
    display_currency: str | None = Query(
        None,
        description=(
            "Optional target currency (e.g. INR/EUR/USD). When set and different "
            "from the native currency, additive *_display convenience fields are "
            "included alongside the unchanged native fields."
        ),
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """THE MAIN OUTPUT TABLE.

    Returns a list of holdings with: stock, quantity, avg_price, current_price,
    action_needed, rsi, pnl_percent for all holdings in the portfolio.

    Passing ``?display_currency=`` layers additive ``*_display`` fields on top of
    the native response — existing fields are never altered.
    """
    # Verify ownership
    await verify_portfolio_ownership(portfolio_id, user, db)

    try:
        summary = await get_portfolio_summary(
            portfolio_id, db, display_currency=display_currency
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    # When conversion actually happened, the summary carries extra *_display
    # fields. Return it directly (bypassing response_model filtering) so those
    # additive fields survive; otherwise fall through to the validated model so
    # the default response is byte-for-byte identical to before.
    if "display_currency" in summary:
        return JSONResponse(content=jsonable_encoder(summary))

    return summary


@router.put("/{portfolio_id}", response_model=PortfolioResponse)
async def update_portfolio(
    portfolio_id: int,
    body: PortfolioUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Portfolio:
    """Update portfolio details."""
    portfolio = await verify_portfolio_ownership(portfolio_id, user, db)

    update_data = body.model_dump(exclude_unset=True)

    # Handle default flag: unset others if setting this one as default
    if update_data.get("is_default") is True:
        result = await db.execute(
            select(Portfolio).where(
                Portfolio.user_id == user.id,
                Portfolio.is_default.is_(True),
                Portfolio.id != portfolio_id,
            )
        )
        for existing in result.scalars().all():
            existing.is_default = False

    for key, value in update_data.items():
        setattr(portfolio, key, value)

    await db.flush()
    await db.refresh(portfolio)
    return portfolio


@router.delete("/{portfolio_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_portfolio(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a portfolio and all its holdings / transactions (cascade)."""
    portfolio = await verify_portfolio_ownership(portfolio_id, user, db)
    await db.delete(portfolio)
    await db.flush()


# ---------------------------------------------------------------------------
# XIRR (Extended Internal Rate of Return)
# ---------------------------------------------------------------------------

@router.get("/{portfolio_id}/xirr")
async def get_portfolio_xirr(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Calculate XIRR for a portfolio based on all buy/sell transactions + current value."""
    # Verify ownership
    await verify_portfolio_ownership(portfolio_id, user, db)

    # Build cash flows (BUY -> negative, SELL -> positive, current value as
    # the terminal positive flow) in the stats service.
    try:
        flows = await build_xirr_cashflows(portfolio_id, db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    cash_flows = flows.cash_flows
    if len(cash_flows) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Not enough transactions to calculate XIRR",
        )

    result_xirr = xirr(cash_flows)

    return {
        "portfolio_id": portfolio_id,
        "xirr": round(result_xirr * 100, 2) if result_xirr is not None else None,
        "xirr_decimal": result_xirr,
        "total_current_value": round(flows.total_current_value, 2),
        "num_cash_flows": len(cash_flows),
        "used_stale_prices": flows.used_stale_prices,
        "status": "calculated" if result_xirr is not None else "failed_to_converge",
    }


# ---------------------------------------------------------------------------
# Benchmark Comparison
# ---------------------------------------------------------------------------

@router.get("/{portfolio_id}/benchmark")
async def compare_benchmark(
    portfolio_id: int,
    benchmark: str = Query("NIFTY50", description="Benchmark index name"),
    days: int = Query(90, ge=7, le=365, description="Comparison period in days"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Compare portfolio performance against a benchmark index."""
    # Verify ownership
    await verify_portfolio_ownership(portfolio_id, user, db)

    # Build a genuine dated market-value series over the SAME window as the
    # benchmark from stored PriceHistory (see the stats service): comparing
    # this real series against the benchmark's windowed return yields an
    # honest alpha, unlike a two-point [invested, current] series which would
    # compare all-time unrealized P&L against an N-day benchmark return.
    try:
        portfolio_daily_values = await build_daily_value_series(
            portfolio_id, days, db
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    comparison = await compare_with_benchmark(
        portfolio_daily_values=portfolio_daily_values,
        benchmark_name=benchmark,
        days=days,
    )

    if comparison is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Could not fetch benchmark data for '{benchmark}'",
        )

    return {
        "portfolio_id": portfolio_id,
        "benchmark_name": comparison.benchmark_name,
        "benchmark_symbol": comparison.benchmark_symbol,
        "portfolio_return_pct": comparison.portfolio_return_pct,
        "benchmark_return_pct": comparison.benchmark_return_pct,
        "alpha": comparison.alpha,
        "insufficient_history": comparison.insufficient_history,
        "period_days": comparison.period_days,
        "data_points": comparison.data_points,
    }
