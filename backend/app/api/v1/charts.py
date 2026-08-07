"""Chart data endpoints: OHLCV for TradingView, RSI series, allocation, performance."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, verify_portfolio_ownership
from app.database import get_db
from app.models.holding import Holding
from app.models.price_history import PriceHistory
from app.models.user import User
from app.schemas.market_data import HistoryResponse, RSIResponse
from app.services.market_data_service import fetch_historical_data, fetch_rsi_series

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/price/{symbol}", response_model=HistoryResponse)
async def chart_price(
    symbol: str,
    exchange: str = Query(default="NSE"),
    days: int = Query(default=30, ge=1, le=730),
    user: User = Depends(get_current_user),
) -> dict:
    """OHLCV data formatted for TradingView-style candlestick charts."""
    try:
        data = await fetch_historical_data(
            symbol.upper().strip(),
            exchange.upper().strip(),
            days,
        )
    except Exception:
        logger.exception(
            "Failed to fetch chart data for %s on %s", symbol, exchange
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to load chart data",
        ) from None

    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No chart data found for {symbol} on {exchange}",
        )

    return {
        "symbol": symbol.upper().strip(),
        "exchange": exchange.upper().strip(),
        "data": data,
    }


@router.get("/rsi/{symbol}", response_model=RSIResponse)
async def chart_rsi(
    symbol: str,
    exchange: str = Query(default="NSE"),
    days: int = Query(default=30, ge=1, le=365),
    period: int = Query(default=14, ge=2, le=50, description="RSI period"),
    user: User = Depends(get_current_user),
) -> dict:
    """RSI time series data for overlay or separate RSI chart."""
    try:
        data = await fetch_rsi_series(
            symbol.upper().strip(),
            exchange.upper().strip(),
            days,
            period,
        )
    except Exception:
        logger.exception("Failed to compute RSI for %s on %s", symbol, exchange)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to load RSI data",
        ) from None

    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No RSI data available for {symbol} on {exchange}",
        )

    return {
        "symbol": symbol.upper().strip(),
        "exchange": exchange.upper().strip(),
        "period": period,
        "data": data,
    }


@router.get("/portfolio/allocation/{portfolio_id}")
async def portfolio_allocation(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Sector and stock allocation data for pie / donut charts.

    Returns:
    - by_stock: list of {symbol, name, value, percentage}
    - by_sector: list of {sector, value, percentage}
    """
    await verify_portfolio_ownership(portfolio_id, user, db)

    h_result = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio_id)
    )
    holdings = h_result.scalars().all()

    by_stock: list[dict] = []
    sector_totals: dict[str, float] = {}
    total_value = 0.0

    for h in holdings:
        qty = float(h.cumulative_quantity)
        price = float(h.current_price) if h.current_price is not None else float(h.average_price)
        value = qty * price
        total_value += value

        by_stock.append(
            {
                "symbol": h.stock_symbol,
                "name": h.stock_name,
                "value": round(value, 2),
            }
        )

        sector = h.sector or "Unknown"
        sector_totals[sector] = sector_totals.get(sector, 0.0) + value

    # Calculate percentages
    for item in by_stock:
        item["percentage"] = (
            round((item["value"] / total_value) * 100, 2) if total_value > 0 else 0.0
        )

    by_sector = [
        {
            "sector": sector,
            "value": round(value, 2),
            "percentage": round((value / total_value) * 100, 2) if total_value > 0 else 0.0,
        }
        for sector, value in sorted(sector_totals.items(), key=lambda x: -x[1])
    ]

    return {
        "portfolio_id": portfolio_id,
        "total_value": round(total_value, 2),
        "by_stock": sorted(by_stock, key=lambda x: -x["value"]),
        "by_sector": by_sector,
    }


@router.get("/portfolio/performance/{portfolio_id}")
async def portfolio_performance(
    portfolio_id: int,
    days: int = Query(default=30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Portfolio value over time, computed from price_history for each holding.

    Returns a time series of {date, total_value} for the requested period.
    """
    portfolio = await verify_portfolio_ownership(portfolio_id, user, db)

    h_result = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio_id)
    )
    holdings = h_result.scalars().all()
    if not holdings:
        return {
            "portfolio_id": portfolio_id,
            "currency": portfolio.currency,
            "data": [],
        }

    # Gather price history for the holdings' symbols, bounded to the requested
    # window so the query never scans a symbol's entire stored history.
    symbols_exchanges = [(h.stock_symbol, h.exchange) for h in holdings]
    from sqlalchemy import and_, or_

    conditions = [
        and_(
            PriceHistory.stock_symbol == sym,
            PriceHistory.exchange == exch,
        )
        for sym, exch in symbols_exchanges
    ]

    window_start = date.today() - timedelta(days=days)
    ph_result = await db.execute(
        select(PriceHistory)
        .where(PriceHistory.date >= window_start, or_(*conditions))
        .order_by(PriceHistory.date)
    )
    price_rows = ph_result.scalars().all()

    # Build a lookup: (symbol, exchange, date) -> close price
    price_lookup: dict[tuple[str, str, str], float] = {}
    all_dates: set[str] = set()
    for ph in price_rows:
        key = (ph.stock_symbol, ph.exchange, ph.date.isoformat())
        price_lookup[key] = float(ph.close)
        all_dates.add(ph.date.isoformat())

    # Sort dates and compute portfolio value for each date
    sorted_dates = sorted(all_dates)
    # Trim to requested number of days
    sorted_dates = sorted_dates[-days:]

    # Build quantity map (current cumulative quantities)
    qty_map = {
        (h.stock_symbol, h.exchange): float(h.cumulative_quantity) for h in holdings
    }

    performance: list[dict] = []
    last_known_price: dict[tuple[str, str], float] = {}

    for date_str in sorted_dates:
        total = 0.0
        for sym, exch in symbols_exchanges:
            key = (sym, exch, date_str)
            price = price_lookup.get(key)
            if price is not None:
                last_known_price[(sym, exch)] = price
            else:
                price = last_known_price.get((sym, exch))

            if price is not None:
                qty = qty_map.get((sym, exch), 0.0)
                total += qty * price

        performance.append(
            {
                "date": date_str,
                "total_value": round(total, 2),
            }
        )

    return {
        "portfolio_id": portfolio_id,
        "currency": portfolio.currency,
        "data": performance,
    }
