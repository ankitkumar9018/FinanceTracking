"""Stock comparison — compare 2-3 stocks side by side."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from dataclasses import dataclass

import math

import yfinance as yf

logger = logging.getLogger(__name__)


def _safe_float_val(val) -> float | None:
    """Convert a value to float, returning None for NaN/Inf/invalid values."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else f
    except (ValueError, TypeError):
        return None


@dataclass
class StockMetrics:
    symbol: str
    name: str
    exchange: str
    current_price: float | None
    day_change_pct: float | None
    week_52_high: float | None
    week_52_low: float | None
    pe_ratio: float | None
    market_cap: float | None
    volume: int | None
    dividend_yield: float | None
    beta: float | None


@dataclass
class StockComparison:
    stocks: list[StockMetrics]
    price_history: dict[str, list[dict]]  # symbol -> [{date, close}]
    period_days: int


def _sync_fetch_stock_data(yf_symbol: str, days: int) -> tuple[dict, list[dict]]:
    """Fetch stock info and price history synchronously (runs in thread)."""
    ticker = yf.Ticker(yf_symbol)
    info = ticker.info or {}

    end = date.today()
    start = end - timedelta(days=days)
    hist = ticker.history(start=start.isoformat(), end=end.isoformat())

    history: list[dict] = []
    if not hist.empty:
        for d, row in hist.iterrows():
            c = _safe_float_val(row["Close"])
            if c is not None:
                history.append({"date": d.date().isoformat(), "close": round(c, 2)})

    return info, history


async def compare_stocks(
    symbols: list[str],
    exchanges: list[str] | None = None,
    days: int = 90,
) -> StockComparison:
    """Compare up to 3 stocks with their key metrics and price history."""
    from app.services.market_data_service import _ticker_symbol

    stocks: list[StockMetrics] = []
    price_history: dict[str, list[dict]] = {}

    for i, symbol in enumerate(symbols[:3]):
        exchange = exchanges[i] if exchanges and i < len(exchanges) else "NSE"
        yf_symbol = _ticker_symbol(symbol, exchange)

        try:
            info, history = await asyncio.wait_for(
                asyncio.to_thread(_sync_fetch_stock_data, yf_symbol, days),
                timeout=10.0,
            )

            current = _safe_float_val(info.get("currentPrice") or info.get("regularMarketPrice"))
            prev_close = _safe_float_val(info.get("previousClose") or info.get("regularMarketPreviousClose"))
            day_change = ((current - prev_close) / prev_close * 100) if current and prev_close else None

            metrics = StockMetrics(
                symbol=symbol,
                name=info.get("shortName") or info.get("longName") or symbol,
                exchange=exchange,
                current_price=current,
                day_change_pct=round(day_change, 2) if day_change else None,
                week_52_high=_safe_float_val(info.get("fiftyTwoWeekHigh")),
                week_52_low=_safe_float_val(info.get("fiftyTwoWeekLow")),
                pe_ratio=_safe_float_val(info.get("trailingPE")),
                market_cap=_safe_float_val(info.get("marketCap")),
                volume=info.get("volume"),
                dividend_yield=_safe_float_val(info.get("dividendYield")),
                beta=_safe_float_val(info.get("beta")),
            )
            stocks.append(metrics)
            price_history[symbol] = history

        except Exception:
            logger.warning("Stock data fetch failed for %s", symbol)
            stocks.append(StockMetrics(
                symbol=symbol, name=symbol, exchange=exchange,
                current_price=None, day_change_pct=None, week_52_high=None,
                week_52_low=None, pe_ratio=None, market_cap=None,
                volume=None, dividend_yield=None, beta=None,
            ))
            price_history[symbol] = []

    return StockComparison(stocks=stocks, price_history=price_history, period_days=days)
