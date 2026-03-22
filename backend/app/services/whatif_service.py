"""What-If Simulator Service — simulate historical investment returns."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

import yfinance as yf

from app.services.benchmark_service import BENCHMARKS
from app.services.market_data_service import _ticker_symbol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

async def simulate(
    symbol: str,
    exchange: str,
    invest_amount: float,
    start_date: date,
    end_date: date | None = None,
    benchmark: str | None = None,
) -> dict:
    """Simulate buying a stock on start_date and calculate returns as of end_date.

    Parameters
    ----------
    symbol : str
        Stock ticker symbol (e.g. RELIANCE, TCS, SAP).
    exchange : str
        Exchange code (NSE, BSE, XETRA, etc.).
    invest_amount : float
        Amount to invest (in the stock's currency).
    start_date : date
        Date of hypothetical purchase.
    end_date : date or None
        Date to check value (defaults to today).
    benchmark : str or None
        Optional benchmark name (NIFTY50, SENSEX, DAX) for comparison.

    Returns
    -------
    dict
        Simulation results matching WhatIfResponse schema.

    Raises
    ------
    ValueError
        If historical data cannot be fetched or dates are invalid.
    """
    if end_date is None:
        end_date = date.today()

    if start_date >= end_date:
        raise ValueError("start_date must be before end_date")

    ticker_str = _ticker_symbol(symbol, exchange)

    # Fetch historical data for the date range
    # Add a few extra days buffer on each side to account for non-trading days
    fetch_start = start_date - timedelta(days=7)
    fetch_end = end_date + timedelta(days=3)

    def _fetch_sync():
        t = yf.Ticker(ticker_str)
        return t.history(start=fetch_start.isoformat(), end=fetch_end.isoformat())

    try:
        hist = await asyncio.wait_for(asyncio.to_thread(_fetch_sync), timeout=15.0)
    except asyncio.TimeoutError as e:
        raise ValueError(f"Timeout fetching data for {symbol}") from e
    except Exception as e:
        raise ValueError(f"Failed to fetch data for {symbol}: {e}") from e

    if hist.empty:
        raise ValueError(f"No historical data available for {ticker_str}")

    # Find the closest trading day on or after start_date
    hist.index = hist.index.tz_localize(None) if hist.index.tz else hist.index
    start_mask = hist.index.date >= start_date
    if not start_mask.any():
        raise ValueError(f"No trading data available on or after {start_date}")
    start_row = hist[start_mask].iloc[0]
    actual_start = hist[start_mask].index[0].date()

    # Find the closest trading day on or before end_date
    end_mask = hist.index.date <= end_date
    if not end_mask.any():
        raise ValueError(f"No trading data available on or before {end_date}")
    end_row = hist[end_mask].iloc[-1]
    actual_end = hist[end_mask].index[-1].date()

    buy_price = float(start_row["Close"])
    end_price = float(end_row["Close"])

    if buy_price <= 0:
        raise ValueError(f"Invalid buy price for {symbol}")

    shares_bought = invest_amount / buy_price
    current_value = shares_bought * end_price
    absolute_return = current_value - invest_amount
    percentage_return = ((current_value - invest_amount) / invest_amount) * 100

    # Annualized return
    holding_period_days = (actual_end - actual_start).days
    annualized_return: float | None = None
    if holding_period_days > 0:
        years = holding_period_days / 365.25
        if years > 0 and current_value > 0 and invest_amount > 0:
            annualized_return = round(
                ((current_value / invest_amount) ** (1 / years) - 1) * 100, 2
            )

    # Optional benchmark comparison
    benchmark_data: dict | None = None
    if benchmark:
        benchmark_data = await _fetch_benchmark_return(
            benchmark, actual_start, actual_end
        )

    return {
        "symbol": symbol,
        "exchange": exchange,
        "invest_amount": invest_amount,
        "start_date": actual_start,
        "end_date": actual_end,
        "buy_price": round(buy_price, 4),
        "end_price": round(end_price, 4),
        "shares_bought": round(shares_bought, 6),
        "current_value": round(current_value, 2),
        "absolute_return": round(absolute_return, 2),
        "percentage_return": round(percentage_return, 2),
        "annualized_return": annualized_return,
        "holding_period_days": holding_period_days,
        "benchmark": benchmark_data,
    }


# ---------------------------------------------------------------------------
# Benchmark helper
# ---------------------------------------------------------------------------

async def _fetch_benchmark_return(
    benchmark_name: str, start: date, end: date
) -> dict | None:
    """Fetch benchmark index return for the same period."""
    bench_symbol = BENCHMARKS.get(benchmark_name)
    if not bench_symbol:
        return None

    try:
        fetch_start = start - timedelta(days=7)
        fetch_end = end + timedelta(days=3)

        def _fetch_bench_sync():
            t = yf.Ticker(bench_symbol)
            return t.history(start=fetch_start.isoformat(), end=fetch_end.isoformat())

        hist = await asyncio.wait_for(asyncio.to_thread(_fetch_bench_sync), timeout=15.0)
        if hist.empty:
            return None

        hist.index = hist.index.tz_localize(None) if hist.index.tz else hist.index

        start_mask = hist.index.date >= start
        end_mask = hist.index.date <= end

        if not start_mask.any() or not end_mask.any():
            return None

        bench_start_price = float(hist[start_mask].iloc[0]["Close"])
        bench_end_price = float(hist[end_mask].iloc[-1]["Close"])

        if bench_start_price <= 0:
            return None

        bench_return = ((bench_end_price - bench_start_price) / bench_start_price) * 100

        return {
            "benchmark_name": benchmark_name,
            "benchmark_start_price": round(bench_start_price, 4),
            "benchmark_end_price": round(bench_end_price, 4),
            "benchmark_return_pct": round(bench_return, 2),
        }
    except Exception:
        logger.warning("Benchmark data fetch failed for %s", benchmark_name)
        return None
