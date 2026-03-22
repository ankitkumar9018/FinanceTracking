"""Analytics endpoints — portfolio drift, sector rotation, calendar, and more.

All endpoints require authentication and verify portfolio ownership before
returning data.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.user import User
from app.services.drift_service import check_drift, set_target_allocation
from app.services.freshness_service import get_data_freshness
from app.services.market_data_service import _EXCHANGE_SUFFIX, fetch_historical_data
from app.services.recurring_detection_service import detect_recurring
from app.services.sector_rotation_service import get_sector_rotation
from app.services.sheets_export_service import generate_portfolio_csv
from app.services.sip_calendar_service import get_calendar_events
from app.services.week52_service import get_52week_proximity

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _verify_portfolio_ownership(
    portfolio_id: int,
    user: User,
    db: AsyncSession,
) -> Portfolio:
    """Ensure the portfolio exists and belongs to the authenticated user."""
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
# Request / response schemas
# ---------------------------------------------------------------------------

class SetTargetAllocationRequest(BaseModel):
    """Body for setting a target allocation percentage on a holding."""

    target_allocation_pct: float = Field(
        ...,
        ge=0,
        le=100,
        description="Target allocation percentage (0-100)",
    )


# ---------------------------------------------------------------------------
# 1. Portfolio Drift
# ---------------------------------------------------------------------------

@router.get("/drift/{portfolio_id}")
async def get_drift(
    portfolio_id: int,
    threshold: float = Query(
        default=5.0,
        ge=0,
        description="Drift threshold in percentage points",
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Check allocation drift for a portfolio.

    Returns each holding's actual vs target allocation, and flags any
    holdings whose drift exceeds the given threshold (default 5 %).
    """
    await _verify_portfolio_ownership(portfolio_id, user, db)
    drift_data = await check_drift(portfolio_id, db, threshold=threshold)
    return {
        "portfolio_id": portfolio_id,
        "threshold": threshold,
        "holdings": drift_data,
    }


@router.put("/drift/{holding_id}")
async def set_drift_target(
    holding_id: int,
    body: SetTargetAllocationRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Set the target allocation percentage for a holding.

    The value is stored in the holding's ``custom_fields`` JSON under
    the key ``target_allocation_pct``.
    """
    try:
        holding = await set_target_allocation(
            holding_id=holding_id,
            target_pct=body.target_allocation_pct,
            user_id=user.id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    return {
        "holding_id": holding.id,
        "stock_symbol": holding.stock_symbol,
        "target_allocation_pct": holding.custom_fields.get("target_allocation_pct"),
    }


# ---------------------------------------------------------------------------
# 2. Sector Rotation
# ---------------------------------------------------------------------------

@router.get("/sector-rotation/{portfolio_id}")
async def sector_rotation(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get sector-wise allocation weights and their change vs last month."""
    await _verify_portfolio_ownership(portfolio_id, user, db)
    return await get_sector_rotation(portfolio_id, db)


# ---------------------------------------------------------------------------
# 3. SIP Calendar
# ---------------------------------------------------------------------------

@router.get("/calendar/{portfolio_id}")
async def calendar_events(
    portfolio_id: int,
    month: int = Query(
        default=None,
        ge=1,
        le=12,
        description="Month (1-12). Defaults to current month.",
    ),
    year: int = Query(
        default=None,
        ge=2000,
        le=2100,
        description="Year. Defaults to current year.",
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a calendar of financial events for the given month.

    Aggregates SIP dates, dividend payment dates, and upcoming earnings.
    """
    await _verify_portfolio_ownership(portfolio_id, user, db)

    today = date.today()
    if month is None:
        month = today.month
    if year is None:
        year = today.year

    events = await get_calendar_events(
        user_id=user.id,
        portfolio_id=portfolio_id,
        month=month,
        year=year,
        db=db,
    )
    return {
        "portfolio_id": portfolio_id,
        "month": month,
        "year": year,
        "event_count": len(events),
        "events": events,
    }


# ---------------------------------------------------------------------------
# 4. Recurring Transaction Detection
# ---------------------------------------------------------------------------

@router.get("/recurring/{portfolio_id}")
async def recurring_transactions(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Detect SIP-like recurring transaction patterns in a portfolio.

    Identifies holdings with regular BUY transactions of similar amounts
    at roughly monthly intervals.
    """
    await _verify_portfolio_ownership(portfolio_id, user, db)
    patterns = await detect_recurring(portfolio_id, db)
    return {
        "portfolio_id": portfolio_id,
        "detected_count": len(patterns),
        "patterns": patterns,
    }


# ---------------------------------------------------------------------------
# 5. 52-Week Proximity
# ---------------------------------------------------------------------------

@router.get("/52week/{portfolio_id}")
async def week52_proximity(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get 52-week high/low proximity for each holding in the portfolio.

    Shows how close each stock's current price is to its 52-week high
    and low, and flags stocks that are near either extreme.
    """
    await _verify_portfolio_ownership(portfolio_id, user, db)
    proximity = await get_52week_proximity(portfolio_id, db)
    return {
        "portfolio_id": portfolio_id,
        "holdings": proximity,
    }


# ---------------------------------------------------------------------------
# 6. Data Freshness
# ---------------------------------------------------------------------------

@router.get("/freshness/{portfolio_id}")
async def data_freshness(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get data freshness / staleness for each holding in the portfolio.

    A holding is stale if its price data is older than 30 minutes during
    market hours, or older than 1 day outside market hours.
    """
    await _verify_portfolio_ownership(portfolio_id, user, db)
    freshness = await get_data_freshness(portfolio_id, db)

    stale_count = sum(1 for f in freshness if f["is_stale"])
    return {
        "portfolio_id": portfolio_id,
        "total_holdings": len(freshness),
        "stale_count": stale_count,
        "holdings": freshness,
    }


# ---------------------------------------------------------------------------
# 7. Google Sheets Export (CSV)
# ---------------------------------------------------------------------------

@router.get("/export/sheets/{portfolio_id}")
async def export_sheets_csv(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Download the portfolio as a CSV file formatted for Google Sheets import.

    The CSV includes a holdings summary, full transaction history, and
    dividend history with proper headers and date formatting.
    """
    portfolio = await _verify_portfolio_ownership(portfolio_id, user, db)

    try:
        csv_content = await generate_portfolio_csv(portfolio_id, db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    # Sanitise portfolio name for the filename
    safe_name = "".join(
        c if c.isalnum() or c in (" ", "-", "_") else "_"
        for c in portfolio.name
    ).strip()

    filename = f"{safe_name}_portfolio_export.csv"

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


# ---------------------------------------------------------------------------
# 9. Correlation Matrix (real data from price history)
# ---------------------------------------------------------------------------

@router.get("/correlation/{portfolio_id}")
async def get_correlation_matrix(
    portfolio_id: int,
    days: int = Query(default=90, ge=30, le=365, description="Lookback period in days"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Compute pairwise correlation matrix for portfolio holdings.

    Uses daily close returns over the specified period. Requires numpy.
    Returns an empty matrix if insufficient data.
    """
    await _verify_portfolio_ownership(portfolio_id, user, db)

    result = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio_id)
    )
    holdings = list(result.scalars().all())
    symbols = [h.stock_symbol for h in holdings]
    exchanges = [h.exchange for h in holdings]

    if len(symbols) < 2:
        return {"symbols": symbols, "matrix": [[1.0]] if symbols else []}

    try:
        import numpy as np

        # Fetch price history for each holding
        returns_map: dict[str, list[float]] = {}
        for sym, exch in zip(symbols, exchanges):
            history = await fetch_historical_data(sym, exch, days=days)
            if len(history) >= 2:
                closes = [d["close"] for d in history]
                daily_returns = [
                    (closes[i] - closes[i - 1]) / closes[i - 1]
                    for i in range(1, len(closes))
                    if closes[i - 1] != 0
                ]
                returns_map[sym] = daily_returns

        # Only include symbols with sufficient data
        valid_symbols = [s for s in symbols if s in returns_map and len(returns_map[s]) >= 10]
        if len(valid_symbols) < 2:
            return {"symbols": valid_symbols, "matrix": [[1.0]] * len(valid_symbols)}

        # Align to same length (minimum common length)
        min_len = min(len(returns_map[s]) for s in valid_symbols)
        matrix_data = np.array([returns_map[s][:min_len] for s in valid_symbols])

        corr = np.corrcoef(matrix_data)
        # Replace NaN with 0
        corr = np.nan_to_num(corr, nan=0.0)

        return {
            "symbols": valid_symbols,
            "matrix": [[round(float(v), 3) for v in row] for row in corr],
        }

    except ImportError:
        logger.warning("numpy not available for correlation computation")
        return {"symbols": symbols, "matrix": [], "error": "numpy not installed"}
    except Exception:
        logger.debug("Correlation computation failed", exc_info=True)
        return {"symbols": symbols, "matrix": []}


# ---------------------------------------------------------------------------
# 10. Monthly Returns (real data from portfolio value history)
# ---------------------------------------------------------------------------

@router.get("/monthly-returns/{portfolio_id}")
async def get_monthly_returns(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Compute monthly portfolio return percentages for the last 12 months.

    Uses the portfolio's first holding as a proxy for portfolio performance
    when full daily portfolio valuation isn't available. Falls back to
    aggregate price change of all holdings.
    """
    await _verify_portfolio_ownership(portfolio_id, user, db)

    result = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio_id)
    )
    holdings = list(result.scalars().all())

    if not holdings:
        return {"returns": []}

    try:
        import numpy as np
        from datetime import datetime

        # Fetch 13 months of history (to compute 12 monthly returns)
        all_histories: dict[str, list[dict]] = {}
        weights: dict[str, float] = {}
        total_value = 0.0

        for h in holdings:
            hist = await fetch_historical_data(h.stock_symbol, h.exchange, days=400)
            if hist:
                all_histories[h.stock_symbol] = hist
                val = float(h.cumulative_quantity) * float(h.average_price)
                weights[h.stock_symbol] = val
                total_value += val

        if not all_histories or total_value == 0:
            return {"returns": []}

        # Normalize weights
        for sym in weights:
            weights[sym] /= total_value

        # Group prices by month and compute weighted monthly returns
        months_data: dict[str, float] = {}
        today = datetime.now().date()

        for sym, hist in all_histories.items():
            w = weights.get(sym, 0)
            prev_close = None
            for d in hist:
                dt = datetime.strptime(d["date"], "%Y-%m-%d").date() if isinstance(d["date"], str) else d["date"]
                month_key = dt.strftime("%Y-%m")
                close = d["close"]
                if prev_close and prev_close != 0:
                    daily_ret = (close - prev_close) / prev_close
                    months_data[month_key] = months_data.get(month_key, 0) + daily_ret * w
                prev_close = close

        # Convert to sorted list of last 12 months
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        returns = []
        for i in range(11, -1, -1):
            d = today.replace(day=1) - timedelta(days=i * 30)
            month_key = d.strftime("%Y-%m")
            month_label = month_names[d.month - 1]
            ret_pct = months_data.get(month_key, 0) * 100
            returns.append({"month": month_label, "return_pct": round(ret_pct, 2)})

        return {"returns": returns}

    except ImportError:
        return {"returns": [], "error": "numpy not installed"}
    except Exception:
        logger.debug("Monthly returns computation failed", exc_info=True)
        return {"returns": []}


# ---------------------------------------------------------------------------
# 11. Drawdown (real data from portfolio value history)
# ---------------------------------------------------------------------------

@router.get("/drawdown/{portfolio_id}")
async def get_drawdown(
    portfolio_id: int,
    days: int = Query(default=365, ge=30, le=730, description="Lookback period in days"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Compute daily drawdown from peak for the portfolio.

    Returns date+drawdown_pct pairs for charting.
    """
    await _verify_portfolio_ownership(portfolio_id, user, db)

    result = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio_id)
    )
    holdings = list(result.scalars().all())

    if not holdings:
        return {"drawdown": []}

    try:
        # Fetch history for all holdings and compute weighted portfolio value
        all_histories: dict[str, list[dict]] = {}
        quantities: dict[str, float] = {}

        for h in holdings:
            hist = await fetch_historical_data(h.stock_symbol, h.exchange, days=days)
            if hist:
                all_histories[h.stock_symbol] = hist
                quantities[h.stock_symbol] = float(h.cumulative_quantity)

        if not all_histories:
            return {"drawdown": []}

        # Build daily portfolio value (sum of qty * close for each holding)
        date_values: dict[str, float] = {}
        for sym, hist in all_histories.items():
            qty = quantities.get(sym, 0)
            for d in hist:
                dt = d["date"] if isinstance(d["date"], str) else d["date"].isoformat()
                date_values[dt] = date_values.get(dt, 0) + qty * d["close"]

        if not date_values:
            return {"drawdown": []}

        # Sort by date and compute drawdown from peak
        sorted_dates = sorted(date_values.keys())
        peak = 0.0
        drawdown_series = []

        for dt in sorted_dates:
            val = date_values[dt]
            peak = max(peak, val)
            dd_pct = ((val - peak) / peak * 100) if peak > 0 else 0.0
            drawdown_series.append({
                "date": dt,
                "drawdown": round(min(0.0, dd_pct), 2),
            })

        return {"drawdown": drawdown_series}

    except Exception:
        logger.debug("Drawdown computation failed", exc_info=True)
        return {"drawdown": []}
