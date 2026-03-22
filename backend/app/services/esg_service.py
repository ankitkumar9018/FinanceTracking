"""ESG Scoring Service — fetch ESG data from yfinance and compute portfolio-level scores."""

from __future__ import annotations

import asyncio
import logging

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.services.market_data_service import _ticker_symbol

logger = logging.getLogger(__name__)


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

    Returns a list of dicts matching StockESGScore schema.
    """
    results: list[dict] = []

    for symbol in symbols:
        ticker_str = _ticker_symbol(symbol, exchange)
        score_data: dict = {
            "symbol": symbol,
            "total_esg": None,
            "environment_score": None,
            "social_score": None,
            "governance_score": None,
            "esg_available": False,
        }

        try:
            sustainability = await asyncio.wait_for(
                asyncio.to_thread(_sync_fetch_sustainability, ticker_str),
                timeout=10.0,
            )

            if sustainability is not None and not sustainability.empty:
                # sustainability is a DataFrame with index like
                # 'totalEsg', 'environmentScore', 'socialScore', 'governanceScore', etc.
                # Values are in the first (and usually only) column
                data = sustainability.iloc[:, 0] if len(sustainability.columns) > 0 else sustainability

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

        results.append(score_data)

    return results


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

async def get_portfolio_esg(portfolio_id: int, db: AsyncSession) -> dict:
    """Calculate weighted-average ESG scores for a portfolio.

    Weights are based on holding value (quantity * current_price).
    Holdings without ESG data are excluded from the weighted average.

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

    # Collect symbols and their weights (market value)
    holdings_data: list[dict] = []
    for h in portfolio.holdings:
        qty = float(h.cumulative_quantity)
        price = float(h.current_price) if h.current_price is not None else 0.0
        value = qty * price
        holdings_data.append({
            "symbol": h.stock_symbol,
            "exchange": h.exchange,
            "value": value,
        })

    # Fetch ESG for all holdings — group by exchange to use proper ticker symbol
    all_scores: list[dict] = []
    exchange_groups: dict[str, list[str]] = {}
    for hd in holdings_data:
        exchange_groups.setdefault(hd["exchange"], []).append(hd["symbol"])

    for exchange, syms in exchange_groups.items():
        scores = await get_esg_scores(syms, exchange)
        all_scores.extend(scores)

    # Build a lookup: symbol -> esg data
    esg_lookup: dict[str, dict] = {s["symbol"]: s for s in all_scores}

    # Calculate weighted averages
    total_weight = 0.0
    weighted_total = 0.0
    weighted_env = 0.0
    weighted_social = 0.0
    weighted_gov = 0.0
    with_esg = 0
    without_esg = 0

    stock_scores: list[dict] = []
    for hd in holdings_data:
        esg = esg_lookup.get(hd["symbol"])
        if esg and esg["esg_available"] and esg["total_esg"] is not None:
            weight = hd["value"]
            total_weight += weight
            weighted_total += (esg["total_esg"] or 0) * weight
            weighted_env += (esg["environment_score"] or 0) * weight
            weighted_social += (esg["social_score"] or 0) * weight
            weighted_gov += (esg["governance_score"] or 0) * weight
            with_esg += 1
            stock_scores.append(esg)
        else:
            without_esg += 1
            stock_scores.append(esg or {
                "symbol": hd["symbol"],
                "total_esg": None,
                "environment_score": None,
                "social_score": None,
                "governance_score": None,
                "esg_available": False,
            })

    avg_total = round(weighted_total / total_weight, 2) if total_weight > 0 else None
    avg_env = round(weighted_env / total_weight, 2) if total_weight > 0 else None
    avg_social = round(weighted_social / total_weight, 2) if total_weight > 0 else None
    avg_gov = round(weighted_gov / total_weight, 2) if total_weight > 0 else None

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
