"""Benchmark comparison — compare portfolio performance vs major indices."""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta

import yfinance as yf

logger = logging.getLogger(__name__)


BENCHMARKS = {
    "NIFTY50": "^NSEI",
    "SENSEX": "^BSESN",
    "DAX": "^GDAXI",
    "S&P500": "^GSPC",
    "NASDAQ": "^IXIC",
}


@dataclass
class BenchmarkComparison:
    benchmark_name: str
    benchmark_symbol: str
    portfolio_return_pct: float | None
    benchmark_return_pct: float
    alpha: float | None  # portfolio_return - benchmark_return; None when history insufficient
    period_days: int
    data_points: list[dict]  # [{date, portfolio_value, benchmark_value}]
    insufficient_history: bool = False


async def compare_with_benchmark(
    portfolio_daily_values: list[dict],  # [{date: str, value: float}]
    benchmark_name: str = "NIFTY50",
    days: int = 90,
) -> BenchmarkComparison | None:
    """Compare portfolio performance against a benchmark index.

    portfolio_daily_values: list of {date: "YYYY-MM-DD", value: float} dicts
    (portfolio total value per day)
    """
    symbol = BENCHMARKS.get(benchmark_name)
    if not symbol:
        return None

    end = date.today()
    start = end - timedelta(days=days)

    def _fetch_sync():
        t = yf.Ticker(symbol)
        return t.history(start=start.isoformat(), end=end.isoformat())

    try:
        hist = await asyncio.wait_for(asyncio.to_thread(_fetch_sync), timeout=15.0)
        if hist.empty:
            return None
    except TimeoutError:
        logger.warning("yfinance timeout fetching benchmark %s", benchmark_name)
        return None
    except Exception:
        return None

    benchmark_closes = [
        (d.date().isoformat(), float(row["Close"]))
        for d, row in hist.iterrows()
        if not (math.isnan(float(row["Close"])) or math.isinf(float(row["Close"])))
    ]
    if not benchmark_closes:
        return None

    # Calculate returns
    bench_start = benchmark_closes[0][1]
    bench_end = benchmark_closes[-1][1]
    if bench_start <= 0:
        return None
    benchmark_return = ((bench_end - bench_start) / bench_start) * 100

    # Portfolio return from daily values — clipped to the benchmark's date
    # range so both returns cover the same period (comparing a full-history
    # portfolio return against a windowed benchmark return fabricates alpha).
    #
    # When fewer than two portfolio points fall inside the window there is no
    # honest period return to compute, so we degrade gracefully: the benchmark
    # comparison is still returned, but ``portfolio_return_pct`` / ``alpha`` are
    # ``None`` and ``insufficient_history`` is set — never a fabricated number.
    bench_first_date = benchmark_closes[0][0]
    bench_last_date = benchmark_closes[-1][0]
    aligned_pf = [
        p for p in portfolio_daily_values
        if bench_first_date <= p["date"] <= bench_last_date
    ]
    if len(aligned_pf) < 2:
        aligned_pf = list(portfolio_daily_values)

    insufficient = len(aligned_pf) < 2
    pf_start: float | None = None
    portfolio_return: float | None = None
    if not insufficient:
        pf_start = aligned_pf[0]["value"]
        pf_end = aligned_pf[-1]["value"]
        portfolio_return = (
            ((pf_end - pf_start) / pf_start) * 100 if pf_start and pf_start > 0 else 0.0
        )

    # Build normalized data points (both starting at 100)
    data_points = []
    for d_str, close in benchmark_closes:
        normalized_bench = (close / bench_start) * 100
        # Find matching portfolio value for the day (if any)
        pf_val = next((p["value"] for p in portfolio_daily_values if p["date"] == d_str), None)
        normalized_pf = (
            (pf_val / pf_start) * 100 if (pf_val and pf_start and pf_start > 0) else None
        )
        data_points.append({
            "date": d_str,
            "benchmark_value": round(normalized_bench, 2),
            "portfolio_value": round(normalized_pf, 2) if normalized_pf else None,
        })

    alpha = (
        round(portfolio_return - benchmark_return, 2)
        if portfolio_return is not None
        else None
    )

    return BenchmarkComparison(
        benchmark_name=benchmark_name,
        benchmark_symbol=symbol,
        portfolio_return_pct=(
            round(portfolio_return, 2) if portfolio_return is not None else None
        ),
        benchmark_return_pct=round(benchmark_return, 2),
        alpha=alpha,
        period_days=days,
        data_points=data_points,
        insufficient_history=insufficient,
    )
