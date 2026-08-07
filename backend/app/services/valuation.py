"""Shared holding valuation helpers.

Single home for the qty × price arithmetic that was duplicated inline as
``_market_value`` in ``drift_service`` and ``concentration_service``.  Works
with any object exposing ``cumulative_quantity``, ``current_price``, and
``average_price`` (the ``Holding`` model shape).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.holding import Holding

__all__ = ["invested_value", "market_value"]


def market_value(holding: Holding, *, fallback_to_avg: bool = True) -> float | None:
    """Current market value of a holding: quantity × current price.

    When ``current_price`` is ``None``: fall back to ``average_price`` if
    ``fallback_to_avg`` (matching the drift/concentration inline helpers),
    otherwise return ``None`` so callers can distinguish "no live price".

    Returns ``None`` when the quantity (or the applicable price) is missing;
    a zero quantity yields ``0.0``.
    """
    qty = getattr(holding, "cumulative_quantity", None)
    if qty is None:
        return None
    price = getattr(holding, "current_price", None)
    if price is None:
        if not fallback_to_avg:
            return None
        price = getattr(holding, "average_price", None)
        if price is None:
            return None
    return float(qty) * float(price)


def invested_value(holding: Holding) -> float:
    """Invested (cost-basis) value of a holding: quantity × average price.

    Missing quantity or average price yields ``0.0``.
    """
    qty = getattr(holding, "cumulative_quantity", None)
    avg = getattr(holding, "average_price", None)
    if qty is None or avg is None:
        return 0.0
    return float(qty) * float(avg)
