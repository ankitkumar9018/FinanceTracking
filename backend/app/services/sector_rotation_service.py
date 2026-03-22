"""Sector Rotation Tracker — analyse sector-wise allocation changes over time.

Uses the ``sector`` field on each :class:`Holding` to compute current sector
weights and compares them against weights derived from transactions one month
ago, giving users a clear picture of how their sector exposure has shifted.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.holding import Holding
from app.models.transaction import Transaction

logger = logging.getLogger(__name__)

_UNKNOWN_SECTOR = "Unknown"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _market_value(holding: Holding) -> float:
    """Return current market value for a holding."""
    price = (
        float(holding.current_price)
        if holding.current_price is not None
        else float(holding.average_price)
    )
    return float(holding.cumulative_quantity) * price


def _compute_weights(sector_values: dict[str, float]) -> dict[str, float]:
    """Turn absolute values into percentage weights."""
    total = sum(sector_values.values())
    if total <= 0:
        return {s: 0.0 for s in sector_values}
    return {s: round((v / total) * 100, 2) for s, v in sector_values.items()}


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

async def get_sector_rotation(
    portfolio_id: int,
    db: AsyncSession,
) -> dict:
    """Return current sector weights and change versus one month ago.

    Returns::

        {
            "sectors": [
                {
                    "sector": "IT",
                    "current_weight": 30.5,
                    "previous_weight": 28.0,
                    "change": 2.5,
                    "current_value": 150000.0,
                },
                ...
            ],
            "total_value": 500000.0,
        }
    """
    # -- Current sector weights from live holdings --
    result = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio_id)
    )
    holdings = list(result.scalars().all())

    if not holdings:
        return {"sectors": [], "total_value": 0.0}

    current_sector_values: dict[str, float] = defaultdict(float)
    holding_sectors: dict[int, str] = {}

    for h in holdings:
        sector = h.sector or _UNKNOWN_SECTOR
        mv = _market_value(h)
        current_sector_values[sector] += mv
        holding_sectors[h.id] = sector

    total_value = sum(current_sector_values.values())
    current_weights = _compute_weights(dict(current_sector_values))

    # -- Previous month weights --
    # Strategy: reconstruct approximate weights by subtracting the net
    # transactions from the last 30 days.  This gives us a rough picture of
    # the portfolio one month ago without requiring historical snapshots.
    one_month_ago = date.today() - timedelta(days=30)

    # Gather holding IDs in this portfolio
    holding_ids = [h.id for h in holdings]

    tx_result = await db.execute(
        select(Transaction).where(
            Transaction.holding_id.in_(holding_ids),
            Transaction.date >= one_month_ago,
        )
    )
    recent_txns = list(tx_result.scalars().all())

    # Build a map of net-value-change per holding from recent transactions
    holding_net_change: dict[int, float] = defaultdict(float)
    for tx in recent_txns:
        value = float(tx.quantity) * float(tx.price)
        if tx.transaction_type == "BUY":
            holding_net_change[tx.holding_id] += value
        else:  # SELL
            holding_net_change[tx.holding_id] -= value

    # Reconstruct previous sector values by subtracting the net change
    prev_sector_values: dict[str, float] = defaultdict(float)
    for h in holdings:
        sector = holding_sectors[h.id]
        mv = _market_value(h)
        net_change = holding_net_change.get(h.id, 0.0)
        prev_value = max(mv - net_change, 0.0)
        prev_sector_values[sector] += prev_value

    previous_weights = _compute_weights(dict(prev_sector_values))

    # -- Merge into response --
    all_sectors = sorted(set(current_weights.keys()) | set(previous_weights.keys()))
    sectors: list[dict] = []
    for sector in all_sectors:
        cw = current_weights.get(sector, 0.0)
        pw = previous_weights.get(sector, 0.0)
        sectors.append(
            {
                "sector": sector,
                "current_weight": cw,
                "previous_weight": pw,
                "change": round(cw - pw, 2),
                "current_value": round(current_sector_values.get(sector, 0.0), 2),
            }
        )

    return {
        "sectors": sectors,
        "total_value": round(total_value, 2),
    }
