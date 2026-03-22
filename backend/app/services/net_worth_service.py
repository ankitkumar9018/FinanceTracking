"""Multi-Asset Net Worth Service — aggregate net worth across stocks, crypto, gold, FD, bonds, real estate."""

from __future__ import annotations

import asyncio
import logging

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.asset import Asset
from app.models.holding import Holding
from app.models.portfolio import Portfolio

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Live price helpers for non-stock assets
# ---------------------------------------------------------------------------

def _sync_fetch_price(symbol: str) -> float | None:
    """Synchronous helper to fetch a price via yfinance (runs in a thread)."""
    try:
        ticker = yf.Ticker(symbol)
        return float(ticker.fast_info.last_price)
    except Exception:
        try:
            ticker = yf.Ticker(symbol)
            return float(ticker.info.get("regularMarketPrice", 0)) or None
        except Exception:
            return None


async def _fetch_crypto_price(symbol: str) -> float | None:
    """Fetch current crypto price via yfinance (e.g. BTC-USD, ETH-USD)."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(_sync_fetch_price, symbol), timeout=10.0)
    except Exception:
        logger.warning("Failed to fetch crypto price for %s", symbol)
        return None


async def _fetch_gold_price(symbol: str = "GC=F") -> float | None:
    """Fetch current gold price via yfinance.

    Default uses gold futures (GC=F). For India, use GOLDBEES.NS.
    """
    try:
        return await asyncio.wait_for(asyncio.to_thread(_sync_fetch_price, symbol), timeout=10.0)
    except Exception:
        logger.warning("Failed to fetch gold price for %s", symbol)
        return None


# ---------------------------------------------------------------------------
# Net worth calculation
# ---------------------------------------------------------------------------

async def get_net_worth(user_id: int, db: AsyncSession) -> dict:
    """Calculate total net worth with breakdown by asset type.

    Includes:
    - STOCK: summed from all portfolio holdings (quantity * current_price)
    - CRYPTO: live prices from yfinance
    - GOLD: live price from yfinance
    - FIXED_DEPOSIT: stored value (principal + accrued interest)
    - BOND: stored value
    - REAL_ESTATE: stored value

    Returns a dict matching NetWorthResponse schema.
    """
    breakdown: list[dict] = []

    # ── 1. Stocks from existing portfolio holdings ─────────────────
    stock_value = 0.0
    stock_items: list[dict] = []

    result = await db.execute(
        select(Portfolio)
        .options(selectinload(Portfolio.holdings))
        .where(Portfolio.user_id == user_id)
    )
    portfolios = result.scalars().all()

    for portfolio in portfolios:
        for h in portfolio.holdings:
            qty = float(h.cumulative_quantity)
            avg = float(h.average_price)
            price = float(h.current_price) if h.current_price is not None else avg
            value = qty * price
            stock_value += value
            stock_items.append({
                "id": h.id,
                "asset_type": "STOCK",
                "name": h.stock_name,
                "symbol": h.stock_symbol,
                "exchange": h.exchange,
                "quantity": qty,
                "purchase_price": round(qty * avg, 2),
                "current_price": price,
                "current_value": round(value, 2),
                "value": round(value, 2),
                "currency": portfolio.currency,
                "portfolio": portfolio.name,
            })

    if stock_items:
        breakdown.append({
            "asset_type": "STOCK",
            "total_value": round(stock_value, 2),
            "count": len(stock_items),
            "items": stock_items,
        })

    # ── 2. Non-stock assets from assets table ──────────────────────
    asset_result = await db.execute(
        select(Asset).where(Asset.user_id == user_id)
    )
    assets = asset_result.scalars().all()

    # Group by asset type
    asset_groups: dict[str, list[Asset]] = {}
    for asset in assets:
        asset_groups.setdefault(asset.asset_type, []).append(asset)

    for asset_type, asset_list in asset_groups.items():
        type_value = 0.0
        type_items: list[dict] = []

        for asset in asset_list:
            value = float(asset.current_value)

            # For crypto and gold with a symbol, try to fetch live price
            if asset_type == "CRYPTO" and asset.symbol:
                live_price = await _fetch_crypto_price(asset.symbol)
                if live_price is not None and float(asset.quantity) > 0:
                    value = float(asset.quantity) * live_price
            elif asset_type == "GOLD" and asset.symbol:
                live_price = await _fetch_gold_price(asset.symbol)
                if live_price is not None and float(asset.quantity) > 0:
                    value = float(asset.quantity) * live_price

            type_value += value
            item_data: dict = {
                "id": asset.id,
                "asset_type": asset_type,
                "name": asset.name,
                "symbol": asset.symbol,
                "quantity": float(asset.quantity),
                "purchase_price": float(asset.purchase_price),
                "current_value": round(value, 2),
                "currency": asset.currency,
            }
            if asset.interest_rate is not None:
                item_data["interest_rate"] = asset.interest_rate
            if asset.maturity_date is not None:
                item_data["maturity_date"] = asset.maturity_date.isoformat()
            type_items.append(item_data)

        breakdown.append({
            "asset_type": asset_type,
            "total_value": round(type_value, 2),
            "count": len(type_items),
            "items": type_items,
        })

    total_net_worth = sum(b["total_value"] for b in breakdown)

    return {
        "total_net_worth": round(total_net_worth, 2),
        "breakdown": breakdown,
        "currency": "INR",  # default; can be made user-specific
    }
