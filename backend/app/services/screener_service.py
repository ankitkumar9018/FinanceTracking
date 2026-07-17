"""Stock screener service.

Screens a universe of symbols against cheap-to-compute filters derived from
yfinance ``.info`` fundamentals plus a short price history. This deliberately
targets a *curated, liquid* universe (a NIFTY-heavyweight-style list per
exchange) rather than the whole market — that keeps every scan fast, bounded
and predictable without depending on a paid screener API.

Filterable fields
-----------------
- ``market_cap``          (min / max)
- ``pe_ratio``            (min / max)   -- trailing P/E from .info
- ``dividend_yield``      (min)         -- normalised to a percentage
- ``price``               (min / max)
- ``sector``              (case-insensitive substring match)
- ``rsi_14``              (min / max)   -- computed from recent closes
- ``week52_position_pct`` (min / max)   -- where price sits in its 52-wk range
- ``day_change_pct``      (min / max)

Every symbol is fetched with yfinance in a worker thread, under a bounded
concurrency semaphore and a per-symbol timeout; failures are skipped rather
than aborting the whole scan.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import pandas as pd
import yfinance as yf

from app.ml.technical_indicators import calculate_rsi
from app.services.market_data_service import _safe_float, _ticker_symbol

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Curated, liquid universe (kept small so scans stay fast & predictable)
# ---------------------------------------------------------------------------
# NSE: NIFTY-50 heavyweights across sectors. XETRA: liquid DAX names.
# These are the *default* universe when the caller doesn't pass explicit
# symbols. The combined universe is always capped (see MAX_UNIVERSE).

_DEFAULT_UNIVERSE: dict[str, list[str]] = {
    "NSE": [
        "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY",
        "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
        "LT", "AXISBANK", "BAJFINANCE", "ASIANPAINT", "MARUTI",
        "HCLTECH", "SUNPHARMA", "TITAN", "ULTRACEMCO", "WIPRO",
        "NESTLEIND", "TATAMOTORS", "TATASTEEL", "POWERGRID", "NTPC",
        "ONGC", "ADANIENT", "ADANIPORTS", "JSWSTEEL", "COALINDIA",
        "TECHM", "GRASIM",
    ],
    "XETRA": [
        "SAP", "SIE", "ALV", "DTE", "BMW", "MBG", "BAS", "VOW3",
    ],
}

# Hard cap on how many symbols a single scan will actually fetch. Anything
# beyond this is dropped and reported via the ``truncated`` flag.
MAX_UNIVERSE = 60

# yfinance / concurrency tuning
_MAX_CONCURRENCY = 10       # simultaneous yfinance calls
_PER_SYMBOL_TIMEOUT = 8.0   # seconds per symbol before it's skipped
_HISTORY_PERIOD = "3mo"     # enough closes to warm up a 14-period RSI


@dataclass
class ScreenerFilters:
    """Optional numeric / string filters. ``None`` means "don't filter"."""

    market_cap_min: float | None = None
    market_cap_max: float | None = None
    pe_min: float | None = None
    pe_max: float | None = None
    dividend_yield_min: float | None = None
    price_min: float | None = None
    price_max: float | None = None
    sector: str | None = None
    rsi_min: float | None = None
    rsi_max: float | None = None
    week52_min: float | None = None
    week52_max: float | None = None
    day_change_min: float | None = None
    day_change_max: float | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dividend_yield_pct(info: dict) -> float | None:
    """Return dividend yield as a percentage, robust across yfinance versions.

    ``trailingAnnualDividendYield`` is consistently a fraction, so prefer it.
    ``dividendYield`` has been a fraction in older yfinance and a percentage in
    newer ones — normalise defensively (values < 1 are treated as fractions).
    """
    tay = _safe_float(info.get("trailingAnnualDividendYield"))
    if tay is not None:
        return round(tay * 100, 2)
    dy = _safe_float(info.get("dividendYield"))
    if dy is None:
        return None
    return round(dy * 100 if dy < 1 else dy, 2)


def _week52_position_pct(
    price: float | None, high: float | None, low: float | None
) -> float | None:
    """Where *price* sits in the 52-week range (0 = at low, 100 = at high)."""
    if price is None or high is None or low is None or high <= low:
        return None
    pos = ((price - low) / (high - low)) * 100
    return round(max(0.0, min(100.0, pos)), 2)


def _rsi_from_closes(closes: list[float]) -> float | None:
    """Compute the latest RSI-14 from a list of close prices."""
    if len(closes) < 15:
        return None
    try:
        series = calculate_rsi(pd.Series(closes), period=14)
        val = series.dropna()
        if val.empty:
            return None
        return round(float(val.iloc[-1]), 2)
    except Exception:
        logger.debug("RSI computation failed", exc_info=True)
        return None


def _sync_fetch_symbol(ticker_str: str) -> tuple[dict, list[float]]:
    """Fetch ``.info`` and a short close-price history (runs in a thread)."""
    ticker = yf.Ticker(ticker_str)
    info = ticker.info or {}
    closes: list[float] = []
    try:
        hist = ticker.history(period=_HISTORY_PERIOD)
        if not hist.empty:
            for c in hist["Close"].tolist():
                cf = _safe_float(c)
                if cf is not None:
                    closes.append(cf)
    except Exception:
        logger.debug("history fetch failed for %s", ticker_str, exc_info=True)
    return info, closes


def _in_range(
    value: float | None, lo: float | None, hi: float | None
) -> bool:
    """True if *value* satisfies the optional [lo, hi] bounds.

    A bound that is set but a missing *value* fails the filter (we can't claim
    a stock matches a criterion we couldn't evaluate).
    """
    if lo is None and hi is None:
        return True
    if value is None:
        return False
    if lo is not None and value < lo:
        return False
    if hi is not None and value > hi:
        return False
    return True


def _passes(metrics: dict, f: ScreenerFilters) -> bool:
    """Apply every active filter to a symbol's evaluated metrics."""
    if not _in_range(metrics["market_cap"], f.market_cap_min, f.market_cap_max):
        return False
    if not _in_range(metrics["pe_ratio"], f.pe_min, f.pe_max):
        return False
    if f.dividend_yield_min is not None:
        dy = metrics["dividend_yield"]
        if dy is None or dy < f.dividend_yield_min:
            return False
    if not _in_range(metrics["price"], f.price_min, f.price_max):
        return False
    if not _in_range(metrics["rsi"], f.rsi_min, f.rsi_max):
        return False
    if not _in_range(
        metrics["week52_position_pct"], f.week52_min, f.week52_max
    ):
        return False
    if not _in_range(
        metrics["day_change_pct"], f.day_change_min, f.day_change_max
    ):
        return False
    if f.sector:
        sector = (metrics["sector"] or "").lower()
        if f.sector.strip().lower() not in sector:
            return False
    return True


# ---------------------------------------------------------------------------
# Universe assembly
# ---------------------------------------------------------------------------

def _build_universe(
    exchange: str, symbols: list[str] | None
) -> tuple[list[str], bool]:
    """Return (deduped symbol list, truncated?) capped at ``MAX_UNIVERSE``.

    Combines any explicitly-supplied symbols with the curated default list for
    the exchange. Order is preserved (explicit symbols first).
    """
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(sym: str) -> None:
        s = sym.upper().strip()
        if s and s not in seen:
            seen.add(s)
            ordered.append(s)

    for s in symbols or []:
        _add(s)
    for s in _DEFAULT_UNIVERSE.get(exchange.upper(), []):
        _add(s)

    truncated = len(ordered) > MAX_UNIVERSE
    if truncated:
        logger.info(
            "Screener universe truncated from %d to %d symbols",
            len(ordered),
            MAX_UNIVERSE,
        )
    return ordered[:MAX_UNIVERSE], truncated


# ---------------------------------------------------------------------------
# Core screen
# ---------------------------------------------------------------------------

async def screen_stocks(
    filters: ScreenerFilters,
    *,
    exchange: str = "NSE",
    symbols: list[str] | None = None,
) -> dict:
    """Screen the universe against *filters*.

    Returns::

        {
            "scanned": int,      # symbols actually fetched (failures included)
            "matched": int,      # symbols passing every active filter
            "truncated": bool,   # universe exceeded MAX_UNIVERSE and was cut
            "universe_size": int,
            "results": [ {symbol, name, exchange, price, market_cap,
                          pe_ratio, dividend_yield, rsi,
                          week52_position_pct, sector, day_change_pct}, ... ],
        }
    """
    exchange = exchange.upper().strip()
    universe, truncated = _build_universe(exchange, symbols)

    if not universe:
        return {
            "scanned": 0,
            "matched": 0,
            "truncated": False,
            "universe_size": 0,
            "results": [],
        }

    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def _evaluate(symbol: str) -> dict | None:
        ticker_str = _ticker_symbol(symbol, exchange)
        async with semaphore:
            try:
                info, closes = await asyncio.wait_for(
                    asyncio.to_thread(_sync_fetch_symbol, ticker_str),
                    timeout=_PER_SYMBOL_TIMEOUT,
                )
            except Exception:
                logger.debug("screener fetch skipped for %s", ticker_str)
                return None

        # Price: prefer live .info fields, fall back to the last close.
        price = _safe_float(
            info.get("currentPrice") or info.get("regularMarketPrice")
        )
        if price is None and closes:
            price = round(closes[-1], 4)

        prev_close = _safe_float(
            info.get("previousClose") or info.get("regularMarketPreviousClose")
        )
        day_change_pct: float | None = None
        if price is not None and prev_close:
            day_change_pct = round((price - prev_close) / prev_close * 100, 2)
        elif len(closes) >= 2 and closes[-2]:
            day_change_pct = round(
                (closes[-1] - closes[-2]) / closes[-2] * 100, 2
            )

        high = _safe_float(info.get("fiftyTwoWeekHigh"))
        low = _safe_float(info.get("fiftyTwoWeekLow"))
        if high is None and closes:
            high = round(max(closes), 4)
        if low is None and closes:
            low = round(min(closes), 4)

        metrics = {
            "symbol": symbol,
            "name": info.get("shortName") or info.get("longName") or symbol,
            "exchange": exchange,
            "price": price,
            "market_cap": _safe_float(info.get("marketCap")),
            "pe_ratio": _safe_float(info.get("trailingPE")),
            "dividend_yield": _dividend_yield_pct(info),
            "rsi": _rsi_from_closes(closes),
            "week52_position_pct": _week52_position_pct(price, high, low),
            "sector": info.get("sector"),
            "day_change_pct": day_change_pct,
        }
        return metrics

    evaluated = await asyncio.gather(
        *(_evaluate(s) for s in universe), return_exceptions=True
    )

    scanned = 0
    results: list[dict] = []
    for item in evaluated:
        if isinstance(item, Exception) or item is None:
            continue
        scanned += 1
        if _passes(item, filters):
            results.append(item)

    # Highest 52-week position first is a sensible default ordering; the UI
    # can re-sort. Fall back gracefully when the metric is missing.
    results.sort(
        key=lambda m: (m["week52_position_pct"] is None, -(m["week52_position_pct"] or 0))
    )

    return {
        "scanned": scanned,
        "matched": len(results),
        "truncated": truncated,
        "universe_size": len(universe),
        "results": results,
    }
