"""Market data endpoints: quotes, history, bulk refresh."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.market_data import HistoryResponse, QuoteResponse
from app.services.market_data_service import (
    _EXCHANGE_SUFFIX,
    _ticker_symbol,
    fetch_current_price,
    fetch_historical_data,
    refresh_all_prices,
)
from app.services.screener_service import ScreenerFilters, screen_stocks

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/quote/{symbol}", response_model=QuoteResponse)
async def get_quote(
    symbol: str,
    exchange: str = Query(default="NSE", description="Exchange: NSE, BSE, XETRA, etc."),
    user: User = Depends(get_current_user),
) -> dict:
    """Get the current quote for a stock symbol."""
    try:
        quote = await fetch_current_price(symbol.upper().strip(), exchange.upper().strip())
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch quote for {symbol}: {exc}",
        )

    if not quote.get("current_price"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No price data found for {symbol} on {exchange}",
        )

    return quote


@router.get("/history/{symbol}", response_model=HistoryResponse)
async def get_history(
    symbol: str,
    exchange: str = Query(default="NSE", description="Exchange: NSE, BSE, XETRA, etc."),
    days: int = Query(default=30, ge=1, le=730, description="Number of trading days"),
    user: User = Depends(get_current_user),
) -> dict:
    """Get OHLCV history for a stock symbol."""
    try:
        data = await fetch_historical_data(
            symbol.upper().strip(),
            exchange.upper().strip(),
            days,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch history for {symbol}: {exc}",
        )

    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No historical data found for {symbol} on {exchange}",
        )

    return {
        "symbol": symbol.upper().strip(),
        "exchange": exchange.upper().strip(),
        "data": data,
    }


@router.post("/refresh")
async def refresh_prices(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Trigger a price refresh for all holdings.

    Updates current_price, current_rsi, and action_needed for every holding
    in the database. This may take several seconds depending on the number
    of holdings.
    """
    try:
        summary = await refresh_all_prices(db, user_id=user.id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Price refresh failed: {exc}",
        )

    return {
        "status": "completed",
        **summary,
    }


@router.get("/search")
async def search_stocks(
    q: str = Query(..., min_length=1, max_length=50),
    exchange: str = Query("NSE"),
    limit: int = Query(10, ge=1, le=50),
    user: User = Depends(get_current_user),
):
    """Search for stocks by name or symbol using Yahoo Finance search API."""
    import httpx
    import yfinance as yf

    results = []
    query = q.strip()

    try:
        # Use Yahoo Finance search API for better name/symbol search
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://query2.finance.yahoo.com/v1/finance/search",
                params={
                    "q": query,
                    "quotesCount": limit,
                    "newsCount": 0,
                    "enableFuzzyQuery": True,
                    "quotesQueryId": "tss_match_phrase_query",
                },
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=5.0,
            )
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except (ValueError, KeyError):
                    data = {}
                quotes = data.get("quotes", [])

                # Map exchange names
                exchange_map = {"NSE": ".NS", "BSE": ".BO", "XETRA": ".DE"}
                exchange_suffix = exchange_map.get(exchange.upper(), "")

                for quote in quotes:
                    symbol = quote.get("symbol", "")
                    # Filter by exchange if specified
                    if exchange_suffix:
                        if not symbol.endswith(exchange_suffix):
                            continue
                        # Remove suffix for display
                        symbol = symbol.replace(exchange_suffix, "")

                    results.append({
                        "symbol": symbol,
                        "name": quote.get("shortname") or quote.get("longname") or symbol,
                        "exchange": exchange.upper(),
                        "type": quote.get("quoteType", "EQUITY"),
                    })

                    if len(results) >= limit:
                        break
    except Exception:
        logger.debug("Stock search API failed for query=%s", q, exc_info=True)

    # Fallback: if no results from search API, try direct symbol lookup
    if not results:
        try:
            symbol = _ticker_symbol(query.upper(), exchange.upper())

            def _lookup_info() -> dict:
                return yf.Ticker(symbol).info or {}

            # ticker.info issues several blocking HTTP requests — keep it off
            # the event loop and bound it so autocomplete can't hang the server
            info = await asyncio.wait_for(asyncio.to_thread(_lookup_info), timeout=10.0)
            if info and info.get("symbol"):
                results.append({
                    "symbol": query.upper(),
                    "name": info.get("shortName") or info.get("longName") or query.upper(),
                    "exchange": exchange.upper(),
                    "type": info.get("quoteType", "EQUITY"),
                })
        except Exception:
            logger.debug("Direct symbol lookup failed for %s", query, exc_info=True)

    return {"results": results[:limit], "query": q, "exchange": exchange}


@router.get("/screener")
async def run_screener(
    exchange: str = Query("NSE", description="Exchange for the default universe: NSE, XETRA"),
    symbols: str | None = Query(
        None,
        description="Optional comma-separated symbols to add to the curated universe",
    ),
    market_cap_min: float | None = Query(None, ge=0),
    market_cap_max: float | None = Query(None, ge=0),
    pe_min: float | None = Query(None),
    pe_max: float | None = Query(None),
    dividend_yield_min: float | None = Query(None, ge=0, description="Minimum dividend yield (%)"),
    price_min: float | None = Query(None, ge=0),
    price_max: float | None = Query(None, ge=0),
    sector: str | None = Query(None, max_length=50, description="Sector substring match"),
    rsi_min: float | None = Query(None, ge=0, le=100),
    rsi_max: float | None = Query(None, ge=0, le=100),
    week52_min: float | None = Query(None, ge=0, le=100, description="Min 52-week range position (%)"),
    week52_max: float | None = Query(None, ge=0, le=100, description="Max 52-week range position (%)"),
    day_change_min: float | None = Query(None),
    day_change_max: float | None = Query(None),
    user: User = Depends(get_current_user),
) -> dict:
    """Screen a curated, liquid universe of stocks against the given filters.

    Screens a modest per-exchange watchlist (plus any explicit ``symbols``),
    not the whole market — this keeps every scan fast and predictable without a
    paid screener API. Each symbol is fetched from yfinance with bounded
    concurrency and a per-symbol timeout; unreachable symbols are skipped.
    """
    symbol_list = (
        [s.strip() for s in symbols.split(",") if s.strip()] if symbols else None
    )
    filters = ScreenerFilters(
        market_cap_min=market_cap_min,
        market_cap_max=market_cap_max,
        pe_min=pe_min,
        pe_max=pe_max,
        dividend_yield_min=dividend_yield_min,
        price_min=price_min,
        price_max=price_max,
        sector=sector,
        rsi_min=rsi_min,
        rsi_max=rsi_max,
        week52_min=week52_min,
        week52_max=week52_max,
        day_change_min=day_change_min,
        day_change_max=day_change_max,
    )

    try:
        return await screen_stocks(
            filters, exchange=exchange.upper().strip(), symbols=symbol_list
        )
    except Exception as exc:
        logger.exception("Screener failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Screener failed: {exc}",
        )
