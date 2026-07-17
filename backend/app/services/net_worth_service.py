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
from app.models.user import User
from app.services import forex_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Live price helpers for non-stock assets
# ---------------------------------------------------------------------------

def _sync_fetch_price(symbol: str) -> tuple[float, str | None] | None:
    """Fetch a price via yfinance (runs in a thread).

    Returns ``(price, quote_currency)`` — the currency the price is
    denominated in (e.g. USD for BTC-USD/GC=F, INR for GOLDBEES.NS) —
    or ``None`` if the price could not be fetched.
    """
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        return float(info.last_price), getattr(info, "currency", None)
    except Exception:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            price = float(info.get("regularMarketPrice", 0)) or None
            if price is None:
                return None
            return price, info.get("currency")
        except Exception:
            return None


async def _fetch_live_price(symbol: str) -> tuple[float, str | None] | None:
    """Fetch current price + quote currency via yfinance (crypto, gold, …)."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(_sync_fetch_price, symbol), timeout=10.0)
    except Exception:
        logger.warning("Failed to fetch live price for %s", symbol)
        return None


class _RateCache:
    """Per-request cache of conversion rates into the base currency."""

    def __init__(self, base_currency: str, db: AsyncSession) -> None:
        self.base = base_currency.upper()
        self.db = db
        self._rates: dict[str, float] = {self.base: 1.0}

    async def to_base(self, amount: float, from_currency: str | None) -> float:
        cur = (from_currency or self.base).upper()
        if cur not in self._rates:
            try:
                self._rates[cur] = await forex_service.get_exchange_rate(
                    cur, self.base, None, self.db
                )
            except Exception:
                logger.warning(
                    "No %s->%s rate available; using 1.0 (net worth may mix currencies)",
                    cur, self.base,
                )
                self._rates[cur] = 1.0
        return amount * self._rates[cur]


# ---------------------------------------------------------------------------
# Net worth calculation
# ---------------------------------------------------------------------------

async def get_net_worth(
    user_id: int,
    db: AsyncSession,
    display_currency: str | None = None,
) -> dict:
    """Calculate total net worth with breakdown by asset type.

    Includes:
    - STOCK: summed from all portfolio holdings (quantity * current_price)
    - CRYPTO: live prices from yfinance
    - GOLD: live price from yfinance
    - FIXED_DEPOSIT: stored value (principal + accrued interest)
    - BOND: stored value
    - REAL_ESTATE: stored value

    All aggregate figures (breakdown ``total_value`` and ``total_net_worth``)
    are converted into the base currency; per-item values stay in their native
    currency (each item carries its own ``currency`` field) with a
    ``value_in_base`` key added.

    The base currency defaults to the user's stored ``preferred_currency``.
    ``display_currency`` is an optional, additive override: when provided it is
    used as the base currency for this response only (the returned ``currency``
    field reflects it) — the user's stored preference is never changed.

    Returns a dict matching NetWorthResponse schema.
    """
    breakdown: list[dict] = []

    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    base_currency = (
        display_currency
        or (user.preferred_currency if user else None)
        or "INR"
    )
    rates = _RateCache(base_currency, db)

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
            holding_currency = h.currency or portfolio.currency
            value_base = await rates.to_base(value, holding_currency)
            stock_value += value_base
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
                "value_in_base": round(value_base, 2),
                "currency": holding_currency,
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
            value_currency = asset.currency

            # For crypto and gold with a symbol, try to fetch live price.
            # The live price is denominated in the symbol's quote currency
            # (USD for BTC-USD/GC=F, INR for GOLDBEES.NS, …), which may
            # differ from the currency stored on the asset.
            if asset_type in ("CRYPTO", "GOLD") and asset.symbol:
                live = await _fetch_live_price(asset.symbol)
                if live is not None and float(asset.quantity) > 0:
                    live_price, quote_currency = live
                    value = float(asset.quantity) * live_price
                    value_currency = quote_currency or asset.currency

            value_base = await rates.to_base(value, value_currency)
            type_value += value_base
            item_data: dict = {
                "id": asset.id,
                "asset_type": asset_type,
                "name": asset.name,
                "symbol": asset.symbol,
                "quantity": float(asset.quantity),
                "purchase_price": float(asset.purchase_price),
                "current_value": round(value, 2),
                "value_in_base": round(value_base, 2),
                "currency": value_currency,
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
        "currency": base_currency,
    }
