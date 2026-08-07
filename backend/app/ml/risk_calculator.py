"""Portfolio risk metrics — Sharpe, Sortino, VaR, MaxDD, Beta."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.ml import common
from app.ml.common import RISK_FREE_RATE_ANNUAL, TRADING_DAYS_PER_YEAR
from app.ml.price_data import fetch_return_series

logger = logging.getLogger(__name__)


@dataclass
class RiskMetrics:
    """Portfolio-level risk metrics."""

    sharpe_ratio: float | None
    sortino_ratio: float | None
    max_drawdown: float | None
    max_drawdown_duration_days: int | None
    value_at_risk_95: float | None  # 1-day VaR at 95% confidence
    value_at_risk_99: float | None
    volatility_annual: float | None
    beta: float | None  # vs benchmark
    alpha: float | None
    information_ratio: float | None
    calmar_ratio: float | None


@dataclass
class HoldingRisk:
    """Per-holding risk metrics."""

    symbol: str
    beta: float | None
    correlation: float | None  # vs benchmark
    volatility: float | None
    weight: float  # portfolio weight
    contribution_to_risk: float | None


def _empty_risk_metrics() -> RiskMetrics:
    """Return a RiskMetrics instance with all None values."""
    return RiskMetrics(
        sharpe_ratio=None,
        sortino_ratio=None,
        max_drawdown=None,
        max_drawdown_duration_days=None,
        value_at_risk_95=None,
        value_at_risk_99=None,
        volatility_annual=None,
        beta=None,
        alpha=None,
        information_ratio=None,
        calmar_ratio=None,
    )


def calculate_sharpe_ratio(
    returns: pd.Series,
    risk_free_rate: float = RISK_FREE_RATE_ANNUAL,
) -> float | None:
    """Annualized Sharpe ratio (None-guarded wrapper over ``common.sharpe``)."""
    if len(returns) < 30 or returns.std() < 1e-10:
        return None
    return common.sharpe(returns, risk_free_rate, min_obs=30)


def calculate_sortino_ratio(
    returns: pd.Series,
    risk_free_rate: float = RISK_FREE_RATE_ANNUAL,
) -> float | None:
    """Annualized Sortino ratio (downside deviation only)."""
    if len(returns) < 30:
        return None
    daily_rf = (1 + risk_free_rate) ** (1 / TRADING_DAYS_PER_YEAR) - 1
    excess = returns - daily_rf
    # Downside deviation is the RMS of negative excess over ALL observations
    # (clipping positives to 0) — not the sample std of the negative subset,
    # which re-centers within the subset and overstates Sortino.
    downside_dev = float(np.sqrt((excess.clip(upper=0.0) ** 2).mean()))
    if downside_dev < 1e-10:
        return None
    return float(excess.mean() / downside_dev * np.sqrt(TRADING_DAYS_PER_YEAR))


def calculate_max_drawdown(
    cumulative_returns: pd.Series,
) -> tuple[float | None, int | None]:
    """Max drawdown and its duration in trading days.

    None-guarded wrapper over ``common.max_drawdown_from_returns``.
    """
    if len(cumulative_returns) < 2:
        return None, None
    return common.max_drawdown_from_returns(cumulative_returns)


def calculate_var(
    returns: pd.Series,
    confidence: float = 0.95,
) -> float | None:
    """Value at Risk using historical simulation (1-day)."""
    if len(returns) < 30:
        return None
    return float(np.percentile(returns, (1 - confidence) * 100))


def calculate_beta(
    returns: pd.Series,
    benchmark_returns: pd.Series,
) -> float | None:
    """Beta relative to a benchmark."""
    if len(returns) < 30 or len(benchmark_returns) < 30:
        return None

    # Align dates
    aligned = pd.DataFrame(
        {"asset": returns, "benchmark": benchmark_returns}
    ).dropna()
    if len(aligned) < 30:
        return None

    cov = aligned["asset"].cov(aligned["benchmark"])
    var_bench = aligned["benchmark"].var()
    if var_bench == 0:
        return None
    return float(cov / var_bench)


def calculate_portfolio_returns(
    holdings_data: list[dict],  # [{symbol, exchange?, weight, daily_returns}]
) -> pd.Series:
    """Calculate weighted portfolio returns.

    Weights are renormalized to sum to 1 over the holdings actually present
    here: callers drop holdings that lack price history, so the surviving
    weights would otherwise sum to <1 and understate the metrics.
    """
    if not holdings_data:
        return pd.Series(dtype=float)

    total_weight = sum(h["weight"] for h in holdings_data)
    if total_weight <= 0:
        return pd.Series(dtype=float)

    # Key each column by (symbol, exchange) so two holdings of the same symbol
    # on different exchanges don't collide (a plain symbol key would silently
    # drop one of them).
    columns = {
        (h["symbol"], h.get("exchange")): h["daily_returns"]
        * (h["weight"] / total_weight)
        for h in holdings_data
    }
    df = pd.DataFrame(columns)
    # Only use dates where every holding has data: summing with NaN→0 would
    # fabricate 0%-return days (all-NaN dates) and value shorter-history
    # holdings at 0% without renormalizing weights, biasing vol/VaR/Sharpe.
    df = df.dropna()
    return df.sum(axis=1)


async def _fetch_benchmark_returns(
    db,
    benchmark_symbol: str,
    cutoff: date,
) -> pd.Series:
    """Fetch benchmark daily returns from the database."""
    from sqlalchemy import select

    from app.models.price_history import PriceHistory

    bench_result = await db.execute(
        select(PriceHistory.date, PriceHistory.close)
        .where(
            PriceHistory.stock_symbol == benchmark_symbol,
            PriceHistory.date >= cutoff,
        )
        .order_by(PriceHistory.date.asc())
    )
    bench_prices = bench_result.all()
    bench_returns = pd.Series(dtype=float)
    if len(bench_prices) >= 2:
        bench_series = pd.Series(
            [float(p.close) for p in bench_prices],
            index=[p.date for p in bench_prices],
        )
        bench_returns = bench_series.pct_change().dropna()
    return bench_returns


async def compute_portfolio_risk(
    user_id: int,
    portfolio_id: int,
    db,  # AsyncSession
    days: int = 252,
    benchmark_symbol: str = "^NSEI",  # Nifty 50
) -> RiskMetrics:
    """Compute comprehensive risk metrics for a portfolio."""
    from sqlalchemy import select

    from app.models.holding import Holding
    from app.models.portfolio import Portfolio

    # Verify portfolio ownership
    port_result = await db.execute(
        select(Portfolio).where(
            Portfolio.id == portfolio_id,
            Portfolio.user_id == user_id,
        )
    )
    portfolio = port_result.scalar_one_or_none()
    if portfolio is None:
        return _empty_risk_metrics()

    # Get holdings
    h_result = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio_id)
    )
    holdings = h_result.scalars().all()

    if not holdings:
        return _empty_risk_metrics()

    # Calculate portfolio value and weights
    total_value = sum(
        float(h.cumulative_quantity) * float(h.current_price or h.average_price)
        for h in holdings
    )

    # `days` means trading days (default 252 = 1y); widen the calendar
    # window accordingly or a "1-year" metric only sees ~7 months of bars
    cutoff = date.today() - timedelta(days=int(days * 1.45) + 10)
    holdings_data = []

    # Single-query batch fetch of every holding's return series, keyed by
    # (symbol, exchange) — see app.ml.price_data.fetch_return_series.
    returns_by_key = await fetch_return_series(db, holdings, cutoff)

    for h in holdings:
        value = float(h.cumulative_quantity) * float(
            h.current_price or h.average_price
        )
        weight = value / total_value if total_value > 0 else 0

        daily_returns = returns_by_key.get((h.stock_symbol, h.exchange))
        if daily_returns is not None:
            holdings_data.append(
                {
                    "symbol": h.stock_symbol,
                    "exchange": h.exchange,
                    "weight": weight,
                    "daily_returns": daily_returns,
                }
            )

    if not holdings_data:
        return _empty_risk_metrics()

    # Portfolio returns
    port_returns = calculate_portfolio_returns(holdings_data)

    # Benchmark returns
    bench_returns = await _fetch_benchmark_returns(db, benchmark_symbol, cutoff)

    # Compute metrics
    sharpe = calculate_sharpe_ratio(port_returns)
    sortino = calculate_sortino_ratio(port_returns)
    max_dd, dd_duration = calculate_max_drawdown(port_returns)
    var_95 = calculate_var(port_returns, 0.95)
    var_99 = calculate_var(port_returns, 0.99)
    volatility = (
        float(port_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR))
        if len(port_returns) > 1
        else None
    )

    beta = (
        calculate_beta(port_returns, bench_returns)
        if len(bench_returns) > 0
        else None
    )

    # Align portfolio and benchmark on their overlapping dates ONCE and reuse
    # for both alpha and the information ratio — comparing each series' own
    # full-length mean would mix different date windows.
    aligned = pd.DataFrame(
        {"port": port_returns, "bench": bench_returns}
    ).dropna()

    # Alpha = portfolio return - (risk_free + beta * (benchmark_return - risk_free))
    alpha_val = None
    if beta is not None and len(aligned) > 0:
        ann_port = float(aligned["port"].mean() * TRADING_DAYS_PER_YEAR)
        ann_bench = float(aligned["bench"].mean() * TRADING_DAYS_PER_YEAR)
        alpha_val = ann_port - (
            RISK_FREE_RATE_ANNUAL + beta * (ann_bench - RISK_FREE_RATE_ANNUAL)
        )

    # Information ratio
    info_ratio = None
    if len(aligned) > 30:
        tracking_error = (aligned["port"] - aligned["bench"]).std() * np.sqrt(
            TRADING_DAYS_PER_YEAR
        )
        if tracking_error > 0:
            excess_return = (
                aligned["port"].mean() - aligned["bench"].mean()
            ) * TRADING_DAYS_PER_YEAR
            info_ratio = float(excess_return / tracking_error)

    # Calmar ratio
    calmar = None
    if max_dd is not None and max_dd < 0 and len(port_returns) > 0:
        ann_return = float(port_returns.mean() * TRADING_DAYS_PER_YEAR)
        calmar = ann_return / abs(max_dd)

    return RiskMetrics(
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        max_drawdown=max_dd,
        max_drawdown_duration_days=dd_duration,
        value_at_risk_95=var_95,
        value_at_risk_99=var_99,
        volatility_annual=volatility,
        beta=beta,
        alpha=alpha_val,
        information_ratio=info_ratio,
        calmar_ratio=calmar,
    )


async def compute_holding_risks(
    user_id: int,
    portfolio_id: int,
    db,
    days: int = 252,
    benchmark_symbol: str = "^NSEI",
) -> list[HoldingRisk]:
    """Compute per-holding risk metrics."""
    from sqlalchemy import select

    from app.models.holding import Holding
    from app.models.portfolio import Portfolio

    port_result = await db.execute(
        select(Portfolio).where(
            Portfolio.id == portfolio_id,
            Portfolio.user_id == user_id,
        )
    )
    if port_result.scalar_one_or_none() is None:
        return []

    h_result = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio_id)
    )
    holdings = h_result.scalars().all()
    if not holdings:
        return []

    total_value = sum(
        float(h.cumulative_quantity) * float(h.current_price or h.average_price)
        for h in holdings
    )

    # `days` means trading days (default 252 = 1y); widen the calendar
    # window accordingly or a "1-year" metric only sees ~7 months of bars
    cutoff = date.today() - timedelta(days=int(days * 1.45) + 10)

    # Benchmark returns
    bench_returns = await _fetch_benchmark_returns(db, benchmark_symbol, cutoff)

    # Single-query batch fetch of every holding's return series, keyed by
    # (symbol, exchange) — see app.ml.price_data.fetch_return_series.
    returns_by_key = await fetch_return_series(db, holdings, cutoff)

    results = []
    for h in holdings:
        value = float(h.cumulative_quantity) * float(
            h.current_price or h.average_price
        )
        weight = value / total_value if total_value > 0 else 0

        daily_returns = returns_by_key.get((h.stock_symbol, h.exchange))

        beta_val = None
        corr_val = None
        vol_val = None
        contrib = None

        if daily_returns is not None:
            vol_val = float(daily_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR))

            if len(bench_returns) > 0:
                beta_val = calculate_beta(daily_returns, bench_returns)
                aligned = pd.DataFrame(
                    {"asset": daily_returns, "bench": bench_returns}
                ).dropna()
                if len(aligned) > 10:
                    corr_val = float(aligned["asset"].corr(aligned["bench"]))

            if vol_val is not None:
                contrib = weight * vol_val

        results.append(
            HoldingRisk(
                symbol=h.stock_symbol,
                beta=beta_val,
                correlation=corr_val,
                volatility=vol_val,
                weight=round(weight, 4),
                contribution_to_risk=contrib,
            )
        )

    return results
