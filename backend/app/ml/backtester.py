"""Backtesting engine — run trading strategies against historical price data."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

try:
    import pandas_ta as ta  # noqa: F401

    HAS_PANDAS_TA = True
except ImportError:
    HAS_PANDAS_TA = False

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.price_history import PriceHistory

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE_ANNUAL = 0.07


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class BacktestResult:
    """Results of a backtest run."""

    total_return: float
    annualized_return: float
    sharpe_ratio: float | None
    max_drawdown: float
    total_trades: int
    win_rate: float
    trades: list[dict] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)


@dataclass
class StrategyConfig:
    """Configuration for a strategy."""

    name: str
    params: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Strategy functions
# ---------------------------------------------------------------------------


def rsi_strategy(
    prices_df: pd.DataFrame,
    buy_threshold: int = 30,
    sell_threshold: int = 70,
) -> pd.Series:
    """RSI-based strategy: buy when RSI < buy_threshold, sell when RSI > sell_threshold.

    Returns a signal series: 1 = buy, -1 = sell, 0 = hold.
    """
    signals = pd.Series(0, index=prices_df.index)

    if "rsi_14" in prices_df.columns:
        rsi = prices_df["rsi_14"]
    elif HAS_PANDAS_TA and "close" in prices_df.columns:
        rsi = prices_df.ta.rsi(length=14)
    else:
        # Fallback: compute RSI manually
        delta = prices_df["close"].diff()
        gain = delta.where(delta > 0, 0.0).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))

    if rsi is None:
        return signals

    signals[rsi < buy_threshold] = 1
    signals[rsi > sell_threshold] = -1
    return signals


def sma_crossover_strategy(
    prices_df: pd.DataFrame,
    short_window: int = 20,
    long_window: int = 50,
) -> pd.Series:
    """SMA crossover: buy when short SMA crosses above long SMA, sell on cross below.

    Returns a signal series: 1 = buy, -1 = sell, 0 = hold.
    """
    signals = pd.Series(0, index=prices_df.index)
    close = prices_df["close"]

    short_sma = close.rolling(window=short_window).mean()
    long_sma = close.rolling(window=long_window).mean()

    # Crossover detection
    prev_short = short_sma.shift(1)
    prev_long = long_sma.shift(1)

    # Buy: short crosses above long
    buy_signal = (prev_short <= prev_long) & (short_sma > long_sma)
    # Sell: short crosses below long
    sell_signal = (prev_short >= prev_long) & (short_sma < long_sma)

    signals[buy_signal] = 1
    signals[sell_signal] = -1
    return signals


def bollinger_strategy(
    prices_df: pd.DataFrame,
    window: int = 20,
    num_std: float = 2.0,
) -> pd.Series:
    """Bollinger Bands: buy at lower band, sell at upper band.

    Returns a signal series: 1 = buy, -1 = sell, 0 = hold.
    """
    signals = pd.Series(0, index=prices_df.index)
    close = prices_df["close"]

    sma = close.rolling(window=window).mean()
    std = close.rolling(window=window).std()

    upper_band = sma + (num_std * std)
    lower_band = sma - (num_std * std)

    signals[close <= lower_band] = 1
    signals[close >= upper_band] = -1
    return signals


# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------

STRATEGY_REGISTRY: dict[str, dict] = {
    "rsi": {
        "function": rsi_strategy,
        "description": "RSI-based strategy: buy when RSI is oversold, sell when overbought.",
        "default_params": {"buy_threshold": 30, "sell_threshold": 70},
    },
    "sma_crossover": {
        "function": sma_crossover_strategy,
        "description": "SMA crossover strategy: buy when short SMA crosses above long SMA.",
        "default_params": {"short_window": 20, "long_window": 50},
    },
    "bollinger": {
        "function": bollinger_strategy,
        "description": "Bollinger Bands strategy: buy at lower band, sell at upper band.",
        "default_params": {"window": 20, "num_std": 2.0},
    },
}


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------


def _compute_backtest_metrics(
    trades: list[dict],
    equity_curve: list[float],
    days: int,
) -> BacktestResult:
    """Compute backtest metrics from trade list and equity curve."""
    if not equity_curve or len(equity_curve) < 2:
        return BacktestResult(
            total_return=0.0,
            annualized_return=0.0,
            sharpe_ratio=None,
            max_drawdown=0.0,
            total_trades=0,
            win_rate=0.0,
            trades=trades,
            equity_curve=equity_curve,
        )

    initial = equity_curve[0]
    final = equity_curve[-1]
    total_return = ((final - initial) / initial) * 100 if initial > 0 else 0.0

    # Annualized return
    years = days / TRADING_DAYS_PER_YEAR
    if years > 0 and initial > 0 and final > 0:
        annualized = ((final / initial) ** (1 / years) - 1) * 100
    else:
        annualized = 0.0

    # Sharpe ratio from daily returns
    equity_series = pd.Series(equity_curve)
    daily_returns = equity_series.pct_change().dropna()
    sharpe = None
    if len(daily_returns) > 1 and daily_returns.std() > 0:
        daily_rf = (1 + RISK_FREE_RATE_ANNUAL) ** (1 / TRADING_DAYS_PER_YEAR) - 1
        excess = daily_returns - daily_rf
        sharpe = float(
            excess.mean() / excess.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
        )

    # Max drawdown
    peak = equity_series.cummax()
    drawdown = (equity_series - peak) / peak
    max_drawdown = float(drawdown.min()) * 100 if len(drawdown) > 0 else 0.0

    # Win rate
    winning_trades = [t for t in trades if t.get("pnl", 0) > 0]
    total_trades = len(trades)
    win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0.0

    return BacktestResult(
        total_return=round(total_return, 2),
        annualized_return=round(annualized, 2),
        sharpe_ratio=round(sharpe, 4) if sharpe is not None else None,
        max_drawdown=round(max_drawdown, 2),
        total_trades=total_trades,
        win_rate=round(win_rate, 2),
        trades=trades,
        equity_curve=[round(e, 4) for e in equity_curve],
    )


def _simulate_trades(
    prices_df: pd.DataFrame,
    signals: pd.Series,
    initial_capital: float = 100_000.0,
) -> tuple[list[dict], list[float]]:
    """Simulate trades based on signals and return trade list + equity curve."""
    cash = initial_capital
    position = 0.0  # number of shares
    entry_price = 0.0
    trades: list[dict] = []
    equity_curve: list[float] = []

    close_prices = prices_df["close"].values
    dates = prices_df.index

    for i in range(len(prices_df)):
        price = float(close_prices[i])
        signal = int(signals.iloc[i]) if i < len(signals) else 0
        current_date = dates[i]

        if signal == 1 and position == 0:
            # Buy: invest all cash
            position = cash / price
            entry_price = price
            cash = 0.0
            trades.append({
                "type": "buy",
                "date": str(current_date),
                "price": round(price, 4),
                "shares": round(position, 6),
            })
        elif signal == -1 and position > 0:
            # Sell: liquidate position
            cash = position * price
            pnl = (price - entry_price) * position
            trades.append({
                "type": "sell",
                "date": str(current_date),
                "price": round(price, 4),
                "shares": round(position, 6),
                "pnl": round(pnl, 4),
            })
            position = 0.0
            entry_price = 0.0

        # Portfolio value
        portfolio_value = cash + (position * price)
        equity_curve.append(portfolio_value)

    return trades, equity_curve


async def run_backtest(
    symbol: str,
    exchange: str,
    strategy_name: str,
    strategy_params: dict | None,
    days: int,
    db: AsyncSession,
    initial_capital: float = 100_000.0,
) -> BacktestResult:
    """Run a backtest for a given symbol using a specified strategy.

    1. Fetches price history from DB
    2. Calculates indicators
    3. Runs the chosen strategy
    4. Computes metrics
    5. Returns BacktestResult
    """
    if strategy_name not in STRATEGY_REGISTRY:
        raise ValueError(
            f"Unknown strategy '{strategy_name}'. "
            f"Available: {', '.join(STRATEGY_REGISTRY.keys())}"
        )

    # Fetch price history
    cutoff = date.today() - timedelta(days=days + 10)
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

    if len(rows) < 2:
        raise ValueError(
            f"Insufficient price data for {symbol} on {exchange}. "
            f"Found {len(rows)} records, need at least 2."
        )

    # Build DataFrame
    data = {
        "date": [r.date for r in rows],
        "open": [float(r.open) for r in rows],
        "high": [float(r.high) for r in rows],
        "low": [float(r.low) for r in rows],
        "close": [float(r.close) for r in rows],
        "volume": [int(r.volume) for r in rows],
    }
    if any(r.rsi_14 is not None for r in rows):
        data["rsi_14"] = [float(r.rsi_14) if r.rsi_14 is not None else np.nan for r in rows]

    prices_df = pd.DataFrame(data)
    prices_df.set_index("date", inplace=True)

    # Resolve strategy
    strategy_info = STRATEGY_REGISTRY[strategy_name]
    strategy_fn = strategy_info["function"]
    params = {**strategy_info["default_params"]}
    if strategy_params:
        params.update(strategy_params)

    # Generate signals
    signals = strategy_fn(prices_df, **params)

    # Simulate trades
    trades, equity_curve = _simulate_trades(prices_df, signals, initial_capital)

    # Compute and return metrics
    return _compute_backtest_metrics(trades, equity_curve, days)
