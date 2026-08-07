"""Portfolio optimisation — mean-variance with efficient frontier."""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ml.common import RISK_FREE_RATE_ANNUAL, TRADING_DAYS_PER_YEAR
from app.ml.price_data import fetch_return_series
from app.models.holding import Holding
from app.models.portfolio import Portfolio

logger = logging.getLogger(__name__)

# Try to import scipy for proper optimisation; fall back to simpler approach
try:
    from scipy.optimize import minimize as scipy_minimize

    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

# A holding is identified by (stock_symbol, exchange) — symbol alone is NOT
# unique (the same company trades on NSE and BSE).
HoldingKey = tuple[str, str]


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
    """Approximate the efficient frontier as the UPPER HULL of sampled portfolios.

    Sample many random long-only portfolios, bucket them by volatility, and keep
    the maximum-return portfolio within each volatility bucket. A final left-to-
    right sweep drops any bucket winner that is dominated by a lower-volatility
    point, so the returned envelope is monotonically non-decreasing in return as
    volatility rises. Each returned point is therefore non-dominated: no other
    returned point has both a higher return AND a lower volatility.

    Deterministic (fixed RNG seed) so the same inputs always yield the same
    frontier, and dependency-free (numpy only — no scipy required).
    """
    rng = np.random.default_rng(42)
    num_samples = max(num_points * 500, 5000)

    rets = np.empty(num_samples)
    vols = np.empty(num_samples)
    sharpes = np.empty(num_samples)
    for i in range(num_samples):
        w = rng.random(n)
        w = w / w.sum()
        rets[i] = _portfolio_return(mean_daily, w)
        vols[i] = _annualized_volatility(cov_daily, w)
        sharpes[i] = _portfolio_sharpe(mean_daily, cov_daily, w)

    def _point(j: int) -> dict:
        return {
            "return": round(float(rets[j]) * 100, 2),
            "volatility": round(float(vols[j]) * 100, 2),
            "sharpe": round(float(sharpes[j]), 4),
        }

    v_min = float(vols.min())
    v_max = float(vols.max())
    if v_max <= v_min:
        # Degenerate cloud (single volatility): the frontier is its max-return
        # point.
        return [_point(int(np.argmax(rets)))]

    # Bucket by volatility; within each bucket keep the highest-return sample.
    edges = np.linspace(v_min, v_max, num_points + 1)
    bucket_of = np.clip(np.digitize(vols, edges) - 1, 0, num_points - 1)

    winners: list[int] = []
    for b in range(num_points):
        members = np.nonzero(bucket_of == b)[0]
        if members.size == 0:
            continue
        winners.append(int(members[np.argmax(rets[members])]))

    # Upper-hull sweep: process by ascending volatility (highest return first on
    # ties) and keep a point only if it strictly improves on the best return so
    # far. This guarantees every kept point is non-dominated.
    winners.sort(key=lambda j: (vols[j], -rets[j]))
    frontier: list[dict] = []
    best_ret = float("-inf")
    for j in winners:
        if rets[j] > best_ret:
            frontier.append(_point(j))
            best_ret = float(rets[j])
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

    # Current weights by market value, keyed by (symbol, exchange) exactly as
    # risk_calculator does — a plain-symbol key would collide for the same
    # company held on NSE and BSE, leaving duplicate entries in the valid list
    # and a covariance matrix whose size no longer matches → matmul ValueError.
    total_value = 0.0
    holding_values: dict[HoldingKey, float] = {}

    for h in holdings:
        qty = float(h.cumulative_quantity)
        price = float(h.current_price) if h.current_price is not None else float(h.average_price)
        value = qty * price
        key = (h.stock_symbol, h.exchange)
        holding_values[key] = holding_values.get(key, 0.0) + value
        total_value += value

    keys: list[HoldingKey] = list(holding_values)

    if total_value == 0:
        raise ValueError("Portfolio has zero total value")

    current_by_key = {
        key: round(val / total_value, 6) for key, val in holding_values.items()
    }

    # Fetch price history for all holdings (single batched query).
    # `days` means trading days (default 252 = 1y); widen the calendar
    # window accordingly or a "1-year" metric only sees ~7 months of bars
    cutoff = date.today() - timedelta(days=int(days * 1.45) + 10)
    returns_data = await fetch_return_series(db, holdings, cutoff)

    # Only optimise holdings with enough data
    valid_keys = [
        k for k in keys if k in returns_data and len(returns_data[k]) >= 30
    ]
    if len(valid_keys) < 2:
        raise ValueError(
            "Insufficient price history for optimisation. "
            f"Need at least 2 holdings with 30+ days of data, found {len(valid_keys)}."
        )

    # Build returns matrix (positional integer columns; row i maps to
    # valid_keys[i])
    returns_df = pd.DataFrame(
        {i: returns_data[k] for i, k in enumerate(valid_keys)}
    ).dropna()

    if len(returns_df) < 30:
        raise ValueError("Insufficient overlapping price data for optimisation.")

    n = len(valid_keys)
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

    optimal_by_key = {
        key: round(float(optimal_raw[i]), 6) for i, key in enumerate(valid_keys)
    }

    # Holdings without enough price history are excluded from optimisation.
    # Freeze them at their current weight (scaling the optimised weights into
    # the remaining budget) — a zero target would tell the user to sell to
    # zero because of a data gap, not a decision.
    excluded = [key for key in keys if key not in optimal_by_key]
    frozen_total = sum(current_by_key.get(key, 0.0) for key in excluded)
    if excluded and frozen_total < 1.0:
        scale = 1.0 - frozen_total
        optimal_by_key = {
            key: round(w * scale, 6) for key, w in optimal_by_key.items()
        }
    for key in excluded:
        optimal_by_key[key] = round(current_by_key.get(key, 0.0), 6)

    # Result dicts use display names: plain "SYM" in the common case, and
    # "SYM (EXCH)" only when the same symbol appears on multiple exchanges.
    display = _display_names(keys)
    current_weights = {display[key]: w for key, w in current_by_key.items()}
    optimal_weights = {display[key]: w for key, w in optimal_by_key.items()}

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
    suggestions = _build_suggestions(
        current_weights, optimal_weights, [display[key] for key in keys]
    )

    return optimization_result, suggestions


def _display_names(keys: list[HoldingKey]) -> dict[HoldingKey, str]:
    """Map each (symbol, exchange) key to its display name.

    Plain "SYM" unless the same symbol appears on multiple exchanges, in which
    case every occurrence is disambiguated as "SYM (EXCH)" — the common
    single-exchange case keeps its familiar labels unchanged.
    """
    symbol_counts = Counter(sym for sym, _ in keys)
    return {
        (sym, exch): f"{sym} ({exch})" if symbol_counts[sym] > 1 else sym
        for sym, exch in keys
    }


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
