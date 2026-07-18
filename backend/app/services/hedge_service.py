"""Portfolio insurance / hedge cost estimator.

INFORMATIONAL ONLY. This module produces a *very rough* order-of-magnitude
estimate of how much it might cost to hedge a portfolio's downside using
index put options. It deliberately avoids any live options data and does NOT
compute a real option price:

  * The put premium is a crude heuristic, NOT a Black-Scholes (or any other
    proper option-pricing) value. It ignores interest rates, dividends,
    strike selection, the volatility smile, time decay curvature, bid/ask
    spreads, lot sizes, and every other real-world pricing input.
  * Real index puts trade in fixed lot sizes and at strikes that rarely match
    the "near-the-money" assumption used here; the count here is fractional.

Treat every number this returns as a ballpark teaching aid, never as a quote,
a recommendation, or trade advice.
"""

from __future__ import annotations

import math

# A rough near-the-money premium heuristic multiplier. Chosen so that the
# estimate lands in a plausible ballpark for a ~1-6 month ATM index put; it is
# NOT derived from an option-pricing model.
_PREMIUM_HEURISTIC_FACTOR = 0.4

# Sensible fallback index level (approx. NIFTY 50) used only when the caller
# does not supply an index_price. Keep the estimate parameter-driven so it
# never needs live market data.
DEFAULT_INDEX_PRICE = 24000.0

_DISCLAIMER = (
    "Rough informational estimate only. The put premium here is a simple "
    "heuristic, NOT a real option price (no Black-Scholes, no live options "
    "data, no strike/lot-size/spread modelling). Do not use this as an "
    "options quote, a recommendation, or trade advice."
)


def compute_hedge_estimate(
    portfolio_value: float,
    beta: float,
    index_price: float,
    protection_pct: float,
    months: float,
    implied_vol_pct: float = 20.0,
) -> dict:
    """Estimate the cost of hedging portfolio downside with index puts.

    This is an intentionally simplified, model-free heuristic (see module
    docstring) — it needs no live options data and is driven entirely by the
    parameters passed in.

    Args:
        portfolio_value: Total current portfolio value (in portfolio currency).
        beta: Portfolio beta vs. the index. Used to scale the notional that a
            like-for-like index hedge would need to cover. Defaults to 1.0 at
            the caller if a computed beta is unavailable.
        index_price: Current level of the hedging index (e.g. NIFTY 50).
        protection_pct: Percentage of the (beta-adjusted) downside to protect,
            0-100. E.g. 80 hedges ~80% of the beta-adjusted notional.
        months: Protection horizon in months.
        implied_vol_pct: Assumed annualized implied volatility, in percent.

    Returns:
        A dict of the estimate and the assumptions behind it. All monetary
        values are in the same currency as ``portfolio_value``.
    """
    portfolio_value = max(float(portfolio_value), 0.0)
    beta = float(beta)
    index_price = float(index_price)
    protection_pct = max(float(protection_pct), 0.0)
    months = max(float(months), 0.0)
    implied_vol_pct = max(float(implied_vol_pct), 0.0)

    # Beta-adjusted notional we would need to cover for a full hedge, then
    # scaled by how much of the downside the user wants to protect.
    full_notional = portfolio_value * beta
    notional_hedged = full_notional * (protection_pct / 100.0)

    # Number of index-put "units" (contracts, fractional and lot-size-agnostic).
    puts_needed = notional_hedged / index_price if index_price > 0 else 0.0

    # Crude near-the-money put premium heuristic — NOT an option price.
    # premium ≈ index_price * (IV) * sqrt(T in years) * factor
    est_premium_per_put = (
        index_price
        * (implied_vol_pct / 100.0)
        * math.sqrt(months / 12.0)
        * _PREMIUM_HEURISTIC_FACTOR
    )

    est_total_cost = puts_needed * est_premium_per_put
    cost_pct_of_portfolio = (
        (est_total_cost / portfolio_value * 100.0) if portfolio_value > 0 else 0.0
    )

    return {
        "portfolio_value": round(portfolio_value, 2),
        "beta": round(beta, 4),
        "notional_hedged": round(notional_hedged, 2),
        "index_price": round(index_price, 2),
        "puts_needed": round(puts_needed, 4),
        "est_premium_per_put": round(est_premium_per_put, 2),
        "est_total_cost": round(est_total_cost, 2),
        "cost_pct_of_portfolio": round(cost_pct_of_portfolio, 4),
        "assumptions": {
            "implied_vol_pct": round(implied_vol_pct, 2),
            "months": round(months, 2),
            "protection_pct": round(protection_pct, 2),
        },
        "disclaimer": _DISCLAIMER,
    }
