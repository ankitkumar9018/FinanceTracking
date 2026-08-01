"""Portfolio CRUD endpoints."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.database import get_db
from app.models.holding import Holding
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
from app.services.xirr_service import CashFlow, xirr

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
    await _get_user_portfolio(portfolio_id, user, db)

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
    used_stale_prices = False

    for h in holdings:
        for tx in h.transactions:
            amount = float(tx.quantity) * float(tx.price)
            if tx.transaction_type == "BUY":
                cash_flows.append(CashFlow(date=tx.date, amount=-amount))
            elif tx.transaction_type == "SELL":
                cash_flows.append(CashFlow(date=tx.date, amount=amount))

        # Add current portfolio value as final positive cash flow (today's
        # date). Fall back to average price for never-refreshed holdings —
        # otherwise they'd contribute no terminal value at all and drag the
        # computed return toward a total loss.
        terminal_price = h.current_price if h.current_price is not None else h.average_price
        if h.current_price is None:
            used_stale_prices = True
        if terminal_price is not None and h.cumulative_quantity:
            total_current_value += float(terminal_price) * float(h.cumulative_quantity)

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
        "used_stale_prices": used_stale_prices,
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
    await _get_user_portfolio(portfolio_id, user, db)

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

    # Build a genuine dated market-value series over the SAME window as the
    # benchmark from stored PriceHistory: value_on_day = sum over holdings of
    # (current quantity * that day's close). Comparing this real series against
    # the benchmark's windowed return yields an honest alpha, unlike the old
    # two-point [invested, current] series which compared all-time unrealized
    # P&L against an N-day benchmark return (a fabricated alpha).
    from datetime import timedelta

    from app.models.price_history import PriceHistory

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    # Aggregate quantity per (symbol, exchange) so multiple lots collapse.
    qty_by_symbol: dict[tuple[str, str], float] = {}
    for h in holdings:
        key = (h.stock_symbol, h.exchange)
        qty_by_symbol[key] = qty_by_symbol.get(key, 0.0) + float(h.cumulative_quantity)

    ph_result = await db.execute(
        select(PriceHistory).where(
            PriceHistory.date >= start_date,
            PriceHistory.date <= end_date,
        )
    )
    price_rows = ph_result.scalars().all()

    daily_totals: dict[date, float] = {}
    for row in price_rows:
        qty = qty_by_symbol.get((row.stock_symbol, row.exchange))
        if qty is None:
            continue
        daily_totals[row.date] = daily_totals.get(row.date, 0.0) + qty * float(row.close)

    portfolio_daily_values = [
        {"date": d.isoformat(), "value": v}
        for d, v in sorted(daily_totals.items())
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
        "insufficient_history": comparison.insufficient_history,
        "period_days": comparison.period_days,
        "data_points": comparison.data_points,
    }
