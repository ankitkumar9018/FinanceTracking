"""Stock comparison — compare 2-3 stocks side by side."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from dataclasses import dataclass

import math

import yfinance as yf

logger = logging.getLogger(__name__)


def _safe_float_val(val) -> float | None:
    """Convert a value to float, returning None for NaN/Inf/invalid values."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else f
    except (ValueError, TypeError):
        return None


@dataclass
class StockMetrics:
    symbol: str
    name: str
    exchange: str
    current_price: float | None
    day_change_pct: float | None
    week_52_high: float | None
    week_52_low: float | None
    pe_ratio: float | None
    market_cap: float | None
    volume: int | None
    dividend_yield: float | None
    beta: float | None


@dataclass
class StockComparison:
    stocks: list[StockMetrics]
    price_history: dict[str, list[dict]]  # symbol -> [{date, close}]
    period_days: int


def _sync_fetch_stock_data(yf_symbol: str, days: int) -> tuple[dict, list[dict]]:
    """Fetch stock info and price history synchronously (runs in thread)."""
    ticker = yf.Ticker(yf_symbol)
    info = ticker.info or {}

    end = date.today()
    start = end - timedelta(days=days)
    hist = ticker.history(start=start.isoformat(), end=end.isoformat())

    history: list[dict] = []
    if not hist.empty:
        for d, row in hist.iterrows():
            c = _safe_float_val(row["Close"])
            if c is not None:
                history.append({"date": d.date().isoformat(), "close": round(c, 2)})

    return info, history


async def compare_stocks(
    symbols: list[str],
    exchanges: list[str] | None = None,
    days: int = 90,
) -> StockComparison:
    """Compare up to 3 stocks with their key metrics and price history."""
    from app.services.market_data_service import _ticker_symbol

    stocks: list[StockMetrics] = []
    price_history: dict[str, list[dict]] = {}

    for i, symbol in enumerate(symbols[:3]):
        exchange = exchanges[i] if exchanges and i < len(exchanges) else "NSE"
        yf_symbol = _ticker_symbol(symbol, exchange)

        try:
            info, history = await asyncio.wait_for(
                asyncio.to_thread(_sync_fetch_stock_data, yf_symbol, days),
                timeout=10.0,
            )

            current = _safe_float_val(info.get("currentPrice") or info.get("regularMarketPrice"))
            prev_close = _safe_float_val(info.get("previousClose") or info.get("regularMarketPreviousClose"))
            day_change = ((current - prev_close) / prev_close * 100) if current and prev_close else None

            metrics = StockMetrics(
                symbol=symbol,
                name=info.get("shortName") or info.get("longName") or symbol,
                exchange=exchange,
                current_price=current,
                day_change_pct=round(day_change, 2) if day_change else None,
                week_52_high=_safe_float_val(info.get("fiftyTwoWeekHigh")),
                week_52_low=_safe_float_val(info.get("fiftyTwoWeekLow")),
                pe_ratio=_safe_float_val(info.get("trailingPE")),
                market_cap=_safe_float_val(info.get("marketCap")),
                volume=info.get("volume"),
                dividend_yield=_safe_float_val(info.get("dividendYield")),
                beta=_safe_float_val(info.get("beta")),
            )
            stocks.append(metrics)
            price_history[symbol] = history

        except Exception:
            logger.warning("Stock data fetch failed for %s", symbol)
            stocks.append(StockMetrics(
                symbol=symbol, name=symbol, exchange=exchange,
                current_price=None, day_change_pct=None, week_52_high=None,
                week_52_low=None, pe_ratio=None, market_cap=None,
                volume=None, dividend_yield=None, beta=None,
            ))
            price_history[symbol] = []

    return StockComparison(stocks=stocks, price_history=price_history, period_days=days)


# ---------------------------------------------------------------------------
# Peer comparison — compare a stock against curated sector peers
# ---------------------------------------------------------------------------

# There is no free live "sector peers" API, so we ship a modest curated map of
# liquid tickers per sector. Symbols are bare (no exchange suffix); the
# exchange suffix is applied via market_data_service._ticker_symbol.

_NSE_SECTOR_PEERS: dict[str, list[str]] = {
    "Banking": ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK", "INDUSINDBK"],
    "IT": ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM", "LTIM"],
    "Energy": ["RELIANCE", "ONGC", "NTPC", "POWERGRID", "BPCL", "IOC"],
    "FMCG": ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "DABUR", "MARICO"],
    "Auto": ["MARUTI", "TATAMOTORS", "M&M", "BAJAJ-AUTO", "EICHERMOT", "HEROMOTOCO"],
    "Pharma": ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "AUROPHARMA", "LUPIN"],
    "Metals": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "COALINDIA", "JINDALSTEL"],
}

_XETRA_SECTOR_PEERS: dict[str, list[str]] = {
    "Auto": ["VOW3", "BMW", "MBG", "PAH3", "CON"],
    "Technology": ["SAP", "IFX", "SRT3"],
    "Pharma": ["BAYN", "MRK", "FRE", "FME"],
}

# yfinance's `.info["sector"]` uses broad GICS-ish buckets. Map those to our
# curated category names (per market, since the category labels differ).
_YF_SECTOR_TO_NSE: dict[str, str] = {
    "Financial Services": "Banking",
    "Technology": "IT",
    "Energy": "Energy",
    "Utilities": "Energy",
    "Consumer Defensive": "FMCG",
    "Consumer Cyclical": "Auto",
    "Healthcare": "Pharma",
    "Basic Materials": "Metals",
}

_YF_SECTOR_TO_XETRA: dict[str, str] = {
    "Consumer Cyclical": "Auto",
    "Technology": "Technology",
    "Healthcare": "Pharma",
}


@dataclass
class PeerMetrics:
    symbol: str
    name: str
    current_price: float | None
    day_change_pct: float | None
    pe_ratio: float | None
    market_cap: float | None
    dividend_yield: float | None
    week_52_high: float | None
    week_52_low: float | None
    week_52_position: float | None  # 0-100: where price sits in the 52W range
    beta: float | None


@dataclass
class PeerComparison:
    symbol: str
    sector: str | None
    target: PeerMetrics | None
    peers: list[PeerMetrics]
    coverage_note: str


def _sync_fetch_peer_metrics(yf_symbol: str) -> tuple[dict, list[dict]]:
    """Fetch a stock's .info plus a short close history (runs in a thread)."""
    ticker = yf.Ticker(yf_symbol)
    info = ticker.info or {}

    closes: list[dict] = []
    try:
        hist = ticker.history(period="5d")
        if not hist.empty:
            for _, row in hist.iterrows():
                c = _safe_float_val(row["Close"])
                if c is not None:
                    closes.append({"close": round(c, 2)})
    except Exception:
        pass

    return info, closes


def _build_peer_metrics(symbol: str, info: dict, closes: list[dict]) -> PeerMetrics:
    """Assemble a PeerMetrics from yfinance .info with short-history fallbacks."""
    current = _safe_float_val(info.get("currentPrice") or info.get("regularMarketPrice"))
    if current is None and closes:
        current = closes[-1]["close"]

    prev_close = _safe_float_val(
        info.get("previousClose") or info.get("regularMarketPreviousClose")
    )
    if prev_close is None and len(closes) >= 2:
        prev_close = closes[-2]["close"]

    day_change = (
        ((current - prev_close) / prev_close * 100) if current and prev_close else None
    )

    high = _safe_float_val(info.get("fiftyTwoWeekHigh"))
    low = _safe_float_val(info.get("fiftyTwoWeekLow"))
    position: float | None = None
    if current is not None and high is not None and low is not None and high > low:
        position = round((current - low) / (high - low) * 100, 1)

    return PeerMetrics(
        symbol=symbol,
        name=info.get("shortName") or info.get("longName") or symbol,
        current_price=current,
        day_change_pct=round(day_change, 2) if day_change is not None else None,
        pe_ratio=_safe_float_val(info.get("trailingPE")),
        market_cap=_safe_float_val(info.get("marketCap")),
        dividend_yield=_safe_float_val(info.get("dividendYield")),
        week_52_high=high,
        week_52_low=low,
        week_52_position=position,
        beta=_safe_float_val(info.get("beta")),
    )


async def compare_peers(symbol: str, exchange: str = "NSE") -> PeerComparison:
    """Compare a stock against curated sector peers.

    Determines the target's sector via yfinance ``.info`` (falling back to
    direct membership in the curated map) and compares it against the liquid
    peers for that sector. Metrics for the target + each peer are fetched with
    bounded concurrency and a per-symbol timeout; failures are skipped.
    """
    from app.services.market_data_service import _ticker_symbol

    symbol = symbol.strip().upper()
    exchange = exchange.strip().upper()

    if exchange in ("NSE", "BSE"):
        sector_map = _NSE_SECTOR_PEERS
        yf_sector_map = _YF_SECTOR_TO_NSE
        market_label = "NSE"
    elif exchange == "XETRA":
        sector_map = _XETRA_SECTOR_PEERS
        yf_sector_map = _YF_SECTOR_TO_XETRA
        market_label = "XETRA"
    else:
        return PeerComparison(
            symbol=symbol,
            sector=None,
            target=None,
            peers=[],
            coverage_note=(
                f"Peer comparison is only curated for NSE/BSE and XETRA; "
                f"exchange '{exchange}' is not covered."
            ),
        )

    # Fetch the target's info once (also used to determine its sector).
    target_yf = _ticker_symbol(symbol, exchange)
    try:
        info, closes = await asyncio.wait_for(
            asyncio.to_thread(_sync_fetch_peer_metrics, target_yf),
            timeout=10.0,
        )
    except Exception:
        logger.warning("Target metrics fetch failed for %s", symbol)
        info, closes = {}, []

    yf_sector = info.get("sector") or None

    # Resolve the curated category: yfinance sector first, then membership.
    category: str | None = yf_sector_map.get(yf_sector) if yf_sector else None
    if category is None:
        for cat, members in sector_map.items():
            if symbol in members:
                category = cat
                break

    if category is None:
        note = (
            f"No curated peer set for {symbol}"
            + (f" (sector: {yf_sector})" if yf_sector else "")
            + f" on {market_label}. Covered sectors: {', '.join(sector_map)}."
        )
        target_metrics = _build_peer_metrics(symbol, info, closes) if info else None
        return PeerComparison(
            symbol=symbol,
            sector=yf_sector,
            target=target_metrics,
            peers=[],
            coverage_note=note,
        )

    target_metrics = _build_peer_metrics(symbol, info, closes)

    peer_symbols = [p for p in sector_map[category] if p != symbol]

    sem = asyncio.Semaphore(4)

    async def _fetch_peer(psym: str) -> PeerMetrics | None:
        pyf = _ticker_symbol(psym, exchange)
        async with sem:
            try:
                pinfo, pcloses = await asyncio.wait_for(
                    asyncio.to_thread(_sync_fetch_peer_metrics, pyf),
                    timeout=8.0,
                )
            except Exception:
                logger.warning("Peer metrics fetch failed for %s", psym)
                return None
        if not pinfo:
            return None
        return _build_peer_metrics(psym, pinfo, pcloses)

    results = await asyncio.gather(*[_fetch_peer(p) for p in peer_symbols])
    peers = [r for r in results if r is not None]

    coverage_note = (
        f"Comparing {symbol} against {len(peers)} curated {category} peer(s) "
        f"on {market_label}"
        + (f" (yfinance sector: {yf_sector})." if yf_sector else ".")
    )

    return PeerComparison(
        symbol=symbol,
        sector=category,
        target=target_metrics,
        peers=peers,
        coverage_note=coverage_note,
    )
