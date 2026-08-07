"""ESG Scoring Service — fetch ESG data from yfinance and compute portfolio-level scores."""

from __future__ import annotations

import asyncio
import logging

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.portfolio import Portfolio
from app.services.market_data_service import _ticker_symbol
from app.services.valuation import market_value

logger = logging.getLogger(__name__)

# Bound simultaneous yfinance calls so a large portfolio doesn't fan out into
# dozens of concurrent outbound requests.
_MAX_CONCURRENCY = 8


def _default_esg(symbol: str) -> dict:
    """An ``esg_available=False`` record used as a safe fallback."""
    return {
        "symbol": symbol,
        "total_esg": None,
        "environment_score": None,
        "social_score": None,
        "governance_score": None,
        "esg_available": False,
    }


def _sync_fetch_sustainability(ticker_str: str):
    """Fetch yfinance sustainability data synchronously (runs in a thread)."""
    ticker = yf.Ticker(ticker_str)
    return ticker.sustainability


# ---------------------------------------------------------------------------
# Single stock ESG
# ---------------------------------------------------------------------------

async def get_esg_scores(symbols: list[str], exchange: str = "NSE") -> list[dict]:
    """Fetch ESG scores for a list of stock symbols.

    Uses yfinance's ``sustainability`` property which returns a DataFrame
    with ESG total, environment, social, and governance scores.

    Fetches happen concurrently under a bounded semaphore (each call keeps its
    own 10s timeout), so a large portfolio no longer blocks for ~10s per symbol.
    Returns a list of dicts matching StockESGScore schema, in the same order as
    ``symbols``.
    """
    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def _one(symbol: str) -> dict:
        ticker_str = _ticker_symbol(symbol, exchange)
        score_data: dict = _default_esg(symbol)

        try:
            async with semaphore:
                sustainability = await asyncio.wait_for(
                    asyncio.to_thread(_sync_fetch_sustainability, ticker_str),
                    timeout=10.0,
                )

            if sustainability is not None and not sustainability.empty:
                # sustainability is a DataFrame with index like
                # 'totalEsg', 'environmentScore', 'socialScore', 'governanceScore', etc.
                # Values are in the first (and usually only) column
                data = (
                    sustainability.iloc[:, 0]
                    if len(sustainability.columns) > 0
                    else sustainability
                )

                total = _safe_float(data, "totalEsg")
                env = _safe_float(data, "environmentScore")
                social = _safe_float(data, "socialScore")
                gov = _safe_float(data, "governanceScore")

                if total is not None or env is not None:
                    score_data.update({
                        "total_esg": total,
                        "environment_score": env,
                        "social_score": social,
                        "governance_score": gov,
                        "esg_available": True,
                    })
        except Exception:
            logger.warning("ESG data fetch failed for %s", symbol)

        return score_data

    gathered = await asyncio.gather(
        *(_one(s) for s in symbols), return_exceptions=True
    )
    return [
        _default_esg(symbol) if isinstance(res, BaseException) else res
        for symbol, res in zip(symbols, gathered)
    ]


def _safe_float(data, key: str) -> float | None:
    """Safely extract a float value from a pandas Series by key."""
    try:
        if key in data.index:
            val = data[key]
            if val is not None:
                f = float(val)
                if f != f:  # NaN check
                    return None
                return round(f, 2)
    except (ValueError, TypeError, KeyError):
        pass
    return None


# ---------------------------------------------------------------------------
# Portfolio ESG (weighted average)
# ---------------------------------------------------------------------------

def _weighted_average(pairs: list[tuple[float | None, float]]) -> float | None:
    """Weighted mean over ``(value, weight)`` pairs, skipping ``None`` values.

    Each sub-score keeps its own weight denominator: a holding whose provider
    is missing e.g. the governance score contributes to neither the numerator
    nor the denominator for governance — counting it as 0 with full weight
    would bias the portfolio average toward zero.
    """
    numerator = 0.0
    denominator = 0.0
    for value, weight in pairs:
        if value is None:
            continue
        numerator += value * weight
        denominator += weight
    return round(numerator / denominator, 2) if denominator > 0 else None


async def get_portfolio_esg(portfolio_id: int, db: AsyncSession) -> dict:
    """Calculate weighted-average ESG scores for a portfolio.

    Weights are based on holding value (quantity * current_price).
    Holdings without ESG data are excluded from the weighted average, and each
    sub-score (E/S/G) averages only over holdings that actually report it.
    ESG results are keyed by (symbol, exchange) so the same ticker listed on
    two exchanges cannot collide.

    Returns a dict matching PortfolioESGResponse schema.
    """
    result = await db.execute(
        select(Portfolio)
        .options(selectinload(Portfolio.holdings))
        .where(Portfolio.id == portfolio_id)
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise ValueError(f"Portfolio {portfolio_id} not found")

    # Collect symbols and their weights (market value; no live price -> 0)
    holdings_data: list[dict] = []
    for h in portfolio.holdings:
        holdings_data.append({
            "symbol": h.stock_symbol,
            "exchange": h.exchange,
            "value": market_value(h, fallback_to_avg=False) or 0.0,
        })

    # Fetch ESG for all holdings — group by exchange to use proper ticker
    # symbol, and key the lookup by (symbol, exchange) to avoid collisions
    # between identically-named tickers on different exchanges.
    exchange_groups: dict[str, list[str]] = {}
    for hd in holdings_data:
        exchange_groups.setdefault(hd["exchange"], []).append(hd["symbol"])

    esg_lookup: dict[tuple[str, str], dict] = {}
    for exchange, syms in exchange_groups.items():
        scores = await get_esg_scores(syms, exchange)
        for score in scores:
            esg_lookup[(score["symbol"], exchange)] = score

    # Calculate weighted averages (per-sub-score denominators, None skipped)
    total_pairs: list[tuple[float | None, float]] = []
    env_pairs: list[tuple[float | None, float]] = []
    social_pairs: list[tuple[float | None, float]] = []
    gov_pairs: list[tuple[float | None, float]] = []
    with_esg = 0
    without_esg = 0

    stock_scores: list[dict] = []
    for hd in holdings_data:
        esg = esg_lookup.get((hd["symbol"], hd["exchange"]))
        if esg and esg["esg_available"] and esg["total_esg"] is not None:
            weight = hd["value"]
            total_pairs.append((esg["total_esg"], weight))
            env_pairs.append((esg["environment_score"], weight))
            social_pairs.append((esg["social_score"], weight))
            gov_pairs.append((esg["governance_score"], weight))
            with_esg += 1
            stock_scores.append(esg)
        else:
            without_esg += 1
            stock_scores.append(esg or _default_esg(hd["symbol"]))

    avg_total = _weighted_average(total_pairs)
    avg_env = _weighted_average(env_pairs)
    avg_social = _weighted_average(social_pairs)
    avg_gov = _weighted_average(gov_pairs)

    return {
        "portfolio_id": portfolio.id,
        "portfolio_name": portfolio.name,
        "weighted_total_esg": avg_total,
        "weighted_environment": avg_env,
        "weighted_social": avg_social,
        "weighted_governance": avg_gov,
        "holdings_with_esg": with_esg,
        "holdings_without_esg": without_esg,
        "stock_scores": stock_scores,
    }
