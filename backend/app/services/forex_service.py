"""Forex service: exchange rate fetching, caching, and conversion."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.markets import CURRENCY
from app.models.forex_rates import ForexRate

logger = logging.getLogger(__name__)

# How many hours before a cached (same-day) rate is considered stale and worth
# refetching. Historical closes are immutable and never expire.
#
# This MUST stay below 24: a cache row dated today was, by definition, written
# at some point today, so a 24-hour window could never elapse and the refetch
# branch was unreachable dead code — the first rate of the day (often fetched
# pre-market) stayed frozen until midnight. One hour keeps intraday moves
# visible without hammering yfinance.
RATE_CACHE_STALE_HOURS = 1

# Exchange -> currency mapping. Re-exported alias of the shared
# ``app.core.markets.CURRENCY`` map (kept for existing importers).
EXCHANGE_CURRENCY_MAP: dict[str, str] = CURRENCY


# ---------------------------------------------------------------------------
# Internal: fetch rate from yfinance
# ---------------------------------------------------------------------------

async def _fetch_rate_yfinance(
    from_currency: str,
    to_currency: str,
    target_date: date | None = None,
) -> float:
    """Fetch an exchange rate from yfinance.

    Uses the ``{FROM}{TO}=X`` ticker convention (e.g. ``EURINR=X``).
    With a past ``target_date``, fetches that day's historical close
    (never today's spot — that would silently answer historical
    queries with the wrong rate and poison the per-date cache).

    Returns the rate as a float, or raises ``RuntimeError`` on failure.
    """
    import asyncio

    def _sync_fetch() -> float:
        import yfinance as yf  # type: ignore[import-untyped]

        ticker_symbol = f"{from_currency}{to_currency}=X"
        ticker = yf.Ticker(ticker_symbol)

        if target_date is not None and target_date < date.today():
            # Historical close on/after the target date (markets close on
            # weekends/holidays, so scan a few days forward)
            hist = ticker.history(
                start=target_date.isoformat(),
                end=(target_date + timedelta(days=7)).isoformat(),
            )
            if hist is not None and not hist.empty:
                return float(hist["Close"].iloc[0])
            raise RuntimeError(
                f"No historical rate for {ticker_symbol} on {target_date}"
            )

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
    except TimeoutError:
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
# Staleness helper
# ---------------------------------------------------------------------------

def _is_stale(rate_row: ForexRate) -> bool:
    """Return True if a cached rate is older than ``RATE_CACHE_STALE_HOURS``.

    Compared against the row's own ``created_at`` timestamp (the moment the
    rate was written), NOT against the start of its ``date`` — a same-day row
    is always less than 24 h old, so a 24-hour window would never fire.

    A missing/unknown timestamp is treated as stale so it gets refreshed.
    """
    ts = getattr(rate_row, "created_at", None)
    if ts is None:
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return datetime.now(UTC) - ts > timedelta(hours=RATE_CACHE_STALE_HOURS)


# ---------------------------------------------------------------------------
# Cache write (concurrency-safe)
# ---------------------------------------------------------------------------

async def _select_cached(
    db: AsyncSession,
    from_currency: str,
    to_currency: str,
    lookup_date: date,
) -> ForexRate | None:
    """Read the cache row for one (from, to, date) triple, or None."""
    result = await db.execute(
        select(ForexRate).where(
            ForexRate.from_currency == from_currency,
            ForexRate.to_currency == to_currency,
            ForexRate.date == lookup_date,
        )
    )
    return result.scalar_one_or_none()


async def _cache_rate(
    db: AsyncSession,
    from_currency: str,
    to_currency: str,
    lookup_date: date,
    rate: float,
) -> float:
    """Persist a freshly fetched rate, tolerating a concurrent writer.

    ``get_exchange_rate`` SELECTs the cache, then awaits a yfinance fetch that
    can take seconds, then INSERTs — and ``forex_rates`` has a UNIQUE
    constraint on (from_currency, to_currency, date). On the first
    currency-converting request of the day the dashboard fires several
    converting endpoints in parallel, each on its own session; they all miss
    the cache, all fetch, and the losers used to hit an IntegrityError that
    500'd /forex/rate or silently dropped every EUR asset from a net-worth
    total.

    So: re-read the cache after the network round-trip, and wrap the INSERT in
    a SAVEPOINT so a lost race can be caught and turned back into a read
    instead of poisoning the enclosing transaction's flush.
    """
    winner = await _select_cached(db, from_currency, to_currency, lookup_date)
    if winner is not None:
        logger.debug(
            "Concurrent fetch of %s/%s for %s already cached; reusing it",
            from_currency,
            to_currency,
            lookup_date,
        )
        return float(winner.rate)

    try:
        async with db.begin_nested():
            db.add(
                ForexRate(
                    from_currency=from_currency,
                    to_currency=to_currency,
                    rate=rate,
                    date=lookup_date,
                    source="yfinance",
                )
            )
    except IntegrityError:
        # Another session committed the same (from, to, date) between our
        # re-read and this flush. The savepoint rolled back, so the session is
        # still usable: serve whichever row landed, or the value we fetched if
        # the winner's transaction is not visible to us yet.
        winner = await _select_cached(db, from_currency, to_currency, lookup_date)
        if winner is not None:
            return float(winner.rate)
        logger.warning(
            "Lost the cache-insert race for %s/%s on %s but cannot read the "
            "winning row; serving the freshly fetched rate uncached",
            from_currency,
            to_currency,
            lookup_date,
        )
        return rate

    logger.info(
        "Cached forex rate %s/%s = %.6f for %s",
        from_currency,
        to_currency,
        rate,
        lookup_date,
    )
    return rate


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
    cached = await _select_cached(db, from_currency, to_currency, lookup_date)

    if cached is not None:
        # Historical closes are immutable — always serve them from cache. Only
        # today's rate can go stale intraday: refetch it once the cached row is
        # older than RATE_CACHE_STALE_HOURS (measured from when it was written,
        # so a rate fetched pre-market is refreshed later the same day),
        # otherwise keep serving the cached value.
        if lookup_date < date.today() or not _is_stale(cached):
            return float(cached.rate)

        try:
            fresh_rate = await _fetch_rate_yfinance(
                from_currency, to_currency, lookup_date
            )
        except Exception as exc:
            # Graceful fallback: keep serving the stale cache on refetch failure.
            logger.warning(
                "Refetch of stale %s/%s rate failed (%s); serving cached value",
                from_currency,
                to_currency,
                exc,
            )
            return float(cached.rate)

        cached.rate = fresh_rate
        cached.created_at = datetime.now(UTC).replace(tzinfo=None)
        await db.flush()
        logger.info(
            "Refreshed stale forex rate %s/%s = %.6f for %s",
            from_currency,
            to_currency,
            fresh_rate,
            lookup_date,
        )
        return fresh_rate

    # Not cached — fetch from yfinance (historical close for past dates)
    rate = await _fetch_rate_yfinance(from_currency, to_currency, lookup_date)

    return await _cache_rate(db, from_currency, to_currency, lookup_date, rate)


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
# Per-request rate cache
# ---------------------------------------------------------------------------

class RateCache:
    """Per-request cache of conversion rates into a base currency.

    Memoizes :func:`get_exchange_rate` per source currency so a request that
    converts many values only fetches each pair once. Failed lookups are also
    memoized (per request) so an unavailable pair is not retried per item.

    Promoted from ``net_worth_service._RateCache``; ``portfolio_service`` used
    to carry its own closure-based copy of the same memoization.
    """

    def __init__(self, base_currency: str, db: AsyncSession) -> None:
        self.base = base_currency.upper()
        self.db = db
        self._rates: dict[str, float] = {self.base: 1.0}
        self._failed: set[str] = set()

    async def to_base(
        self, amount: float, from_currency: str | None
    ) -> tuple[float, bool]:
        """Convert *amount* into the base currency.

        Returns ``(value_in_base, converted)``. When no exchange rate is
        available ``converted`` is ``False`` and the amount is returned
        UNconverted (still in its native currency) — callers must then mark the
        item and exclude it from base-currency totals rather than silently
        mixing currencies (which would count e.g. $10k as ₹10k).
        """
        cur = (from_currency or self.base).upper()
        if cur == self.base:
            return amount, True
        if cur not in self._rates and cur not in self._failed:
            try:
                self._rates[cur] = await get_exchange_rate(
                    cur, self.base, None, self.db
                )
            except Exception:
                logger.warning(
                    "No %s->%s rate available; marking value unconverted "
                    "(excluded from the base-currency total)",
                    cur, self.base,
                )
                self._failed.add(cur)
        if cur in self._rates:
            return amount * self._rates[cur], True
        return amount, False
