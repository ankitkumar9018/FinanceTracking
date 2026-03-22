"""Portfolio Drift Service — detect allocation drift from target percentages.

Target allocations are stored in each holding's ``custom_fields`` JSON under
the key ``target_allocation_pct``.  The service compares actual portfolio
weights (by current market value) against these targets and flags holdings
where the absolute difference exceeds a configurable threshold.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.holding import Holding
from app.models.portfolio import Portfolio

logger = logging.getLogger(__name__)

# Default drift threshold in percentage points
DEFAULT_DRIFT_THRESHOLD: float = 5.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _market_value(holding: Holding) -> float:
    """Return the current market value of a holding."""
    price = (
        float(holding.current_price)
        if holding.current_price is not None
        else float(holding.average_price)
    )
    return float(holding.cumulative_quantity) * price


# ---------------------------------------------------------------------------
# Set target allocation
# ---------------------------------------------------------------------------

async def set_target_allocation(
    holding_id: int,
    target_pct: float,
    user_id: int,
    db: AsyncSession,
) -> Holding:
    """Persist a target allocation percentage in a holding's custom_fields.

    Raises ``ValueError`` if the holding is not found or does not belong to
    the user.
    """
    result = await db.execute(
        select(Holding)
        .join(Portfolio, Holding.portfolio_id == Portfolio.id)
        .where(Holding.id == holding_id, Portfolio.user_id == user_id)
    )
    holding = result.scalar_one_or_none()
    if holding is None:
        raise ValueError("Holding not found or does not belong to the current user")

    custom = dict(holding.custom_fields) if holding.custom_fields else {}
    custom["target_allocation_pct"] = round(target_pct, 2)
    holding.custom_fields = custom

    await db.flush()
    await db.refresh(holding)
    return holding


# ---------------------------------------------------------------------------
# Check drift
# ---------------------------------------------------------------------------

async def check_drift(
    portfolio_id: int,
    db: AsyncSession,
    threshold: float = DEFAULT_DRIFT_THRESHOLD,
) -> list[dict]:
    """Compare actual allocation vs target for every holding in a portfolio.

    Returns a list of dicts with keys:
        holding_id, stock_symbol, stock_name, sector, exchange,
        target_pct, actual_pct, drift_pct, over_threshold
    """
    result = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio_id)
    )
    holdings = list(result.scalars().all())

    if not holdings:
        return []

    # Total portfolio market value
    total_value = sum(_market_value(h) for h in holdings)
    if total_value <= 0:
        return []

    drift_report: list[dict] = []
    for h in holdings:
        mv = _market_value(h)
        actual_pct = round((mv / total_value) * 100, 2)

        custom = h.custom_fields or {}
        target_pct = custom.get("target_allocation_pct")

        drift_pct: float | None = None
        over_threshold = False
        if target_pct is not None:
            drift_pct = round(actual_pct - target_pct, 2)
            over_threshold = abs(drift_pct) > threshold

        drift_report.append(
            {
                "holding_id": h.id,
                "stock_symbol": h.stock_symbol,
                "stock_name": h.stock_name,
                "sector": h.sector,
                "exchange": h.exchange,
                "market_value": round(mv, 2),
                "target_pct": target_pct,
                "actual_pct": actual_pct,
                "drift_pct": drift_pct,
                "over_threshold": over_threshold,
            }
        )

    return drift_report
