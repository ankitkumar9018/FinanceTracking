"""Data Freshness Tracking — report staleness of holding price data.

A holding is considered **stale** when its ``last_price_update`` is:
- More than **30 minutes** ago during market hours (9:15-15:30 IST for
  Indian exchanges, 09:00-17:30 CET for XETRA)
- More than **1 day** ago outside market hours or on weekends
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.holding import Holding

logger = logging.getLogger(__name__)

# Timezone definitions — IST is fixed offset, others need DST support
_IST = timezone(timedelta(hours=5, minutes=30))
_CET = ZoneInfo("Europe/Berlin")
_EST = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Market hours helpers
# ---------------------------------------------------------------------------

def _is_market_hours(exchange: str, now_utc: datetime) -> bool:
    """Return True if *now_utc* falls within market trading hours for the
    given exchange.
    """
    exchange_upper = exchange.upper()

    if exchange_upper in ("NSE", "BSE"):
        local = now_utc.astimezone(_IST)
        # NSE/BSE: Mon-Fri 09:15 - 15:30 IST
        if local.weekday() >= 5:  # Saturday / Sunday
            return False
        return (
            local.hour > 9 or (local.hour == 9 and local.minute >= 15)
        ) and (
            local.hour < 15 or (local.hour == 15 and local.minute <= 30)
        )

    if exchange_upper == "XETRA":
        local = now_utc.astimezone(_CET)
        # XETRA: Mon-Fri 09:00 - 17:30 CET
        if local.weekday() >= 5:
            return False
        return (
            local.hour >= 9
        ) and (
            local.hour < 17 or (local.hour == 17 and local.minute <= 30)
        )

    if exchange_upper in ("NYSE", "NASDAQ"):
        local = now_utc.astimezone(_EST)
        # NYSE/NASDAQ: Mon-Fri 09:30 - 16:00 EST
        if local.weekday() >= 5:
            return False
        return (
            local.hour > 9 or (local.hour == 9 and local.minute >= 30)
        ) and (
            local.hour < 16
        )

    # Default: assume market hours Mon-Fri 09:00 - 17:00 UTC
    if now_utc.weekday() >= 5:
        return False
    return 9 <= now_utc.hour < 17


def _is_stale(
    last_updated: datetime | None,
    exchange: str,
    now_utc: datetime,
) -> bool:
    """Determine whether the price data for a holding is stale."""
    if last_updated is None:
        return True

    # Ensure last_updated is timezone-aware (assume UTC if naive)
    if last_updated.tzinfo is None:
        last_updated = last_updated.replace(tzinfo=UTC)

    age = now_utc - last_updated

    if _is_market_hours(exchange, now_utc):
        return age > timedelta(minutes=30)
    else:
        return age > timedelta(days=1)


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

async def get_data_freshness(
    portfolio_id: int,
    db: AsyncSession,
) -> list[dict]:
    """Return freshness info for each holding in the portfolio.

    Each dict contains::

        {
            "holding_id": 42,
            "stock_symbol": "RELIANCE",
            "stock_name": "Reliance Industries",
            "exchange": "NSE",
            "last_updated": "2026-02-05T10:30:00+00:00",
            "age_minutes": 45,
            "is_stale": True,
            "market_open": True,
        }
    """
    result = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio_id)
    )
    holdings = list(result.scalars().all())

    if not holdings:
        return []

    now_utc = datetime.now(UTC)
    freshness: list[dict] = []

    for h in holdings:
        last_updated = h.last_price_update
        market_open = _is_market_hours(h.exchange, now_utc)
        stale = _is_stale(last_updated, h.exchange, now_utc)

        age_minutes: float | None = None
        last_updated_iso: str | None = None
        if last_updated is not None:
            if last_updated.tzinfo is None:
                last_updated = last_updated.replace(tzinfo=UTC)
            age_minutes = round((now_utc - last_updated).total_seconds() / 60, 1)
            last_updated_iso = last_updated.isoformat()

        freshness.append(
            {
                "holding_id": h.id,
                "stock_symbol": h.stock_symbol,
                "stock_name": h.stock_name,
                "exchange": h.exchange,
                "last_updated": last_updated_iso,
                "age_minutes": age_minutes,
                "is_stale": stale,
                "market_open": market_open,
            }
        )

    return freshness
