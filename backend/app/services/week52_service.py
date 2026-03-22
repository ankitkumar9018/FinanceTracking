"""52-Week Proximity Service — how close each holding is to its 52-week extremes.

For every holding in a portfolio, fetches the 52-week high and low via yfinance
and computes:
- **high_proximity_pct**: how close the current price is to the 52-week high
  (100 % = at the high, 0 % = at the low)
- **low_proximity_pct**: how close the current price is to the 52-week low
  (100 % = at the low, 0 % = at the high)
"""

from __future__ import annotations

import asyncio
import logging

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.holding import Holding
from app.services.market_data_service import _safe_float, _ticker_symbol

logger = logging.getLogger(__name__)


def _sync_fetch_52week(ticker_str: str) -> tuple[float | None, float | None, float | None]:
    """Fetch 52-week high/low and current price synchronously (runs in a thread).

    Returns (week52_high, week52_low, current_price_fallback).
    """
    ticker = yf.Ticker(ticker_str)
    week52_high: float | None = None
    week52_low: float | None = None
    current_fallback: float | None = None

    try:
        info = ticker.fast_info
        week52_high = _safe_float(info.year_high) if hasattr(info, "year_high") else None
        week52_low = _safe_float(info.year_low) if hasattr(info, "year_low") else None
        if hasattr(info, "last_price"):
            current_fallback = _safe_float(info.last_price)
    except Exception:
        info = ticker.info
        week52_high = _safe_float(info.get("fiftyTwoWeekHigh"))
        week52_low = _safe_float(info.get("fiftyTwoWeekLow"))
        current_fallback = _safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))

    return week52_high, week52_low, current_fallback


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

async def get_52week_proximity(
    portfolio_id: int,
    db: AsyncSession,
) -> list[dict]:
    """Return 52-week high/low proximity for each holding.

    Each dict in the returned list has::

        {
            "holding_id": 42,
            "stock_symbol": "RELIANCE",
            "stock_name": "Reliance Industries",
            "exchange": "NSE",
            "current_price": 2850.0,
            "week52_high": 3000.0,
            "week52_low": 2200.0,
            "high_proximity_pct": 81.25,
            "low_proximity_pct": 18.75,
            "near_high": False,
            "near_low": False,
        }

    ``near_high`` / ``near_low`` are set when the price is within 5 %
    of the respective extreme.
    """
    result = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio_id)
    )
    holdings = list(result.scalars().all())

    if not holdings:
        return []

    proximity_data: list[dict] = []

    # ── Parallel fetch: all 52-week data concurrently ────────────────
    fetch_tasks = [
        asyncio.wait_for(
            asyncio.to_thread(_sync_fetch_52week, _ticker_symbol(h.stock_symbol, h.exchange)),
            timeout=10.0,
        )
        for h in holdings
    ]
    fetch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

    for h, fetch_result in zip(holdings, fetch_results):
        current_price = (
            float(h.current_price) if h.current_price is not None else None
        )

        week52_high: float | None = None
        week52_low: float | None = None

        if isinstance(fetch_result, Exception):
            logger.warning("yfinance 52-week fetch failed for %s", h.stock_symbol)
        else:
            w_high, w_low, price_fallback = fetch_result
            week52_high = w_high
            week52_low = w_low
            if current_price is None:
                current_price = price_fallback

        # Compute proximity percentages
        high_prox: float | None = None
        low_prox: float | None = None
        near_high = False
        near_low = False

        if (
            current_price is not None
            and week52_high is not None
            and week52_low is not None
            and week52_high > week52_low
        ):
            range_size = week52_high - week52_low
            high_prox = round(
                ((current_price - week52_low) / range_size) * 100, 2
            )
            low_prox = round(
                ((week52_high - current_price) / range_size) * 100, 2
            )

            # Clamp to 0-100
            high_prox = max(0.0, min(100.0, high_prox))
            low_prox = max(0.0, min(100.0, low_prox))

            # Near flags: within 5 % of the extreme
            if week52_high > 0:
                near_high = ((week52_high - current_price) / week52_high) <= 0.05
            if week52_low > 0:
                near_low = ((current_price - week52_low) / week52_low) <= 0.05

        proximity_data.append(
            {
                "holding_id": h.id,
                "stock_symbol": h.stock_symbol,
                "stock_name": h.stock_name,
                "exchange": h.exchange,
                "current_price": current_price,
                "week52_high": week52_high,
                "week52_low": week52_low,
                "high_proximity_pct": high_prox,
                "low_proximity_pct": low_prox,
                "near_high": near_high,
                "near_low": near_low,
            }
        )

    return proximity_data
