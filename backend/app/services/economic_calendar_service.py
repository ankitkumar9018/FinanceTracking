"""Economic / Macro & Catalysts Calendar Service.

Builds a single, unified dated feed of upcoming catalysts relevant to a user's
holdings, merging three sources:

* ``EARNINGS`` — upcoming earnings dates for held symbols (yfinance, reusing the
  same ``Ticker.calendar`` logic as :mod:`app.services.earnings_service`).
* ``EX_DIV``   — upcoming ex-dividend dates for held symbols (yfinance,
  best-effort via ``Ticker.calendar`` / ``Ticker.info``).
* ``MACRO``    — a **curated static** list of key macro events (RBI + ECB rate
  decisions, US / India CPI prints, US jobs report). See
  :data:`CURATED_MACRO_EVENTS` below.

.. important::
   The macro events are a **curated, hand-maintained static source**, *not* a
   live macro-data API. Refresh :data:`CURATED_MACRO_EVENTS` roughly once a
   quarter (or whenever central-bank / statistics-agency calendars publish new
   dates). Each entry is a plain ``{date, region, event, importance}`` dict so
   the list is trivial to update.

All yfinance access runs in threads (``asyncio.to_thread``) with a bounded
concurrency semaphore and per-call timeout, and degrades gracefully: any symbol
that fails to fetch is simply skipped.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.holding import Holding
from app.services.market_data_service import _ticker_symbol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

EVENT_EARNINGS = "EARNINGS"
EVENT_EX_DIV = "EX_DIV"
EVENT_MACRO = "MACRO"


# ---------------------------------------------------------------------------
# Tuning knobs
# ---------------------------------------------------------------------------

# How far ahead (days) to include events. ~3 months.
_LOOKAHEAD_DAYS = 100

# Bound concurrent yfinance calls and per-call time budget.
_FETCH_CONCURRENCY = 6
_FETCH_TIMEOUT_S = 10.0


# Map exchange codes to a human-readable region label so every event — whether
# a stock catalyst or a macro print — carries a consistent region tag.
_EXCHANGE_REGION: dict[str, str] = {
    "NSE": "India",
    "BSE": "India",
    "XETRA": "Germany",
    "FRA": "Germany",
    "NYSE": "US",
    "NASDAQ": "US",
}


def _region_for_exchange(exchange: str | None) -> str:
    """Return a region label for an exchange code (defaults to ``Global``)."""
    if not exchange:
        return "Global"
    return _EXCHANGE_REGION.get(exchange.upper(), "Global")


# ---------------------------------------------------------------------------
# Curated static macro events
# ---------------------------------------------------------------------------
#
# Hand-maintained list of key scheduled macro catalysts for the next ~quarter.
# This is a CURATED STATIC SOURCE, not a live feed — update it roughly every
# quarter from the official calendars:
#   * RBI MPC .............. https://www.rbi.org.in (Monetary Policy)
#   * ECB Governing Council  https://www.ecb.europa.eu (monetary policy meetings)
#   * US CPI / Jobs (BLS) .. https://www.bls.gov/schedule/news_release/
#   * India CPI (MoSPI) .... https://www.mospi.gov.in
#   * US FOMC .............. https://www.federalreserve.gov
#
# ``importance`` is one of "high" | "medium". ``date`` is ISO ``YYYY-MM-DD``.
# Last reviewed: 2026-07 (covers ~2026-07 through 2026-10).
CURATED_MACRO_EVENTS: list[dict] = [
    # ── Central-bank rate decisions ──────────────────────────────────
    {"date": "2026-07-23", "region": "Eurozone", "event": "ECB rate decision", "importance": "high"},
    {"date": "2026-07-29", "region": "US", "event": "US FOMC rate decision", "importance": "high"},
    {"date": "2026-08-06", "region": "India", "event": "RBI MPC rate decision", "importance": "high"},
    {"date": "2026-09-10", "region": "Eurozone", "event": "ECB rate decision", "importance": "high"},
    {"date": "2026-09-16", "region": "US", "event": "US FOMC rate decision", "importance": "high"},
    {"date": "2026-10-01", "region": "India", "event": "RBI MPC rate decision", "importance": "high"},
    # ── Inflation (CPI) prints ───────────────────────────────────────
    {"date": "2026-08-12", "region": "US", "event": "US CPI (July)", "importance": "high"},
    {"date": "2026-08-12", "region": "India", "event": "India CPI (July)", "importance": "medium"},
    {"date": "2026-09-11", "region": "US", "event": "US CPI (August)", "importance": "high"},
    {"date": "2026-09-14", "region": "India", "event": "India CPI (August)", "importance": "medium"},
    {"date": "2026-10-13", "region": "India", "event": "India CPI (September)", "importance": "medium"},
    {"date": "2026-10-15", "region": "US", "event": "US CPI (September)", "importance": "high"},
    # ── US jobs report (Nonfarm Payrolls, first Friday) ──────────────
    {"date": "2026-08-07", "region": "US", "event": "US jobs report (July NFP)", "importance": "high"},
    {"date": "2026-09-04", "region": "US", "event": "US jobs report (August NFP)", "importance": "high"},
    {"date": "2026-10-02", "region": "US", "event": "US jobs report (September NFP)", "importance": "high"},
]


# ---------------------------------------------------------------------------
# Date parsing helpers
# ---------------------------------------------------------------------------

def _parse_date(value) -> date | None:
    """Best-effort parse of a yfinance date value into a ``date``.

    Handles ``date``/``datetime`` objects, pandas timestamps (via ``.date()``),
    ISO strings, and unix epoch seconds (as used by ``Ticker.info``).
    """
    if value is None:
        return None
    try:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if hasattr(value, "date"):
            return value.date()
        if isinstance(value, (int, float)):
            # yfinance .info exposes some dates as unix epoch seconds.
            if value != value:  # NaN
                return None
            return datetime.utcfromtimestamp(int(value)).date()
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except (ValueError, TypeError, AttributeError, OverflowError, OSError):
        pass
    return None


def _calendar_values(calendar, key: str) -> list:
    """Extract the raw value(s) for *key* from a yfinance calendar.

    yfinance returns either a ``dict`` or a ``DataFrame`` depending on version;
    normalise both into a flat list of raw values.
    """
    if calendar is None:
        return []
    # Dict form: {'Earnings Date': [...], 'Ex-Dividend Date': ..., ...}
    if isinstance(calendar, dict):
        raw = calendar.get(key)
        if raw is None:
            return []
        if isinstance(raw, (list, tuple)):
            return list(raw)
        return [raw]
    # DataFrame form.
    try:
        if hasattr(calendar, "index") and key in getattr(calendar, "index", []):
            raw = calendar.loc[key]
            if hasattr(raw, "__iter__") and not isinstance(raw, str):
                return list(raw)
            return [raw]
    except Exception:
        logger.debug("Could not read '%s' from calendar DataFrame", key)
    return []


# ---------------------------------------------------------------------------
# Blocking yfinance fetch (runs in a worker thread)
# ---------------------------------------------------------------------------

def _sync_fetch_catalysts(ticker_str: str) -> dict:
    """Fetch earnings + ex-dividend dates for one symbol (blocking).

    Returns ``{"earnings_dates": [date, ...], "ex_div_date": date | None}``.
    Best-effort — any part that fails contributes an empty result.
    """
    result: dict = {"earnings_dates": [], "ex_div_date": None}
    ticker = yf.Ticker(ticker_str)

    calendar = None
    try:
        calendar = ticker.calendar
    except Exception:
        calendar = None

    # Earnings dates.
    for raw in _calendar_values(calendar, "Earnings Date"):
        parsed = _parse_date(raw)
        if parsed:
            result["earnings_dates"].append(parsed)

    # Ex-dividend date (best-effort from the calendar first).
    for raw in _calendar_values(calendar, "Ex-Dividend Date"):
        parsed = _parse_date(raw)
        if parsed:
            result["ex_div_date"] = parsed
            break

    # Fallback: .info exposes exDividendDate as a unix timestamp.
    if result["ex_div_date"] is None:
        try:
            info = ticker.info or {}
            result["ex_div_date"] = _parse_date(info.get("exDividendDate"))
        except Exception:
            pass

    return result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def get_economic_calendar(portfolio_id: int, db: AsyncSession) -> dict:
    """Build the unified economic / catalysts feed for a portfolio.

    Merges upcoming earnings + ex-dividend dates for the portfolio's holdings
    with the curated macro events, restricted to a forward window of
    ``_LOOKAHEAD_DAYS`` days. Returns::

        {
            "events": [
                {"date": "2026-07-23", "type": "MACRO", "region": "Eurozone",
                 "title": "ECB rate decision", "importance": "high"},
                {"date": "2026-07-28", "type": "EARNINGS", "region": "India",
                 "title": "Earnings — HDFC Bank", "symbol": "HDFCBANK"},
                ...
            ],
            "range": {"start": "2026-07-17", "end": "2026-10-25"},
        }

    Events are sorted by date (then type). yfinance failures degrade
    gracefully — affected symbols are simply omitted.
    """
    today = date.today()
    window_end = today + timedelta(days=_LOOKAHEAD_DAYS)

    events: list[dict] = []

    # ── 1. Stock catalysts (earnings + ex-dividend) ──────────────────
    result = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio_id)
    )
    holdings = list(result.scalars().all())

    if holdings:
        sem = asyncio.Semaphore(_FETCH_CONCURRENCY)

        async def _fetch(h: Holding) -> tuple[Holding, dict | None]:
            async with sem:
                try:
                    data = await asyncio.wait_for(
                        asyncio.to_thread(
                            _sync_fetch_catalysts,
                            _ticker_symbol(h.stock_symbol, h.exchange),
                        ),
                        timeout=_FETCH_TIMEOUT_S,
                    )
                except Exception:
                    logger.debug(
                        "Economic-calendar fetch failed for %s", h.stock_symbol
                    )
                    return h, None
                return h, data

        fetched = await asyncio.gather(*[_fetch(h) for h in holdings])

        for h, data in fetched:
            if not data:
                continue
            region = _region_for_exchange(h.exchange)

            # Nearest upcoming earnings date within the window.
            upcoming_earnings = sorted(
                d for d in data["earnings_dates"] if today <= d <= window_end
            )
            if upcoming_earnings:
                events.append(
                    {
                        "date": upcoming_earnings[0].isoformat(),
                        "type": EVENT_EARNINGS,
                        "region": region,
                        "title": f"Earnings — {h.stock_name}",
                        "symbol": h.stock_symbol,
                    }
                )

            # Ex-dividend date within the window.
            ex_div = data.get("ex_div_date")
            if ex_div and today <= ex_div <= window_end:
                events.append(
                    {
                        "date": ex_div.isoformat(),
                        "type": EVENT_EX_DIV,
                        "region": region,
                        "title": f"Ex-dividend — {h.stock_name}",
                        "symbol": h.stock_symbol,
                    }
                )

    # ── 2. Curated macro events (within the window) ──────────────────
    for macro in CURATED_MACRO_EVENTS:
        macro_date = _parse_date(macro.get("date"))
        if macro_date is None or not (today <= macro_date <= window_end):
            continue
        events.append(
            {
                "date": macro_date.isoformat(),
                "type": EVENT_MACRO,
                "region": macro.get("region", "Global"),
                "title": macro.get("event", "Macro event"),
                "importance": macro.get("importance", "medium"),
            }
        )

    # ── 3. Sort by date, then by type for stable ordering ────────────
    events.sort(key=lambda e: (e["date"], e["type"]))

    return {
        "events": events,
        "range": {"start": today.isoformat(), "end": window_end.isoformat()},
    }
