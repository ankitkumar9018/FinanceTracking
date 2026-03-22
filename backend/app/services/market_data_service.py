"""Market data service: fetching prices via yfinance, RSI calculation, bulk refresh."""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import UTC, datetime

import pandas as pd
import yfinance as yf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.price_history import PriceHistory
from app.services.alert_service import determine_action_needed

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exchange suffix mapping
# ---------------------------------------------------------------------------

_EXCHANGE_SUFFIX: dict[str, str] = {
    "NSE": ".NS",
    "BSE": ".BO",
    "XETRA": ".DE",
    "NYSE": "",
    "NASDAQ": "",
}


def _ticker_symbol(symbol: str, exchange: str) -> str:
    """Return the yfinance ticker string for a given symbol and exchange."""
    suffix = _EXCHANGE_SUFFIX.get(exchange.upper(), "")
    return f"{symbol}{suffix}"


def _safe_float(val) -> float | None:
    """Convert a value to float, returning None for NaN/Inf/invalid values."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else f
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Current price
# ---------------------------------------------------------------------------

async def fetch_current_price(symbol: str, exchange: str = "NSE") -> dict:
    """Fetch the latest quote for a stock via yfinance.

    Returns a dict with keys: current_price, open, high, low, volume,
    previous_close, change, change_percent.
    """
    ticker_str = _ticker_symbol(symbol, exchange)

    def _fetch_sync() -> dict:
        ticker = yf.Ticker(ticker_str)
        try:
            info = ticker.fast_info
            cp = _safe_float(info.last_price)
            pc = _safe_float(info.previous_close) if hasattr(info, "previous_close") else None
            op = _safe_float(info.open) if hasattr(info, "open") else None
            dh = _safe_float(info.day_high) if hasattr(info, "day_high") else None
            dl = _safe_float(info.day_low) if hasattr(info, "day_low") else None
        except Exception:
            info = ticker.info
            raw_cp = info.get("currentPrice") or info.get("regularMarketPrice")
            cp = _safe_float(raw_cp) if raw_cp else None
            pc = _safe_float(info.get("previousClose"))
            op = _safe_float(info.get("open") or info.get("regularMarketOpen"))
            dh = _safe_float(info.get("dayHigh") or info.get("regularMarketDayHigh"))
            dl = _safe_float(info.get("dayLow") or info.get("regularMarketDayLow"))

        vol: int | None = None
        try:
            hist = ticker.history(period="1d")
            if not hist.empty:
                vol = int(hist["Volume"].iloc[-1])
        except Exception:
            pass

        return {"cp": cp, "pc": pc, "op": op, "dh": dh, "dl": dl, "vol": vol}

    try:
        data = await asyncio.wait_for(asyncio.to_thread(_fetch_sync), timeout=15.0)
    except asyncio.TimeoutError:
        logger.warning("yfinance timeout fetching %s", ticker_str)
        return {
            "symbol": symbol, "exchange": exchange, "current_price": None,
            "open": None, "high": None, "low": None, "volume": None,
            "previous_close": None, "change": None, "change_percent": None,
        }

    current_price = data["cp"]
    prev_close = data["pc"]
    open_price = data["op"]
    day_high = data["dh"]
    day_low = data["dl"]
    volume = data["vol"]

    change: float | None = None
    change_pct: float | None = None
    if prev_close and current_price:
        change = round(current_price - prev_close, 4)
        change_pct = round((change / prev_close) * 100, 2)

    return {
        "symbol": symbol,
        "exchange": exchange,
        "current_price": current_price,
        "open": open_price,
        "high": day_high,
        "low": day_low,
        "volume": volume,
        "previous_close": prev_close,
        "change": change,
        "change_percent": change_pct,
    }


# ---------------------------------------------------------------------------
# Historical OHLCV data
# ---------------------------------------------------------------------------

async def fetch_historical_data(
    symbol: str,
    exchange: str = "NSE",
    days: int = 30,
) -> list[dict]:
    """Fetch OHLCV history for the past *days* trading days.

    Returns a list of dicts with keys: date, open, high, low, close, volume.
    """
    ticker_str = _ticker_symbol(symbol, exchange)

    # Map days to a yfinance period string
    if days <= 5:
        period = "5d"
    elif days <= 30:
        period = "1mo"
    elif days <= 90:
        period = "3mo"
    elif days <= 180:
        period = "6mo"
    elif days <= 365:
        period = "1y"
    else:
        period = "2y"

    def _fetch_hist_sync() -> pd.DataFrame:
        ticker = yf.Ticker(ticker_str)
        return ticker.history(period=period)

    try:
        hist: pd.DataFrame = await asyncio.wait_for(
            asyncio.to_thread(_fetch_hist_sync), timeout=15.0
        )
    except asyncio.TimeoutError:
        logger.warning("yfinance timeout fetching history for %s", ticker_str)
        return []

    if hist.empty:
        return []

    # Trim to requested number of rows
    hist = hist.tail(days)

    rows: list[dict] = []
    for idx, row in hist.iterrows():
        o = _safe_float(row["Open"])
        h = _safe_float(row["High"])
        lo = _safe_float(row["Low"])
        c = _safe_float(row["Close"])
        # Skip rows where essential price data is missing (NaN from yfinance)
        if c is None:
            continue
        rows.append(
            {
                "date": idx.date() if hasattr(idx, "date") else idx,
                "open": round(o, 4) if o is not None else round(c, 4),
                "high": round(h, 4) if h is not None else round(c, 4),
                "low": round(lo, 4) if lo is not None else round(c, 4),
                "close": round(c, 4),
                "volume": int(row["Volume"]) if pd.notna(row["Volume"]) else 0,
            }
        )

    return rows


# ---------------------------------------------------------------------------
# RSI calculation
# ---------------------------------------------------------------------------

def calculate_rsi(close_prices: pd.Series, period: int = 14) -> pd.Series:
    """Calculate RSI (Relative Strength Index) using pandas_ta if available,
    with a manual fallback.

    Parameters
    ----------
    close_prices : pd.Series
        Series of close prices indexed by date.
    period : int
        RSI look-back period (default 14).

    Returns
    -------
    pd.Series
        RSI values (NaN where insufficient data).
    """
    try:
        import pandas_ta as ta

        rsi = ta.rsi(close_prices, length=period)
        if rsi is not None:
            return rsi
    except ImportError:
        pass

    # Manual Wilder-smoothed RSI
    delta = close_prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()

    # Wilder smoothing after the first SMA
    for i in range(period, len(avg_gain)):
        avg_gain.iloc[i] = (avg_gain.iloc[i - 1] * (period - 1) + gain.iloc[i]) / period
        avg_loss.iloc[i] = (avg_loss.iloc[i - 1] * (period - 1) + loss.iloc[i]) / period

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


async def fetch_rsi_series(
    symbol: str,
    exchange: str = "NSE",
    days: int = 30,
    period: int = 14,
) -> list[dict]:
    """Fetch historical data and compute an RSI time series.

    Returns list of {date, close, rsi}.
    """
    # Wilder smoothing needs ~4x the period to stabilize
    fetch_days = days + period * 4 + 10
    raw = await fetch_historical_data(symbol, exchange, fetch_days)
    if not raw:
        return []

    df = pd.DataFrame(raw)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    rsi_series = calculate_rsi(df["close"], period=period)
    df["rsi"] = rsi_series

    # Trim to requested number of days
    df = df.tail(days)

    rows: list[dict] = []
    for _, row in df.iterrows():
        rsi_val = round(float(row["rsi"]), 2) if pd.notna(row["rsi"]) else None
        rows.append(
            {
                "date": row["date"].date() if hasattr(row["date"], "date") else row["date"],
                "close": round(float(row["close"]), 4),
                "rsi": rsi_val,
            }
        )

    return rows


# ---------------------------------------------------------------------------
# Bulk price refresh
# ---------------------------------------------------------------------------

async def _fetch_holding_data(symbol: str, exchange: str) -> dict:
    """Fetch price, RSI, and OHLCV for a single holding in parallel-safe way.

    Returns a dict with all fetched data (no DB writes).
    """
    data: dict = {"symbol": symbol, "exchange": exchange, "ok": False}
    try:
        quote = await fetch_current_price(symbol, exchange)
        data["quote"] = quote

        # Compute RSI from recent history
        rsi_val = None
        try:
            rsi_data = await fetch_rsi_series(symbol, exchange, days=1, period=14)
            if rsi_data:
                rsi_val = rsi_data[-1]["rsi"]
        except Exception:
            logger.warning("RSI fetch failed for %s", symbol)
        data["rsi"] = rsi_val

        # Fetch OHLCV for price history
        try:
            ohlcv = await fetch_historical_data(symbol, exchange, days=1)
            data["ohlcv"] = ohlcv
        except Exception:
            data["ohlcv"] = []

        data["ok"] = True
    except Exception:
        logger.exception("Price refresh failed for %s", symbol)
    return data


async def refresh_all_prices(
    db: AsyncSession, *, user_id: int | None = None
) -> dict:
    """Update current_price, current_rsi, and action_needed for holdings.

    If *user_id* is given, only refresh that user's holdings (via portfolio).
    If *user_id* is ``None``, refresh all holdings (background task mode).

    Fetches external data for all holdings in parallel, then writes to DB
    sequentially (async sessions are not safe for concurrent writes).

    Returns a summary dict with counts of updated / failed holdings.
    """
    stmt = select(Holding)
    if user_id is not None:
        stmt = stmt.join(Portfolio, Holding.portfolio_id == Portfolio.id).where(
            Portfolio.user_id == user_id
        )
    result = await db.execute(stmt)
    holdings = list(result.scalars().all())

    if not holdings:
        return {"updated": 0, "failed": 0, "total": 0}

    # ── Parallel fetch: all external API calls run concurrently ──────
    fetch_tasks = [
        _fetch_holding_data(h.stock_symbol, h.exchange) for h in holdings
    ]
    fetch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

    # ── Sequential DB writes ─────────────────────────────────────────
    updated = 0
    failed = 0
    today = datetime.now(UTC).date()

    for holding, fetch_result in zip(holdings, fetch_results):
        if isinstance(fetch_result, Exception) or not isinstance(fetch_result, dict) or not fetch_result.get("ok"):
            failed += 1
            continue

        try:
            quote = fetch_result["quote"]
            holding.current_price = quote["current_price"]
            holding.last_price_update = datetime.now(UTC)
            holding.current_rsi = fetch_result.get("rsi")

            holding.action_needed = determine_action_needed(
                holding.current_price, holding
            )

            # Store price in history table
            hist_result = await db.execute(
                select(PriceHistory).where(
                    PriceHistory.stock_symbol == holding.stock_symbol,
                    PriceHistory.exchange == holding.exchange,
                    PriceHistory.date == today,
                )
            )
            existing = hist_result.scalar_one_or_none()
            if existing is None:
                ohlcv = fetch_result.get("ohlcv", [])
                if ohlcv:
                    latest = ohlcv[-1]
                    ph = PriceHistory(
                        stock_symbol=holding.stock_symbol,
                        exchange=holding.exchange,
                        date=today,
                        open=latest["open"],
                        high=latest["high"],
                        low=latest["low"],
                        close=latest["close"],
                        volume=latest["volume"],
                        rsi_14=holding.current_rsi,
                    )
                    db.add(ph)

            updated += 1
        except Exception:
            logger.exception("DB update failed for %s", holding.stock_symbol)
            failed += 1

    await db.flush()

    return {"updated": updated, "failed": failed, "total": len(holdings)}
