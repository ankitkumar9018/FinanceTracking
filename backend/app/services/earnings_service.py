"""Earnings Calendar Service — fetch upcoming earnings dates from yfinance."""

from __future__ import annotations

import asyncio
import logging
from datetime import date

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.services.market_data_service import _ticker_symbol

logger = logging.getLogger(__name__)


def _sync_fetch_calendar(ticker_str: str):
    """Fetch yfinance calendar synchronously (runs in a thread)."""
    ticker = yf.Ticker(ticker_str)
    return ticker.calendar


# ---------------------------------------------------------------------------
# Single stock earnings
# ---------------------------------------------------------------------------

async def get_stock_earnings(symbol: str, exchange: str = "NSE") -> dict:
    """Fetch earnings calendar data for a single stock.

    Uses yfinance's ``calendar`` property which returns upcoming earnings
    dates, revenue estimates, and earnings estimates.

    Returns a dict matching StockEarnings schema.
    """
    ticker_str = _ticker_symbol(symbol, exchange)
    result: dict = {
        "symbol": symbol,
        "earnings_date": None,
        "earnings_dates": [],
        "revenue_estimate": None,
        "earnings_estimate": None,
        "data_available": False,
    }

    try:
        calendar = await asyncio.wait_for(
            asyncio.to_thread(_sync_fetch_calendar, ticker_str),
            timeout=10.0,
        )

        if calendar is not None:
            # calendar can be a dict or DataFrame depending on yfinance version
            if isinstance(calendar, dict):
                # Dict format: {'Earnings Date': [...], 'Revenue Estimate': ..., etc.}
                earnings_dates_raw = calendar.get("Earnings Date", [])
                if isinstance(earnings_dates_raw, list):
                    for ed in earnings_dates_raw:
                        parsed = _parse_date(ed)
                        if parsed:
                            result["earnings_dates"].append(parsed)
                else:
                    parsed = _parse_date(earnings_dates_raw)
                    if parsed:
                        result["earnings_dates"].append(parsed)

                result["revenue_estimate"] = _safe_float_value(
                    calendar.get("Revenue Estimate") or calendar.get("Revenue Average")
                )
                result["earnings_estimate"] = _safe_float_value(
                    calendar.get("Earnings Estimate") or calendar.get("Earnings Average")
                )

            else:
                # DataFrame format
                try:
                    if hasattr(calendar, "columns"):
                        for col in calendar.columns:
                            col_data = calendar[col]
                            if "Earnings Date" in col_data.index:
                                parsed = _parse_date(col_data["Earnings Date"])
                                if parsed:
                                    result["earnings_dates"].append(parsed)
                            if "Revenue Average" in col_data.index:
                                result["revenue_estimate"] = _safe_float_value(
                                    col_data["Revenue Average"]
                                )
                            if "Earnings Average" in col_data.index:
                                result["earnings_estimate"] = _safe_float_value(
                                    col_data["Earnings Average"]
                                )
                    elif hasattr(calendar, "index"):
                        if "Earnings Date" in calendar.index:
                            raw_dates = calendar.loc["Earnings Date"]
                            if hasattr(raw_dates, "__iter__") and not isinstance(raw_dates, str):
                                for ed in raw_dates:
                                    parsed = _parse_date(ed)
                                    if parsed:
                                        result["earnings_dates"].append(parsed)
                            else:
                                parsed = _parse_date(raw_dates)
                                if parsed:
                                    result["earnings_dates"].append(parsed)

                        if "Revenue Average" in calendar.index:
                            result["revenue_estimate"] = _safe_float_value(
                                calendar.loc["Revenue Average"].iloc[0]
                                if hasattr(calendar.loc["Revenue Average"], "iloc")
                                else calendar.loc["Revenue Average"]
                            )
                        if "Earnings Average" in calendar.index:
                            result["earnings_estimate"] = _safe_float_value(
                                calendar.loc["Earnings Average"].iloc[0]
                                if hasattr(calendar.loc["Earnings Average"], "iloc")
                                else calendar.loc["Earnings Average"]
                            )
                except Exception:
                    logger.debug("Could not parse calendar DataFrame for %s", symbol)

            if result["earnings_dates"]:
                # Set the nearest upcoming earnings date
                today = date.today()
                upcoming = [d for d in result["earnings_dates"] if d >= today]
                result["earnings_date"] = min(upcoming) if upcoming else result["earnings_dates"][0]
                result["data_available"] = True
            elif result["revenue_estimate"] or result["earnings_estimate"]:
                result["data_available"] = True

    except Exception:
        logger.warning("Earnings data fetch failed for %s", symbol)

    return result


def _parse_date(value) -> date | None:
    """Safely parse a date value from various formats."""
    if value is None:
        return None
    try:
        if isinstance(value, date):
            return value
        if hasattr(value, "date"):
            return value.date()
        if isinstance(value, str):
            from datetime import datetime
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except (ValueError, TypeError, AttributeError):
        pass
    return None


def _safe_float_value(value) -> float | None:
    """Safely convert a value to float."""
    if value is None:
        return None
    try:
        f = float(value)
        if f != f:  # NaN check
            return None
        return round(f, 2)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Bulk earnings for multiple symbols
# ---------------------------------------------------------------------------

async def get_earnings_calendar(
    symbols: list[str], exchange: str = "NSE"
) -> list[dict]:
    """Fetch earnings data for multiple symbols.

    Returns a list of dicts, one per symbol.
    """
    results: list[dict] = []
    for symbol in symbols:
        data = await get_stock_earnings(symbol, exchange)
        results.append(data)
    return results


# ---------------------------------------------------------------------------
# Portfolio earnings
# ---------------------------------------------------------------------------

async def get_portfolio_earnings(portfolio_id: int, db: AsyncSession) -> dict:
    """Get upcoming earnings dates for all holdings in a portfolio.

    Returns a dict matching PortfolioEarningsResponse schema.
    """
    result = await db.execute(
        select(Portfolio)
        .options(selectinload(Portfolio.holdings))
        .where(Portfolio.id == portfolio_id)
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise ValueError(f"Portfolio {portfolio_id} not found")

    all_earnings: list[dict] = []
    holdings_with_data = 0

    for h in portfolio.holdings:
        earnings = await get_stock_earnings(h.stock_symbol, h.exchange)
        all_earnings.append(earnings)
        if earnings["data_available"]:
            holdings_with_data += 1

    # Sort by nearest earnings date (those with dates first)
    all_earnings.sort(
        key=lambda e: (
            e["earnings_date"] is None,
            e["earnings_date"] or date.max,
        )
    )

    return {
        "portfolio_id": portfolio.id,
        "portfolio_name": portfolio.name,
        "upcoming_earnings": all_earnings,
        "total_holdings": len(portfolio.holdings),
        "holdings_with_data": holdings_with_data,
    }
