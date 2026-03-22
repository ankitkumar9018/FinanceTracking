"""Portfolio risk metrics — Sharpe, Sortino, VaR, MaxDD, Beta."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

RISK_FREE_RATE_ANNUAL = 0.07  # 7% (India 10Y govt bond approx)
TRADING_DAYS_PER_YEAR = 252


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
    """Annualized Sharpe ratio."""
    if len(returns) < 30 or returns.std() < 1e-10:
        return None
    daily_rf = (1 + risk_free_rate) ** (1 / TRADING_DAYS_PER_YEAR) - 1
    excess = returns - daily_rf
    if excess.std() < 1e-10:
        return None
    return float(excess.mean() / excess.std() * np.sqrt(TRADING_DAYS_PER_YEAR))


def calculate_sortino_ratio(
    returns: pd.Series,
    risk_free_rate: float = RISK_FREE_RATE_ANNUAL,
) -> float | None:
    """Annualized Sortino ratio (downside deviation only)."""
    if len(returns) < 30:
        return None
    daily_rf = (1 + risk_free_rate) ** (1 / TRADING_DAYS_PER_YEAR) - 1
    excess = returns - daily_rf
    downside = excess[excess < 0]
    if len(downside) == 0 or downside.std() < 1e-10:
        return None
    return float(excess.mean() / downside.std() * np.sqrt(TRADING_DAYS_PER_YEAR))


def calculate_max_drawdown(
    cumulative_returns: pd.Series,
) -> tuple[float | None, int | None]:
    """Max drawdown and its duration in trading days."""
    if len(cumulative_returns) < 2:
        return None, None

    wealth = (1 + cumulative_returns).cumprod()
    running_max = wealth.cummax()
    drawdown = (wealth - running_max) / running_max

    max_dd = float(drawdown.min())

    # Duration
    in_drawdown = drawdown < 0
    if not in_drawdown.any():
        return 0.0, 0

    # Find longest drawdown period
    groups = (~in_drawdown).cumsum()
    dd_groups = groups[in_drawdown]
    if len(dd_groups) == 0:
        return max_dd, 0
    duration = dd_groups.value_counts().max()
    return max_dd, int(duration)


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
    holdings_data: list[dict],  # [{symbol, weight, daily_returns: pd.Series}]
) -> pd.Series:
    """Calculate weighted portfolio returns."""
    if not holdings_data:
        return pd.Series(dtype=float)

    df = pd.DataFrame(
        {h["symbol"]: h["daily_returns"] * h["weight"] for h in holdings_data}
    )
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
    from app.models.price_history import PriceHistory

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

    cutoff = date.today() - timedelta(days=days + 10)
    holdings_data = []

    for h in holdings:
        value = float(h.cumulative_quantity) * float(
            h.current_price or h.average_price
        )
        weight = value / total_value if total_value > 0 else 0

        # Fetch daily prices
        price_result = await db.execute(
            select(PriceHistory.date, PriceHistory.close)
            .where(
                PriceHistory.stock_symbol == h.stock_symbol,
                PriceHistory.exchange == h.exchange,
                PriceHistory.date >= cutoff,
            )
            .order_by(PriceHistory.date.asc())
        )
        prices = price_result.all()

        if len(prices) >= 2:
            price_series = pd.Series(
                [float(p.close) for p in prices],
                index=[p.date for p in prices],
            )
            daily_returns = price_series.pct_change().dropna()
            holdings_data.append(
                {
                    "symbol": h.stock_symbol,
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

    # Alpha = portfolio return - (risk_free + beta * (benchmark_return - risk_free))
    alpha_val = None
    if beta is not None and len(bench_returns) > 0:
        ann_port = float(port_returns.mean() * TRADING_DAYS_PER_YEAR)
        ann_bench = float(bench_returns.mean() * TRADING_DAYS_PER_YEAR)
        alpha_val = ann_port - (
            RISK_FREE_RATE_ANNUAL + beta * (ann_bench - RISK_FREE_RATE_ANNUAL)
        )

    # Information ratio
    info_ratio = None
    if len(bench_returns) > 0:
        aligned = pd.DataFrame(
            {"port": port_returns, "bench": bench_returns}
        ).dropna()
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
    from app.models.price_history import PriceHistory

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

    cutoff = date.today() - timedelta(days=days + 10)

    # Benchmark returns
    bench_returns = await _fetch_benchmark_returns(db, benchmark_symbol, cutoff)

    results = []
    for h in holdings:
        value = float(h.cumulative_quantity) * float(
            h.current_price or h.average_price
        )
        weight = value / total_value if total_value > 0 else 0

        price_result = await db.execute(
            select(PriceHistory.date, PriceHistory.close)
            .where(
                PriceHistory.stock_symbol == h.stock_symbol,
                PriceHistory.exchange == h.exchange,
                PriceHistory.date >= cutoff,
            )
            .order_by(PriceHistory.date.asc())
        )
        prices = price_result.all()

        beta_val = None
        corr_val = None
        vol_val = None
        contrib = None

        if len(prices) >= 2:
            price_series = pd.Series(
                [float(p.close) for p in prices],
                index=[p.date for p in prices],
            )
            daily_returns = price_series.pct_change().dropna()
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
