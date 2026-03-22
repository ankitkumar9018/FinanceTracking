"""Portfolio optimisation — mean-variance with efficient frontier."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.price_history import PriceHistory

logger = logging.getLogger(__name__)

# Try to import scipy for proper optimisation; fall back to simpler approach
try:
    from scipy.optimize import minimize as scipy_minimize

    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE_ANNUAL = 0.07


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class OptimizationResult:
    """Result of a portfolio optimisation run."""

    current_weights: dict[str, float]
    optimal_weights: dict[str, float]
    expected_return: float
    expected_volatility: float
    sharpe_ratio: float
    efficient_frontier: list[dict] = field(default_factory=list)


@dataclass
class RebalanceSuggestion:
    """Suggestion for rebalancing a single holding."""

    symbol: str
    current_weight: float
    target_weight: float
    action: str  # "increase" / "decrease" / "hold"
    amount_percent: float


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _annualized_return(mean_daily: np.ndarray) -> np.ndarray:
    """Convert mean daily returns to annualised."""
    return mean_daily * TRADING_DAYS_PER_YEAR


def _annualized_volatility(cov_daily: np.ndarray, weights: np.ndarray) -> float:
    """Annualised portfolio volatility."""
    port_var = weights @ cov_daily @ weights
    return float(np.sqrt(port_var * TRADING_DAYS_PER_YEAR))


def _portfolio_return(mean_daily: np.ndarray, weights: np.ndarray) -> float:
    """Annualised portfolio return."""
    return float(weights @ _annualized_return(mean_daily))


def _portfolio_sharpe(
    mean_daily: np.ndarray,
    cov_daily: np.ndarray,
    weights: np.ndarray,
    risk_free: float = RISK_FREE_RATE_ANNUAL,
) -> float:
    """Annualised Sharpe ratio."""
    ret = _portfolio_return(mean_daily, weights)
    vol = _annualized_volatility(cov_daily, weights)
    if vol == 0:
        return 0.0
    return (ret - risk_free) / vol


def _optimize_scipy(
    mean_daily: np.ndarray,
    cov_daily: np.ndarray,
    n: int,
    objective: str,
) -> np.ndarray:
    """Use scipy to solve mean-variance optimisation.

    objective: "min_variance" | "max_sharpe" | "max_return"
    """
    bounds = tuple((0.0, 1.0) for _ in range(n))
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
    x0 = np.ones(n) / n

    if objective == "min_variance":
        def obj(w: np.ndarray) -> float:
            return float(w @ cov_daily @ w)
    elif objective == "max_sharpe":
        def obj(w: np.ndarray) -> float:
            sharpe = _portfolio_sharpe(mean_daily, cov_daily, w)
            return -sharpe  # minimise negative sharpe
    elif objective == "max_return":
        def obj(w: np.ndarray) -> float:
            return -float(w @ _annualized_return(mean_daily))
    else:
        raise ValueError(f"Unknown objective: {objective}")

    result = scipy_minimize(
        obj,
        x0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 1000, "ftol": 1e-9},
    )

    if result.success:
        # Normalise to exactly sum to 1
        weights = result.x
        weights = np.maximum(weights, 0)
        weights = weights / weights.sum()
        return weights
    else:
        logger.warning("Scipy optimisation did not converge: %s", result.message)
        return np.ones(n) / n


def _optimize_fallback(
    mean_daily: np.ndarray,
    cov_daily: np.ndarray,
    n: int,
    objective: str,
    num_samples: int = 10_000,
) -> np.ndarray:
    """Monte Carlo fallback when scipy is not available.

    Generates random portfolios and selects the best one according to objective.
    """
    best_weights = np.ones(n) / n
    best_metric = float("-inf") if objective != "min_variance" else float("inf")

    rng = np.random.default_rng(42)

    for _ in range(num_samples):
        w = rng.random(n)
        w = w / w.sum()

        if objective == "min_variance":
            metric = float(w @ cov_daily @ w)
            if metric < best_metric:
                best_metric = metric
                best_weights = w
        elif objective == "max_sharpe":
            metric = _portfolio_sharpe(mean_daily, cov_daily, w)
            if metric > best_metric:
                best_metric = metric
                best_weights = w
        elif objective == "max_return":
            metric = _portfolio_return(mean_daily, w)
            if metric > best_metric:
                best_metric = metric
                best_weights = w

    return best_weights


def _generate_efficient_frontier(
    mean_daily: np.ndarray,
    cov_daily: np.ndarray,
    n: int,
    num_points: int = 15,
) -> list[dict]:
    """Generate efficient frontier points via random portfolios."""
    rng = np.random.default_rng(42)
    points: list[dict] = []

    for _ in range(max(num_points * 500, 5000)):
        w = rng.random(n)
        w = w / w.sum()

        ret = _portfolio_return(mean_daily, w)
        vol = _annualized_volatility(cov_daily, w)
        sharpe = _portfolio_sharpe(mean_daily, cov_daily, w)

        points.append({
            "return": round(ret * 100, 2),
            "volatility": round(vol * 100, 2),
            "sharpe": round(sharpe, 4),
        })

    # Sort by volatility and pick evenly spaced points
    points.sort(key=lambda p: p["volatility"])

    if len(points) <= num_points:
        return points

    step = len(points) // num_points
    frontier = [points[i * step] for i in range(num_points)]
    return frontier


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def optimize_portfolio(
    portfolio_id: int,
    user_id: int,
    risk_tolerance: str,
    db: AsyncSession,
    days: int = 252,
) -> tuple[OptimizationResult, list[RebalanceSuggestion]]:
    """Run mean-variance optimisation on a portfolio.

    risk_tolerance: "conservative" (min variance), "moderate" (max sharpe),
                    "aggressive" (max return)

    Returns (OptimizationResult, list[RebalanceSuggestion]).
    """
    # Verify portfolio ownership
    port_result = await db.execute(
        select(Portfolio).where(
            Portfolio.id == portfolio_id,
            Portfolio.user_id == user_id,
        )
    )
    portfolio = port_result.scalar_one_or_none()
    if portfolio is None:
        raise ValueError("Portfolio not found or does not belong to the current user")

    # Fetch holdings
    h_result = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio_id)
    )
    holdings = h_result.scalars().all()

    if len(holdings) < 2:
        raise ValueError(
            "Portfolio must have at least 2 holdings for optimisation. "
            f"Found {len(holdings)}."
        )

    # Current weights by market value
    total_value = 0.0
    holding_values: dict[str, float] = {}
    symbols: list[str] = []

    for h in holdings:
        qty = float(h.cumulative_quantity)
        price = float(h.current_price) if h.current_price is not None else float(h.average_price)
        value = qty * price
        holding_values[h.stock_symbol] = value
        total_value += value
        symbols.append(h.stock_symbol)

    if total_value == 0:
        raise ValueError("Portfolio has zero total value")

    current_weights = {
        sym: round(val / total_value, 6) for sym, val in holding_values.items()
    }

    # Fetch price history for all holdings
    cutoff = date.today() - timedelta(days=days + 10)
    returns_data: dict[str, pd.Series] = {}

    for h in holdings:
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
            returns_data[h.stock_symbol] = daily_returns

    # Only optimise holdings with enough data
    valid_symbols = [s for s in symbols if s in returns_data and len(returns_data[s]) >= 30]
    if len(valid_symbols) < 2:
        raise ValueError(
            "Insufficient price history for optimisation. "
            f"Need at least 2 holdings with 30+ days of data, found {len(valid_symbols)}."
        )

    # Build returns matrix
    returns_df = pd.DataFrame(
        {sym: returns_data[sym] for sym in valid_symbols}
    ).dropna()

    if len(returns_df) < 30:
        raise ValueError("Insufficient overlapping price data for optimisation.")

    n = len(valid_symbols)
    mean_daily = returns_df.mean().values
    cov_daily = returns_df.cov().values

    # Map risk tolerance to objective
    objective_map = {
        "conservative": "min_variance",
        "moderate": "max_sharpe",
        "aggressive": "max_return",
    }
    objective = objective_map.get(risk_tolerance, "max_sharpe")

    # Run optimisation
    if HAS_SCIPY:
        optimal_raw = _optimize_scipy(mean_daily, cov_daily, n, objective)
    else:
        logger.info("scipy not available — using Monte Carlo fallback for optimisation")
        optimal_raw = _optimize_fallback(mean_daily, cov_daily, n, objective)

    optimal_weights = {
        sym: round(float(optimal_raw[i]), 6) for i, sym in enumerate(valid_symbols)
    }

    # For holdings excluded from optimisation, assign zero target weight
    for sym in symbols:
        if sym not in optimal_weights:
            optimal_weights[sym] = 0.0

    # Compute expected metrics for optimal portfolio
    exp_return = _portfolio_return(mean_daily, optimal_raw)
    exp_volatility = _annualized_volatility(cov_daily, optimal_raw)
    sharpe = _portfolio_sharpe(mean_daily, cov_daily, optimal_raw)

    # Generate efficient frontier
    frontier = _generate_efficient_frontier(mean_daily, cov_daily, n)

    optimization_result = OptimizationResult(
        current_weights=current_weights,
        optimal_weights=optimal_weights,
        expected_return=round(exp_return * 100, 2),
        expected_volatility=round(exp_volatility * 100, 2),
        sharpe_ratio=round(sharpe, 4),
        efficient_frontier=frontier,
    )

    # Generate rebalance suggestions
    suggestions = _build_suggestions(current_weights, optimal_weights, symbols)

    return optimization_result, suggestions


def _build_suggestions(
    current_weights: dict[str, float],
    optimal_weights: dict[str, float],
    symbols: list[str],
) -> list[RebalanceSuggestion]:
    """Build rebalance suggestions from current vs optimal weights."""
    suggestions: list[RebalanceSuggestion] = []
    threshold = 0.01  # 1% threshold for action

    for sym in symbols:
        cw = current_weights.get(sym, 0.0)
        tw = optimal_weights.get(sym, 0.0)
        diff = tw - cw

        if abs(diff) < threshold:
            action = "hold"
        elif diff > 0:
            action = "increase"
        else:
            action = "decrease"

        suggestions.append(
            RebalanceSuggestion(
                symbol=sym,
                current_weight=round(cw * 100, 2),
                target_weight=round(tw * 100, 2),
                action=action,
                amount_percent=round(abs(diff) * 100, 2),
            )
        )

    return suggestions
