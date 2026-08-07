"""Shared ML constants and return-series metrics.

Single owner of ``TRADING_DAYS_PER_YEAR`` / ``RISK_FREE_RATE_ANNUAL`` (which
were previously declared independently in ``risk_calculator``, ``backtester``
and ``portfolio_optimizer``) plus the Sharpe and max-drawdown computations the
backtester used to re-implement inline.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = [
    "RISK_FREE_RATE_ANNUAL",
    "TRADING_DAYS_PER_YEAR",
    "max_drawdown_from_returns",
    "sharpe",
]

TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE_ANNUAL = 0.07  # 7% (India 10Y govt bond approx)


def sharpe(
    returns: pd.Series,
    risk_free_rate: float = RISK_FREE_RATE_ANNUAL,
    *,
    min_obs: int = 2,
) -> float | None:
    """Annualized Sharpe ratio of a daily-return series.

    Returns ``None`` when there are fewer than ``min_obs`` observations or the
    excess-return std is (numerically) zero. ``risk_calculator`` wraps this
    with ``min_obs=30``; the backtester uses the permissive default.
    """
    if len(returns) < min_obs:
        return None
    daily_rf = (1 + risk_free_rate) ** (1 / TRADING_DAYS_PER_YEAR) - 1
    excess = returns - daily_rf
    std = float(excess.std())
    if np.isnan(std) or std < 1e-10:
        return None
    return float(excess.mean() / std * np.sqrt(TRADING_DAYS_PER_YEAR))


def max_drawdown_from_returns(
    returns: pd.Series,
) -> tuple[float | None, int | None]:
    """Max drawdown (as a negative fraction) and its duration in bars.

    The wealth path includes the implicit 1.0 starting point, so a drawdown
    that begins on the very first return is still counted (an equity curve
    always contains its initial value; a bare ``cumprod`` over returns would
    silently drop a drawdown anchored at t0).
    """
    if len(returns) < 1:
        return None, None

    wealth = np.concatenate(
        [[1.0], np.cumprod(1.0 + returns.to_numpy(dtype=float))]
    )
    running_max = np.maximum.accumulate(wealth)
    drawdown = pd.Series((wealth - running_max) / running_max)

    max_dd = float(drawdown.min())

    in_drawdown = drawdown < 0
    if not in_drawdown.any():
        return 0.0, 0

    # Longest consecutive run of in-drawdown bars.
    groups = (~in_drawdown).cumsum()
    duration = groups[in_drawdown].value_counts().max()
    return max_dd, int(duration)
