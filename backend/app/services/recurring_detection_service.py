"""Recurring Transaction Detection — identify SIP-like patterns.

Analyses transaction history per holding and detects Systematic Investment Plan
(SIP) patterns by looking for:
- Same stock (same holding_id)
- Similar amounts (within 10% tolerance)
- Regular intervals clustered around the median gap, so weekly (~7d),
  bi-weekly (~14d), monthly (~30d) and quarterly (~91d) cadences are all
  recognised (not just monthly).

Results include the detected frequency, average amount, and the projected next
expected transaction date.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta
from statistics import mean, median

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.holding import Holding
from app.models.transaction import Transaction

logger = logging.getLogger(__name__)

# Detection parameters
_AMOUNT_TOLERANCE_PCT: float = 0.10  # 10 %
_INTERVAL_TOLERANCE_DAYS: int = 5  # absolute floor for the interval tolerance
_INTERVAL_REL_TOLERANCE: float = 0.25  # 25 % of the median gap
_MIN_OCCURRENCES: int = 3  # need at least 3 transactions to call it recurring


# ---------------------------------------------------------------------------
# Core detection
# ---------------------------------------------------------------------------

def _amounts_similar(amounts: list[float]) -> bool:
    """Return True if all amounts are within 10 % of the median."""
    if not amounts:
        return False
    med = median(amounts)
    if med == 0:
        return False
    return all(abs(a - med) / med <= _AMOUNT_TOLERANCE_PCT for a in amounts)


def _intervals_regular(dates: list[date]) -> tuple[bool, float]:
    """Check whether the gaps between sorted dates follow one regular cadence.

    The dominant cadence is taken from the MEDIAN gap (robust to a single
    outlier), and the series is "regular" when every gap lies within a relative
    tolerance of that median — 25 %, but never tighter than 5 days. This lets
    weekly (~7d), bi-weekly (~14d), monthly (~30d) and quarterly (~91d) SIPs all
    qualify, whereas the old fixed 30±5-day rule only ever matched monthly.

    Returns ``(is_regular, avg_interval_days)``.
    """
    if len(dates) < 2:
        return False, 0.0

    intervals = [
        (dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)
    ]

    med = median(intervals)
    if med <= 0:
        return False, 0.0

    tolerance = max(float(_INTERVAL_TOLERANCE_DAYS), med * _INTERVAL_REL_TOLERANCE)
    regular = all(abs(iv - med) <= tolerance for iv in intervals)

    return regular, round(mean(intervals), 1)


def _classify_frequency(avg_interval: float) -> str:
    """Human-readable frequency label."""
    if avg_interval <= 0:
        return "unknown"
    if abs(avg_interval - 7) <= 2:
        return "weekly"
    if abs(avg_interval - 14) <= 3:
        return "bi-weekly"
    if abs(avg_interval - 30) <= 7:
        return "monthly"
    if abs(avg_interval - 90) <= 15:
        return "quarterly"
    return f"~{int(avg_interval)} days"


async def detect_recurring(
    portfolio_id: int,
    db: AsyncSession,
) -> list[dict]:
    """Detect recurring (SIP) transaction patterns in a portfolio.

    Returns a list of dicts::

        {
            "holding_id": 42,
            "stock_symbol": "HDFCBANK",
            "stock_name": "HDFC Bank",
            "exchange": "NSE",
            "transaction_type": "BUY",
            "avg_amount": 5000.0,
            "avg_quantity": 2.5,
            "frequency": "monthly",
            "avg_interval_days": 30.5,
            "occurrences": 6,
            "last_date": "2026-01-15",
            "next_expected_date": "2026-02-14",
        }
    """
    # Fetch all holdings in the portfolio
    h_result = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio_id)
    )
    holdings = {h.id: h for h in h_result.scalars().all()}

    if not holdings:
        return []

    # Fetch all transactions for these holdings
    tx_result = await db.execute(
        select(Transaction)
        .where(Transaction.holding_id.in_(list(holdings.keys())))
        .order_by(Transaction.date.asc())
    )
    transactions = list(tx_result.scalars().all())

    # Group by (holding_id, transaction_type)
    groups: dict[tuple[int, str], list[Transaction]] = defaultdict(list)
    for tx in transactions:
        groups[(tx.holding_id, tx.transaction_type)].append(tx)

    detected: list[dict] = []

    for (holding_id, tx_type), txns in groups.items():
        if len(txns) < _MIN_OCCURRENCES:
            continue

        amounts = [float(tx.quantity) * float(tx.price) for tx in txns]
        quantities = [float(tx.quantity) for tx in txns]
        dates = sorted(tx.date for tx in txns)

        if not _amounts_similar(amounts):
            continue

        is_regular, avg_interval = _intervals_regular(dates)
        if not is_regular:
            continue

        holding = holdings[holding_id]
        last_date = dates[-1]
        next_expected = last_date + timedelta(days=round(avg_interval))

        detected.append(
            {
                "holding_id": holding_id,
                "stock_symbol": holding.stock_symbol,
                "stock_name": holding.stock_name,
                "exchange": holding.exchange,
                "transaction_type": tx_type,
                "avg_amount": round(mean(amounts), 2),
                "avg_quantity": round(mean(quantities), 4),
                "frequency": _classify_frequency(avg_interval),
                "avg_interval_days": avg_interval,
                "occurrences": len(txns),
                "last_date": last_date.isoformat(),
                "next_expected_date": next_expected.isoformat(),
            }
        )

    return detected
