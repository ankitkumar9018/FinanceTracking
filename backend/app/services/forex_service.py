"""Forex service: exchange rate fetching, caching, and conversion."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.forex_rates import ForexRate

logger = logging.getLogger(__name__)

# How many hours before a cached rate is considered stale
RATE_CACHE_STALE_HOURS = 24

# Exchange -> currency mapping
EXCHANGE_CURRENCY_MAP: dict[str, str] = {
    "NSE": "INR",
    "BSE": "INR",
    "XETRA": "EUR",
    "NYSE": "USD",
    "NASDAQ": "USD",
}


# ---------------------------------------------------------------------------
# Internal: fetch rate from yfinance
# ---------------------------------------------------------------------------

async def _fetch_rate_yfinance(from_currency: str, to_currency: str) -> float:
    """Fetch the latest exchange rate from yfinance.

    Uses the ``{FROM}{TO}=X`` ticker convention (e.g. ``EURINR=X``).

    Returns the last price as a float, or raises ``RuntimeError`` on failure.
    """
    import asyncio

    def _sync_fetch() -> float:
        import yfinance as yf  # type: ignore[import-untyped]

        ticker_symbol = f"{from_currency}{to_currency}=X"
        ticker = yf.Ticker(ticker_symbol)
        try:
            price = ticker.fast_info.last_price
        except Exception:
            # Fallback: try .info dict
            info = ticker.info
            price = info.get("regularMarketPrice") or info.get("previousClose")

        if price is None:
            raise RuntimeError(
                f"Could not fetch rate for {ticker_symbol}"
            )
        return float(price)

    try:
        return await asyncio.wait_for(asyncio.to_thread(_sync_fetch), timeout=10.0)
    except asyncio.TimeoutError:
        logger.error(
            "Timeout fetching forex rate %s/%s from yfinance",
            from_currency,
            to_currency,
        )
        raise RuntimeError(
            f"Timeout fetching exchange rate for {from_currency}/{to_currency}"
        )
    except Exception as exc:
        logger.error(
            "Failed to fetch forex rate %s/%s from yfinance: %s",
            from_currency,
            to_currency,
            exc,
        )
        raise RuntimeError(
            f"Could not fetch exchange rate for {from_currency}/{to_currency}"
        ) from exc


# ---------------------------------------------------------------------------
# Get exchange rate (with DB cache)
# ---------------------------------------------------------------------------

async def get_exchange_rate(
    from_currency: str,
    to_currency: str,
    target_date: date | None,
    db: AsyncSession,
) -> float:
    """Get the exchange rate for a currency pair, using DB cache first.

    If no cached rate exists (or it is stale), fetch from yfinance and cache.

    Parameters
    ----------
    from_currency : str
        Source currency code (e.g. ``"EUR"``).
    to_currency : str
        Target currency code (e.g. ``"INR"``).
    target_date : date | None
        The date for the rate. ``None`` means today.
    db : AsyncSession
        Database session.

    Returns
    -------
    float
        The exchange rate.
    """
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()

    if from_currency == to_currency:
        return 1.0

    lookup_date = target_date or date.today()

    # Check DB cache
    result = await db.execute(
        select(ForexRate).where(
            ForexRate.from_currency == from_currency,
            ForexRate.to_currency == to_currency,
            ForexRate.date == lookup_date,
        )
    )
    cached = result.scalar_one_or_none()

    if cached is not None:
        return float(cached.rate)

    # Not cached — fetch from yfinance
    rate = await _fetch_rate_yfinance(from_currency, to_currency)

    # Store in cache
    forex_record = ForexRate(
        from_currency=from_currency,
        to_currency=to_currency,
        rate=rate,
        date=lookup_date,
        source="yfinance",
    )
    db.add(forex_record)
    await db.flush()

    logger.info(
        "Cached forex rate %s/%s = %.6f for %s",
        from_currency,
        to_currency,
        rate,
        lookup_date,
    )
    return rate


# ---------------------------------------------------------------------------
# Convert amount
# ---------------------------------------------------------------------------

async def convert_amount(
    amount: float,
    from_currency: str,
    to_currency: str,
    db: AsyncSession,
) -> dict:
    """Convert an amount between two currencies.

    Returns a dict with ``original_amount``, ``from_currency``,
    ``to_currency``, ``converted_amount``, ``rate``, ``rate_date``.
    """
    today = date.today()
    rate = await get_exchange_rate(from_currency, to_currency, today, db)
    converted = round(amount * rate, 4)

    return {
        "original_amount": amount,
        "from_currency": from_currency.upper(),
        "to_currency": to_currency.upper(),
        "converted_amount": converted,
        "rate": rate,
        "rate_date": today,
    }


# ---------------------------------------------------------------------------
# Rate history
# ---------------------------------------------------------------------------

async def get_rate_history(
    from_currency: str,
    to_currency: str,
    days: int,
    db: AsyncSession,
) -> list[dict]:
    """Return cached rates for a currency pair over the last *days* days.

    Returns a list of dicts with ``date``, ``rate``, ``source``.
    """
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()
    start_date = date.today() - timedelta(days=days)

    result = await db.execute(
        select(ForexRate)
        .where(
            ForexRate.from_currency == from_currency,
            ForexRate.to_currency == to_currency,
            ForexRate.date >= start_date,
        )
        .order_by(ForexRate.date.desc())
    )
    rates = result.scalars().all()

    return [
        {
            "date": r.date,
            "rate": float(r.rate),
            "source": r.source,
        }
        for r in rates
    ]


# ---------------------------------------------------------------------------
# Utility: infer currency from exchange
# ---------------------------------------------------------------------------

def _infer_currency_from_exchange(exchange: str) -> str:
    """Map an exchange code to its base currency.

    Supported: NSE/BSE -> INR, XETRA -> EUR, NYSE/NASDAQ -> USD.
    Defaults to ``"USD"`` for unknown exchanges.
    """
    return EXCHANGE_CURRENCY_MAP.get(exchange.upper(), "USD")
