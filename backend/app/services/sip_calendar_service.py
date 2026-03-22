"""SIP Calendar Service — aggregate financial events into a monthly calendar.

Combines three sources of events:
1. **SIP dates** — projected from detected recurring transactions
2. **Dividend payment dates** — from the existing dividend model
3. **Upcoming earnings** — fetched from yfinance (graceful degradation)

Returns a flat list of calendar events for a given month/year, each with a
type, date, amount, and associated stock.
"""

from __future__ import annotations

import asyncio
import logging
from calendar import monthrange
from datetime import date, timedelta

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dividend import Dividend
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.transaction import Transaction
from app.services.market_data_service import _ticker_symbol
from app.services.recurring_detection_service import detect_recurring

logger = logging.getLogger(__name__)


def _sync_fetch_earnings_calendar(ticker_str: str):
    """Fetch yfinance calendar synchronously (runs in a thread)."""
    ticker = yf.Ticker(ticker_str)
    return ticker.calendar


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

EVENT_SIP = "SIP"
EVENT_DIVIDEND = "DIVIDEND"
EVENT_EARNINGS = "EARNINGS"


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

async def get_calendar_events(
    user_id: int,
    portfolio_id: int,
    month: int,
    year: int,
    db: AsyncSession,
) -> list[dict]:
    """Return a list of calendar events for *month*/*year*.

    Each event dict contains::

        {
            "type": "SIP" | "DIVIDEND" | "EARNINGS",
            "date": "2026-02-15",
            "stock_symbol": "HDFCBANK",
            "stock_name": "HDFC Bank",
            "exchange": "NSE",
            "amount": 5000.0,       # null for earnings
            "description": "...",
        }
    """
    events: list[dict] = []

    # Date bounds for the requested month
    _, last_day = monthrange(year, month)
    month_start = date(year, month, 1)
    month_end = date(year, month, last_day)

    # ── 1. SIP events (from recurring detection) ──────────────────────
    try:
        recurring = await detect_recurring(portfolio_id, db)
        for sip in recurring:
            next_date_str = sip.get("next_expected_date")
            if not next_date_str:
                continue
            next_date = date.fromisoformat(next_date_str)

            # Project forward if next_expected_date is before month_start
            avg_interval = int(sip.get("avg_interval_days", 30))
            if avg_interval <= 0:
                avg_interval = 30

            # Walk the projected date into the requested month window
            projected = next_date
            while projected < month_start:
                projected += timedelta(days=avg_interval)

            # Collect all occurrences within the month
            while projected <= month_end:
                events.append(
                    {
                        "type": EVENT_SIP,
                        "date": projected.isoformat(),
                        "stock_symbol": sip["stock_symbol"],
                        "stock_name": sip["stock_name"],
                        "exchange": sip["exchange"],
                        "amount": sip["avg_amount"],
                        "description": (
                            f"{sip['frequency'].capitalize()} SIP — "
                            f"{sip['stock_symbol']} "
                            f"~{sip['avg_quantity']} shares"
                        ),
                    }
                )
                projected += timedelta(days=avg_interval)
    except Exception:
        logger.exception("Failed to generate SIP calendar events")

    # ── 2. Dividend payment dates ─────────────────────────────────────
    try:
        # Get holding IDs for this portfolio
        h_result = await db.execute(
            select(Holding).where(Holding.portfolio_id == portfolio_id)
        )
        holdings = {h.id: h for h in h_result.scalars().all()}

        if holdings:
            div_result = await db.execute(
                select(Dividend).where(
                    Dividend.holding_id.in_(list(holdings.keys())),
                    Dividend.payment_date >= month_start,
                    Dividend.payment_date <= month_end,
                )
            )
            dividends = list(div_result.scalars().all())

            for div in dividends:
                holding = holdings.get(div.holding_id)
                events.append(
                    {
                        "type": EVENT_DIVIDEND,
                        "date": div.payment_date.isoformat() if div.payment_date else div.ex_date.isoformat(),
                        "stock_symbol": holding.stock_symbol if holding else "N/A",
                        "stock_name": holding.stock_name if holding else "N/A",
                        "exchange": holding.exchange if holding else "",
                        "amount": float(div.total_amount),
                        "description": (
                            f"Dividend payment — "
                            f"{float(div.amount_per_share)}/share"
                        ),
                    }
                )
    except Exception:
        logger.exception("Failed to generate dividend calendar events")

    # ── 3. Upcoming earnings (parallel fetch) ─────────────────────────
    try:
        h_result = await db.execute(
            select(Holding).where(Holding.portfolio_id == portfolio_id)
        )
        holdings_list = list(h_result.scalars().all())

        # Fetch all earnings calendars in parallel
        fetch_tasks = [
            asyncio.wait_for(
                asyncio.to_thread(
                    _sync_fetch_earnings_calendar,
                    _ticker_symbol(h.stock_symbol, h.exchange),
                ),
                timeout=10.0,
            )
            for h in holdings_list
        ]
        fetch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        for h, cal in zip(holdings_list, fetch_results):
            try:
                if isinstance(cal, Exception) or cal is None:
                    continue

                # yfinance returns a dict or DataFrame depending on version
                earnings_date = None
                if isinstance(cal, dict):
                    earnings_dates = cal.get("Earnings Date", [])
                    if earnings_dates:
                        earnings_date = earnings_dates[0]
                elif hasattr(cal, "columns"):
                    # DataFrame case
                    if "Earnings Date" in cal.columns:
                        earnings_date = cal["Earnings Date"].iloc[0]

                if earnings_date is not None:
                    if hasattr(earnings_date, "date"):
                        ed = earnings_date.date()
                    elif isinstance(earnings_date, str):
                        ed = date.fromisoformat(earnings_date)
                    else:
                        ed = earnings_date

                    if month_start <= ed <= month_end:
                        events.append(
                            {
                                "type": EVENT_EARNINGS,
                                "date": ed.isoformat(),
                                "stock_symbol": h.stock_symbol,
                                "stock_name": h.stock_name,
                                "exchange": h.exchange,
                                "amount": None,
                                "description": f"Earnings release — {h.stock_name}",
                            }
                        )
            except Exception:
                # Graceful degradation per stock
                logger.debug("Earnings fetch failed for %s", h.stock_symbol)
    except Exception:
        logger.exception("Failed to generate earnings calendar events")

    # Sort all events by date
    events.sort(key=lambda e: e["date"])

    return events
