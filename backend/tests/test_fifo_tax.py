"""Tests for per-lot FIFO capital-gains tax computation.

Exercises ``compute_tax_for_transaction`` against the in-memory SQLite DB from
conftest.py, driving the service directly with ORM-created holdings and
transactions (no HTTP layer, no auth needed since ownership is verified by
portfolio.user_id).

Run with:
    uv run pytest tests/test_fifo_tax.py -q
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.transaction import Transaction
from app.models.user import User
from app.services.tax_service import compute_tax_for_transaction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Sale date and buy dates chosen so the "old" lot is comfortably > 12 calendar
# months before the sale and the "recent" lot is comfortably < 12 months.
SALE_DATE = date(2026, 5, 1)
OLD_BUY_DATE = date(2024, 1, 10)   # > 12 months before SALE_DATE -> LTCG
RECENT_BUY_DATE = date(2026, 3, 1)  # < 12 months before SALE_DATE -> STCG


async def _make_user(db: AsyncSession, email: str = "fifo@example.com") -> User:
    user = User(email=email, password_hash="x", display_name="FIFO Tester")
    db.add(user)
    await db.flush()
    return user


async def _make_holding(
    db: AsyncSession,
    user: User,
    *,
    exchange: str = "NSE",
    avg_price: float = 300.0,
    quantity: float = 10.0,
) -> Holding:
    portfolio = Portfolio(user_id=user.id, name="FIFO Portfolio", currency="INR")
    db.add(portfolio)
    await db.flush()

    holding = Holding(
        portfolio_id=portfolio.id,
        stock_symbol="RELIANCE",
        stock_name="Reliance Industries",
        exchange=exchange,
        currency="INR",
        cumulative_quantity=quantity,
        average_price=avg_price,
    )
    db.add(holding)
    await db.flush()
    return holding


async def _add_txn(
    db: AsyncSession,
    holding: Holding,
    *,
    txn_type: str,
    txn_date: date,
    quantity: float,
    price: float,
) -> Transaction:
    txn = Transaction(
        holding_id=holding.id,
        transaction_type=txn_type,
        date=txn_date,
        quantity=quantity,
        price=price,
    )
    db.add(txn)
    await db.flush()
    return txn


def _by_type(records: list, gain_type: str):
    matches = [r for r in records if r.gain_type == gain_type]
    assert len(matches) == 1, f"expected exactly one {gain_type} record, got {len(matches)}"
    return matches[0]


# ---------------------------------------------------------------------------
# Mixed SELL: straddles the STCG/LTCG boundary -> two records
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mixed_sell_produces_stcg_and_ltcg_records(db: AsyncSession):
    """buy 10@100 (old, LTCG lot) + buy 10@500 (recent, STCG lot), SELL 15@600.

    FIFO consumes all 10 of the old 100 lot (LTCG) then 5 of the recent 500 lot
    (STCG), producing two records:
      LTCG: (600-100)*10 = 5000 gain
      STCG: (600-500)*5  = 500 gain
    """
    user = await _make_user(db)
    holding = await _make_holding(db, user)

    await _add_txn(db, holding, txn_type="BUY", txn_date=OLD_BUY_DATE, quantity=10, price=100)
    await _add_txn(db, holding, txn_type="BUY", txn_date=RECENT_BUY_DATE, quantity=10, price=500)
    sell = await _add_txn(
        db, holding, txn_type="SELL", txn_date=SALE_DATE, quantity=15, price=600
    )

    records = await compute_tax_for_transaction(sell.id, user.id, db)

    assert len(records) == 2

    ltcg = _by_type(records, "LTCG")
    assert float(ltcg.gain_amount) == 5000.0
    assert float(ltcg.purchase_price) == 1000.0   # 100 * 10
    assert float(ltcg.sale_price) == 6000.0        # 600 * 10
    assert ltcg.purchase_date == OLD_BUY_DATE
    assert ltcg.sale_date == SALE_DATE
    assert ltcg.tax_jurisdiction == "IN"
    # 5000 LTCG is within the Rs 1.25L exemption -> no tax.
    assert float(ltcg.tax_amount) == 0.0

    stcg = _by_type(records, "STCG")
    assert float(stcg.gain_amount) == 500.0
    assert float(stcg.purchase_price) == 2500.0    # 500 * 5
    assert float(stcg.sale_price) == 3000.0         # 600 * 5
    assert stcg.purchase_date == RECENT_BUY_DATE
    # STCG taxed at 20% flat -> 100.
    assert float(stcg.tax_amount) == 100.0


# ---------------------------------------------------------------------------
# Pure LTCG
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pure_ltcg_sell(db: AsyncSession):
    """buy 10@100 (old), SELL 5@300 -> a single LTCG record, gain 1000."""
    user = await _make_user(db)
    holding = await _make_holding(db, user)

    await _add_txn(db, holding, txn_type="BUY", txn_date=OLD_BUY_DATE, quantity=10, price=100)
    sell = await _add_txn(
        db, holding, txn_type="SELL", txn_date=SALE_DATE, quantity=5, price=300
    )

    records = await compute_tax_for_transaction(sell.id, user.id, db)

    assert len(records) == 1
    rec = records[0]
    assert rec.gain_type == "LTCG"
    assert float(rec.gain_amount) == 1000.0   # (300-100)*5
    assert float(rec.purchase_price) == 500.0  # 100 * 5
    assert float(rec.sale_price) == 1500.0     # 300 * 5
    assert rec.purchase_date == OLD_BUY_DATE
    assert float(rec.tax_amount) == 0.0        # within exemption


# ---------------------------------------------------------------------------
# Pure STCG
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pure_stcg_sell(db: AsyncSession):
    """buy 10@500 (recent), SELL 5@600 -> a single STCG record, gain 500."""
    user = await _make_user(db)
    holding = await _make_holding(db, user)

    await _add_txn(db, holding, txn_type="BUY", txn_date=RECENT_BUY_DATE, quantity=10, price=500)
    sell = await _add_txn(
        db, holding, txn_type="SELL", txn_date=SALE_DATE, quantity=5, price=600
    )

    records = await compute_tax_for_transaction(sell.id, user.id, db)

    assert len(records) == 1
    rec = records[0]
    assert rec.gain_type == "STCG"
    assert float(rec.gain_amount) == 500.0     # (600-500)*5
    assert float(rec.purchase_price) == 2500.0  # 500 * 5
    assert float(rec.sale_price) == 3000.0      # 600 * 5
    assert rec.purchase_date == RECENT_BUY_DATE
    assert float(rec.tax_amount) == 100.0       # 20% of 500


# ---------------------------------------------------------------------------
# Idempotent recompute — recomputing replaces, never duplicates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recompute_is_idempotent(db: AsyncSession):
    """Recomputing the same mixed SELL replaces its records, not appends them."""
    user = await _make_user(db)
    holding = await _make_holding(db, user)

    await _add_txn(db, holding, txn_type="BUY", txn_date=OLD_BUY_DATE, quantity=10, price=100)
    await _add_txn(db, holding, txn_type="BUY", txn_date=RECENT_BUY_DATE, quantity=10, price=500)
    sell = await _add_txn(
        db, holding, txn_type="SELL", txn_date=SALE_DATE, quantity=15, price=600
    )

    first = await compute_tax_for_transaction(sell.id, user.id, db)
    second = await compute_tax_for_transaction(sell.id, user.id, db)

    from sqlalchemy import select
    from app.models.tax_record import TaxRecord

    result = await db.execute(
        select(TaxRecord).where(TaxRecord.transaction_id == sell.id)
    )
    stored = result.scalars().all()

    assert len(first) == 2
    assert len(second) == 2
    # No duplicates accumulated across the two runs.
    assert len(stored) == 2
    # The exemption/Freibetrag netting still holds after replacement.
    ltcg = _by_type(second, "LTCG")
    assert float(ltcg.gain_amount) == 5000.0
    assert float(ltcg.tax_amount) == 0.0
