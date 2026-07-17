"""XIRR (Extended Internal Rate of Return) calculator.

Accounts for cash flows at irregular intervals — the standard way to
measure true portfolio returns for SIP and partial sale scenarios.
"""

from __future__ import annotations

import math
from datetime import date
from dataclasses import dataclass


@dataclass
class CashFlow:
    """A single cash flow: negative = money out (buy), positive = money in (sell/current value)."""
    date: date
    amount: float


def xirr(cash_flows: list[CashFlow], guess: float = 0.1, max_iter: int = 200, tol: float = 1e-7) -> float | None:
    """Calculate XIRR using Newton-Raphson method.

    Returns annualized return as a decimal (e.g. 0.12 for 12%).
    Returns None if it fails to converge.
    """
    if not cash_flows or len(cash_flows) < 2:
        return None

    # Sort by date
    flows = sorted(cash_flows, key=lambda cf: cf.date)

    # All cash flows on the same date — XIRR is mathematically undefined
    if len(set(cf.date for cf in flows)) < 2:
        return None

    d0 = flows[0].date

    def _days(d: date) -> float:
        return (d - d0).days / 365.25

    def _npv(rate: float) -> float:
        return sum(cf.amount / (1 + rate) ** _days(cf.date) for cf in flows)

    def _dnpv(rate: float) -> float:
        return sum(-_days(cf.date) * cf.amount / (1 + rate) ** (_days(cf.date) + 1) for cf in flows)

    # A candidate rate only counts as a root if NPV is actually ~0 at that
    # rate (relative to the money involved). Without this, buys-only flows
    # (e.g. every current_price is stale/None so there is no terminal value)
    # "converge" to the -99% boundary and get reported as a real return.
    total_scale = sum(abs(cf.amount) for cf in flows)
    npv_tol = max(total_scale * 1e-9, 1e-2)

    rate = max(guess, -0.99)
    for _ in range(max_iter):
        # Clamp rate before computing to avoid (1 + rate) ** x with rate <= -1
        rate = max(rate, -0.99)
        try:
            npv = _npv(rate)
            dnpv = _dnpv(rate)
        except (ValueError, ZeroDivisionError, OverflowError):
            break  # Fall through to bisection
        if abs(dnpv) < 1e-12:
            if abs(npv) < npv_tol:
                return rate
            break
        new_rate = rate - npv / dnpv
        new_rate = max(new_rate, -0.99)
        if abs(new_rate - rate) < tol:
            if abs(_npv(new_rate)) < npv_tol:
                return new_rate
            break  # Stalled at a clamp/plateau, not a root
        rate = new_rate

    # Fallback: bisection — only valid if the bracket actually straddles a root
    lo, hi = -0.99, 10.0
    try:
        npv_lo, npv_hi = _npv(lo), _npv(hi)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
    if npv_lo == 0.0:
        return lo
    if npv_hi == 0.0:
        return hi
    if (npv_lo > 0) == (npv_hi > 0):
        return None  # No sign change — no root in range, XIRR undefined here
    for _ in range(200):
        mid = (lo + hi) / 2
        v = _npv(mid)
        if v == 0.0:
            return mid
        if (v > 0) == (npv_lo > 0):
            lo, npv_lo = mid, v
        else:
            hi = mid
        if hi - lo < tol:
            return (lo + hi) / 2
    return None
