"""Batched price-history access shared by the ML modules.

Owns the single-query return-series fetch that used to be duplicated twice in
``risk_calculator`` (~50 lines each) while ``portfolio_optimizer`` still ran
one SELECT per holding (N+1).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import pandas as pd
from sqlalchemy import select

from app.models.holding import Holding
from app.models.price_history import PriceHistory

__all__ = ["fetch_return_series"]


async def fetch_return_series(
    db,  # AsyncSession
    holdings: Sequence[Holding],
    cutoff: date,
) -> dict[tuple[str, str], pd.Series]:
    """Fetch every holding's daily-return series in a SINGLE query.

    Returns a dict keyed by ``(stock_symbol, exchange)`` tuples — so the same
    symbol held on two exchanges (e.g. NSE + BSE) can never collide — mapping
    to a date-indexed :class:`pd.Series` of daily pct-change returns. Holdings
    with fewer than 2 price rows in the window are omitted.

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
        if len(prices) >= 2:
            # Already ordered by date asc from the batched query.
            price_series = pd.Series(
                [close for _, close in prices],
                index=[d for d, _ in prices],
            )
            returns_by_key[key] = price_series.pct_change().dropna()
    return returns_by_key
