"""Portfolio CRUD endpoints."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.database import get_db
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.portfolio import (
    PortfolioCreate,
    PortfolioResponse,
    PortfolioSummaryResponse,
    PortfolioUpdate,
)
from app.services.portfolio_service import get_portfolio_summary
from app.services.xirr_service import CashFlow, xirr
from app.services.benchmark_service import compare_with_benchmark

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_user_portfolio(
    portfolio_id: int,
    user: User,
    db: AsyncSession,
) -> Portfolio:
    """Fetch a portfolio ensuring it belongs to the current user."""
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
    return await _get_user_portfolio(portfolio_id, user, db)


@router.get("/{portfolio_id}/summary", response_model=PortfolioSummaryResponse)
async def get_portfolio_summary_endpoint(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """THE MAIN OUTPUT TABLE.

    Returns a list of holdings with: stock, quantity, avg_price, current_price,
    action_needed, rsi, pnl_percent for all holdings in the portfolio.
    """
    # Verify ownership
    await _get_user_portfolio(portfolio_id, user, db)

    try:
        summary = await get_portfolio_summary(portfolio_id, db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    return summary


@router.put("/{portfolio_id}", response_model=PortfolioResponse)
async def update_portfolio(
    portfolio_id: int,
    body: PortfolioUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Portfolio:
    """Update portfolio details."""
    portfolio = await _get_user_portfolio(portfolio_id, user, db)

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
    portfolio = await _get_user_portfolio(portfolio_id, user, db)
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
    await _get_user_portfolio(portfolio_id, user, db)

    # Get all holdings for this portfolio with their transactions
    result = await db.execute(
        select(Holding)
        .options(selectinload(Holding.transactions))
        .where(Holding.portfolio_id == portfolio_id)
    )
    holdings = result.scalars().all()

    if not holdings:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No holdings found in this portfolio",
        )

    # Build cash flows: BUY -> negative, SELL -> positive
    cash_flows: list[CashFlow] = []
    total_current_value = 0.0

    for h in holdings:
        for tx in h.transactions:
            amount = float(tx.quantity) * float(tx.price)
            if tx.transaction_type == "BUY":
                cash_flows.append(CashFlow(date=tx.date, amount=-amount))
            elif tx.transaction_type == "SELL":
                cash_flows.append(CashFlow(date=tx.date, amount=amount))

        # Add current portfolio value as final positive cash flow (today's date)
        if h.current_price is not None and h.cumulative_quantity:
            total_current_value += float(h.current_price) * float(h.cumulative_quantity)

    if total_current_value > 0:
        cash_flows.append(CashFlow(date=date.today(), amount=total_current_value))

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
        "total_current_value": round(total_current_value, 2),
        "num_cash_flows": len(cash_flows),
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
    portfolio = await _get_user_portfolio(portfolio_id, user, db)

    # Get all holdings for this portfolio
    result = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio_id)
    )
    holdings = result.scalars().all()

    if not holdings:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No holdings found in this portfolio",
        )

    # Build portfolio daily values (simplified: use current snapshot as single point)
    # In a full implementation, you'd pull from PriceHistory table
    total_invested = 0.0
    total_current = 0.0
    for h in holdings:
        qty = float(h.cumulative_quantity)
        avg = float(h.average_price)
        total_invested += qty * avg
        if h.current_price is not None:
            total_current += qty * float(h.current_price)

    # Build a minimal daily values list with start and end
    from datetime import timedelta

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    portfolio_daily_values = [
        {"date": start_date.isoformat(), "value": total_invested},
        {"date": end_date.isoformat(), "value": total_current},
    ]

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
        "period_days": comparison.period_days,
        "data_points": comparison.data_points,
    }
