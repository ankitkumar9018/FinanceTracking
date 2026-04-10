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
            if abs(npv) < tol:
                return rate
            break
        new_rate = rate - npv / dnpv
        new_rate = max(new_rate, -0.99)
        if abs(new_rate - rate) < tol:
            return new_rate
        rate = new_rate

    # Fallback: bisection if Newton failed
    lo, hi = -0.99, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if _npv(mid) > 0:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            return mid
    return None
