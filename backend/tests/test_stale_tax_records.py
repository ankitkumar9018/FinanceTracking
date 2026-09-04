"""TaxRecords must never outlive the ledger they were derived from.

A TaxRecord is a DERIVED artifact of one SELL replayed against its holding's
FIFO ledger. Editing or deleting any transaction changes that ledger, so the
records derived from it must be re-derived or destroyed.

Before this fix neither happened:
  * correcting a sale's price left the OLD tax figure standing in /tax/summary
    and in the ITR-ready capital-gains export;
  * deleting a sale left a ghost record — TaxRecord.transaction_id is
    ondelete=SET NULL — which kept consuming the annual exemption forever.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.tax_record import TaxRecord
from app.models.transaction import Transaction
from app.models.user import User
from app.services.tax_service import (
    compute_tax_for_transaction,
    recompute_tax_after_ledger_change,
    snapshot_tax_anchors,
)

BUY_DATE = date(2025, 4, 10)
SELL_DATE = date(2025, 9, 1)


async def _seed(db: AsyncSession) -> tuple[User, Holding, Transaction]:
    user = User(email="stale@example.com", password_hash="x", display_name="Stale")
    db.add(user)
    await db.flush()
    portfolio = Portfolio(user_id=user.id, name="P", currency="INR")
    db.add(portfolio)
    await db.flush()
    holding = Holding(
        portfolio_id=portfolio.id, stock_symbol="RELIANCE", stock_name="Reliance",
        exchange="NSE", currency="INR", cumulative_quantity=100.0, average_price=1000.0,
    )
    db.add(holding)
    await db.flush()
    db.add(Transaction(
        holding_id=holding.id, transaction_type="BUY", date=BUY_DATE,
        quantity=100.0, price=1000.0,
    ))
    sell = Transaction(
        holding_id=holding.id, transaction_type="SELL", date=SELL_DATE,
        quantity=100.0, price=1500.0,
    )
    db.add(sell)
    await db.flush()
    return user, holding, sell


async def _records(db: AsyncSession, user: User) -> list[TaxRecord]:
    res = await db.execute(select(TaxRecord).where(TaxRecord.user_id == user.id))
    return list(res.scalars().all())


@pytest.mark.asyncio
async def test_editing_a_sale_re_derives_its_tax_record(db: AsyncSession):
    """Correcting the sale price must update the stored gain, not leave it."""
    user, holding, sell = await _seed(db)
    await compute_tax_for_transaction(sell.id, user.id, db)

    before = await _records(db, user)
    assert len(before) == 1
    assert float(before[0].gain_amount) == pytest.approx(50_000.0)  # (1500-1000)*100

    # The user corrects the price: it was 1,200, not 1,500.
    anchors = await snapshot_tax_anchors(holding.id, user.id, db)
    assert anchors, "a computed sale must produce an anchor"
    sell.price = 1200.0
    await db.flush()
    await recompute_tax_after_ledger_change(anchors, user.id, db)

    after = await _records(db, user)
    assert len(after) == 1, "the edit must not duplicate the record"
    assert float(after[0].gain_amount) == pytest.approx(20_000.0)  # (1200-1000)*100


@pytest.mark.asyncio
async def test_deleting_a_sale_removes_its_tax_record(db: AsyncSession):
    """No ghost record may survive the sale it was derived from."""
    user, holding, sell = await _seed(db)
    await compute_tax_for_transaction(sell.id, user.id, db)
    assert len(await _records(db, user)) == 1

    # Records must be dropped while the FK still points at the transaction.
    anchors = await snapshot_tax_anchors(
        holding.id, user.id, db, dropping_transaction_id=sell.id
    )
    await db.delete(sell)
    await db.flush()
    await recompute_tax_after_ledger_change(anchors, user.id, db)

    remaining = await _records(db, user)
    assert remaining == [], f"ghost tax records survived: {remaining}"


@pytest.mark.asyncio
async def test_deleted_sale_stops_consuming_the_exemption(db: AsyncSession):
    """The ghost's real damage: it kept eating the Rs 1.25L LTCG exemption."""
    user, holding, sell = await _seed(db)
    await compute_tax_for_transaction(sell.id, user.id, db)
    fy = (await _records(db, user))[0].financial_year

    anchors = await snapshot_tax_anchors(
        holding.id, user.id, db, dropping_transaction_id=sell.id
    )
    await db.delete(sell)
    await db.flush()
    await recompute_tax_after_ledger_change(anchors, user.id, db)

    res = await db.execute(
        select(TaxRecord).where(
            TaxRecord.user_id == user.id, TaxRecord.financial_year == fy
        )
    )
    assert list(res.scalars().all()) == []


@pytest.mark.asyncio
async def test_routes_are_wired_to_the_invalidation(db: AsyncSession):
    """The fix is worthless if the routes don't call it."""
    import inspect

    from app.api.v1 import transactions as tx_routes

    for fn in (tx_routes.update_transaction, tx_routes.delete_transaction):
        src = inspect.getsource(fn)
        assert "snapshot_tax_anchors" in src, f"{fn.__name__} takes no snapshot"
        assert "recompute_tax_after_ledger_change" in src, (
            f"{fn.__name__} never re-derives tax"
        )
    # Delete must drop records while the FK still points at the transaction.
    assert "dropping_transaction_id" in inspect.getsource(tx_routes.delete_transaction)
