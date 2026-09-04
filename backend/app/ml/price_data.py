"""Batched price-history access shared by the ML modules.

Owns the single-query return-series fetch that used to be duplicated twice in
``risk_calculator`` (~50 lines each) while ``portfolio_optimizer`` still ran
one SELECT per holding (N+1).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date

import pandas as pd
from sqlalchemy import select

from app.models.holding import Holding
from app.models.price_history import PriceHistory

logger = logging.getLogger(__name__)

__all__ = ["MAX_RETURN_GAP_DAYS", "fetch_return_series", "gap_filtered_returns"]

# Largest calendar gap between two consecutive stored closes that may still be
# treated as ONE trading day's return. A Friday→Monday step is 3 days and a
# long weekend 4, so 5 keeps every genuine daily observation while rejecting
# the refresh-job holes that are the real problem: ``price_history`` is written
# by an intermittent refresh, so a symbol can easily jump 134 calendar days
# between rows. Every consumer annualises these observations as daily
# (mean * 252, std * sqrt(252) in risk_calculator and portfolio_optimizer), so a
# single multi-month "day" poisons every risk number and every optimiser
# weight derived from it.
MAX_RETURN_GAP_DAYS = 5


def gap_filtered_returns(
    prices: list[tuple[date, float]],
    max_gap_days: int,
) -> pd.Series:
    """Daily pct-change returns, dropping any step that spans a data gap.

    Consecutive ROWS are not necessarily consecutive TRADING DAYS. A return
    computed across a gap is a multi-day (sometimes multi-month) move; keeping
    it and annualising it as a single day is what produced "sell 100% of
    RELIANCE" from one 134-day hole in the stored history.

    Public so a caller that builds its own price list — e.g. the benchmark
    series in ``risk_calculator._fetch_benchmark_returns``, which has the same
    gap problem — can apply the identical guard.
    """
    series = pd.Series(
        [close for _, close in prices],
        index=[d for d, _ in prices],
    )
    returns = series.pct_change()

    dates = [d for d, _ in prices]
    # Position 0 is the always-NaN seed of pct_change and is never kept.
    keep_positions = [
        i
        for i in range(1, len(dates))
        if (dates[i] - dates[i - 1]).days <= max_gap_days
    ]
    return returns.iloc[keep_positions].dropna()


async def fetch_return_series(
    db,  # AsyncSession
    holdings: Sequence[Holding],
    cutoff: date,
    *,
    max_gap_days: int = MAX_RETURN_GAP_DAYS,
) -> dict[tuple[str, str], pd.Series]:
    """Fetch every holding's daily-return series in a SINGLE query.

    Returns a dict keyed by ``(stock_symbol, exchange)`` tuples — so the same
    symbol held on two exchanges (e.g. NSE + BSE) can never collide — mapping
    to a date-indexed :class:`pd.Series` of daily pct-change returns. Holdings
    with fewer than 2 price rows in the window are omitted.

    Returns spanning more than ``max_gap_days`` calendar days are DROPPED (see
    :data:`MAX_RETURN_GAP_DAYS`): stored history has holes, and every caller
    annualises these observations as if each were exactly one trading day.

    Over-fetching across exchanges (``symbol IN (...) AND exchange IN (...)``)
    is harmless: rows are grouped by their exact (symbol, exchange) key and
    only actual-holding keys are returned.
    """
    if not holdings:
        return {}

    wanted = {(h.stock_symbol, h.exchange) for h in holdings}
    price_rows = (
        await db.execute(
            select(
                PriceHistory.stock_symbol,
                PriceHistory.exchange,
                PriceHistory.date,
                PriceHistory.close,
            )
            .where(
                PriceHistory.stock_symbol.in_({sym for sym, _ in wanted}),
                PriceHistory.exchange.in_({exch for _, exch in wanted}),
                PriceHistory.date >= cutoff,
            )
            .order_by(PriceHistory.date.asc())
        )
    ).all()

    prices_by_key: dict[tuple[str, str], list[tuple[date, float]]] = {}
    for r in price_rows:
        key = (r.stock_symbol, r.exchange)
        if key in wanted:
            prices_by_key.setdefault(key, []).append((r.date, float(r.close)))

    returns_by_key: dict[tuple[str, str], pd.Series] = {}
    for key, prices in prices_by_key.items():
        if len(prices) < 2:
            continue
        # Already ordered by date asc from the batched query.
        returns = gap_filtered_returns(prices, max_gap_days)
        dropped = (len(prices) - 1) - len(returns)
        if dropped:
            logger.warning(
                "%s/%s: dropped %d of %d returns spanning a >%d-day gap in "
                "price_history (they would be annualised as single days)",
                key[0],
                key[1],
                dropped,
                len(prices) - 1,
                max_gap_days,
            )
        if not returns.empty:
            returns_by_key[key] = returns
    return returns_by_key
