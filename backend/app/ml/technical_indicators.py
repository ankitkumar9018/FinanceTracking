"""Technical indicators — MACD, Bollinger Bands, SMA/EMA, Support/Resistance, Fibonacci."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class IndicatorResult:
    """Generic indicator result with dates and values."""
    dates: list[date]
    values: dict[str, list[float | None]]  # name -> values


@dataclass
class MACDResult:
    dates: list[date]
    macd_line: list[float | None]
    signal_line: list[float | None]
    histogram: list[float | None]


@dataclass
class BollingerResult:
    dates: list[date]
    upper_band: list[float | None]
    middle_band: list[float | None]
    lower_band: list[float | None]
    bandwidth: list[float | None]


@dataclass
class SupportResistance:
    support_levels: list[float]
    resistance_levels: list[float]


@dataclass
class FibonacciLevels:
    high: float
    low: float
    levels: dict[str, float]  # "0.236" -> price, "0.382" -> price, etc.


def calculate_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    """Calculate RSI using Wilder smoothing."""
    try:
        import pandas_ta as ta
        result = ta.rsi(closes, length=period)
        if result is not None:
            return result
    except ImportError:
        pass

    # Manual Wilder-smoothed RSI fallback
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_macd(
    closes: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> MACDResult:
    """Calculate MACD (Moving Average Convergence Divergence)."""
    ema_fast = closes.ewm(span=fast, adjust=False).mean()
    ema_slow = closes.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    dates = closes.index.tolist()
    return MACDResult(
        dates=dates,
        macd_line=macd_line.tolist(),
        signal_line=signal_line.tolist(),
        histogram=histogram.tolist(),
    )


def calculate_bollinger_bands(
    closes: pd.Series,
    period: int = 20,
    std_dev: float = 2.0,
) -> BollingerResult:
    """Calculate Bollinger Bands."""
    middle = closes.rolling(window=period).mean()
    std = closes.rolling(window=period).std()
    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)
    bandwidth = ((upper - lower) / middle) * 100

    dates = closes.index.tolist()
    return BollingerResult(
        dates=dates,
        upper_band=upper.tolist(),
        middle_band=middle.tolist(),
        lower_band=lower.tolist(),
        bandwidth=bandwidth.tolist(),
    )


def calculate_sma(closes: pd.Series, period: int = 20) -> pd.Series:
    """Simple Moving Average."""
    return closes.rolling(window=period).mean()


def calculate_ema(closes: pd.Series, period: int = 20) -> pd.Series:
    """Exponential Moving Average."""
    return closes.ewm(span=period, adjust=False).mean()


def find_support_resistance(
    highs: pd.Series,
    lows: pd.Series,
    closes: pd.Series,
    window: int = 5,
    num_levels: int = 3,
) -> SupportResistance:
    """Find support and resistance levels from swing highs/lows."""
    supports = []
    resistances = []

    for i in range(window, len(lows) - window):
        # Swing low (support)
        if lows.iloc[i] == lows.iloc[i - window : i + window + 1].min():
            supports.append(float(lows.iloc[i]))
        # Swing high (resistance)
        if highs.iloc[i] == highs.iloc[i - window : i + window + 1].max():
            resistances.append(float(highs.iloc[i]))

    # Cluster nearby levels and take strongest
    current_price = float(closes.iloc[-1])
    supports = _cluster_levels(supports, current_price)[:num_levels]
    resistances = _cluster_levels(resistances, current_price)[:num_levels]

    return SupportResistance(
        support_levels=sorted(supports),
        resistance_levels=sorted(resistances),
    )


def _cluster_levels(
    levels: list[float], current_price: float, threshold: float = 0.02
) -> list[float]:
    """Cluster nearby price levels within threshold percentage."""
    if not levels:
        return []

    levels = sorted(levels)
    clusters: list[list[float]] = [[levels[0]]]

    for level in levels[1:]:
        if abs(level - clusters[-1][-1]) / clusters[-1][-1] < threshold:
            clusters[-1].append(level)
        else:
            clusters.append([level])

    # Return mean of each cluster, sorted by frequency (most touches first)
    result = [(sum(c) / len(c), len(c)) for c in clusters]
    result.sort(key=lambda x: -x[1])
    return [r[0] for r in result]


def calculate_fibonacci(
    highs: pd.Series,
    lows: pd.Series,
) -> FibonacciLevels:
    """Calculate Fibonacci retracement levels from recent swing high to low."""
    high = float(highs.max())
    low = float(lows.min())
    diff = high - low

    fib_ratios = {
        "0.0": high,
        "0.236": high - (diff * 0.236),
        "0.382": high - (diff * 0.382),
        "0.5": high - (diff * 0.5),
        "0.618": high - (diff * 0.618),
        "0.786": high - (diff * 0.786),
        "1.0": low,
    }

    return FibonacciLevels(high=high, low=low, levels=fib_ratios)


def _nan_to_none(values: list) -> list:
    """Replace NaN values with None for JSON serialization."""
    return [None if (v is not None and pd.isna(v)) else v for v in values]


async def get_all_indicators(
    symbol: str,
    exchange: str,
    db,  # AsyncSession
    days: int = 90,
) -> dict:
    """Fetch price history and compute all indicators."""
    from datetime import timedelta
    from datetime import date as date_type

    from sqlalchemy import select

    from app.models.price_history import PriceHistory

    cutoff = date_type.today() - timedelta(days=days + 50)  # extra for warmup

    result = await db.execute(
        select(PriceHistory)
        .where(
            PriceHistory.stock_symbol == symbol,
            PriceHistory.exchange == exchange,
            PriceHistory.date >= cutoff,
        )
        .order_by(PriceHistory.date.asc())
    )
    rows = result.scalars().all()

    if len(rows) < 30:
        return {"error": "Insufficient price history", "data_points": len(rows)}

    df = pd.DataFrame(
        [
            {
                "date": r.date,
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "volume": int(r.volume),
            }
            for r in rows
        ]
    )
    df.set_index("date", inplace=True)

    closes = df["close"]
    highs = df["high"]
    lows = df["low"]

    # Calculate all indicators
    rsi = calculate_rsi(closes)
    macd = calculate_macd(closes)
    bb = calculate_bollinger_bands(closes)
    sma_20 = calculate_sma(closes, 20)
    sma_50 = calculate_sma(closes, 50)
    ema_20 = calculate_ema(closes, 20)
    ema_50 = calculate_ema(closes, 50)
    sr = find_support_resistance(highs, lows, closes)
    fib = calculate_fibonacci(highs, lows)

    # Trim to requested days
    trim_idx = max(0, len(df) - days)
    dates = [d.isoformat() for d in df.index[trim_idx:]]

    return {
        "symbol": symbol,
        "exchange": exchange,
        "dates": dates,
        "rsi": _nan_to_none(rsi.iloc[trim_idx:].tolist()),
        "macd": {
            "macd_line": _nan_to_none(macd.macd_line[trim_idx:]),
            "signal_line": _nan_to_none(macd.signal_line[trim_idx:]),
            "histogram": _nan_to_none(macd.histogram[trim_idx:]),
        },
        "bollinger_bands": {
            "upper": _nan_to_none(bb.upper_band[trim_idx:]),
            "middle": _nan_to_none(bb.middle_band[trim_idx:]),
            "lower": _nan_to_none(bb.lower_band[trim_idx:]),
            "bandwidth": _nan_to_none(bb.bandwidth[trim_idx:]),
        },
        "sma": {
            "sma_20": _nan_to_none(sma_20.iloc[trim_idx:].tolist()),
            "sma_50": _nan_to_none(sma_50.iloc[trim_idx:].tolist()),
        },
        "ema": {
            "ema_20": _nan_to_none(ema_20.iloc[trim_idx:].tolist()),
            "ema_50": _nan_to_none(ema_50.iloc[trim_idx:].tolist()),
        },
        "support_resistance": {
            "supports": sr.support_levels,
            "resistances": sr.resistance_levels,
        },
        "fibonacci": {
            "high": fib.high,
            "low": fib.low,
            "levels": fib.levels,
        },
    }
