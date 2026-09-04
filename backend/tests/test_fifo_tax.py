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
    brokerage: float = 0.0,
) -> Transaction:
    txn = Transaction(
        holding_id=holding.id,
        transaction_type=txn_type,
        date=txn_date,
        quantity=quantity,
        price=price,
        brokerage=brokerage,
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


# ===========================================================================
# Brokerage in the cost basis and as an expense of transfer
#
# Design note (this is the ALT-A shape from the plan review, chosen over
# netting brokerage off the proceeds):
#   * ``sale_price``     = GROSS full value of consideration (unchanged), so
#                          ``export_service._record_quantity`` keeps deriving
#                          the ITR quantity correctly for old AND new rows.
#   * ``purchase_price`` = cost of acquisition (incl. the lot's apportioned
#                          PURCHASE brokerage) + the apportioned SALE brokerage
#                          as an expense of transfer.
#   * ``gain_amount``    = sale_price - purchase_price, i.e. net of both.
# ===========================================================================


@pytest.mark.asyncio
async def test_brokerage_reduces_indian_stcg_gain(db: AsyncSession):
    """BUY 100@1000 brk 500, SELL 100@1200 brk 600.

    Economics: 120,000 - 100,000 - 500 - 600 = 18,900, not 20,000.
    """
    user = await _make_user(db, email="brk1@example.com")
    holding = await _make_holding(db, user, avg_price=1000.0, quantity=100.0)

    await _add_txn(
        db, holding, txn_type="BUY", txn_date=date(2025, 9, 1),
        quantity=100, price=1000, brokerage=500,
    )
    sell = await _add_txn(
        db, holding, txn_type="SELL", txn_date=date(2026, 3, 1),
        quantity=100, price=1200, brokerage=600,
    )

    records = await compute_tax_for_transaction(sell.id, user.id, db)

    assert len(records) == 1
    rec = records[0]
    assert rec.gain_type == "STCG"
    # 100*1000 + 500 (purchase brokerage) + 600 (transfer expense)
    assert float(rec.purchase_price) == 101_100.0
    assert float(rec.sale_price) == 120_000.0        # FVC stays GROSS
    assert float(rec.gain_amount) == 18_900.0        # NOT 20,000
    assert float(rec.tax_amount) == 3_780.0          # NOT 4,000


@pytest.mark.asyncio
async def test_brokerage_apportioned_across_multiple_buy_lots(db: AsyncSession):
    """One sale consuming three lots charges each lot only its own share.

    The third lot is HALF consumed, so only 150 of its 300 brokerage lands on
    this sale (3.0/unit x 50).
    """
    user = await _make_user(db, email="brk2@example.com")
    holding = await _make_holding(db, user, avg_price=266.67, quantity=300.0)

    await _add_txn(db, holding, txn_type="BUY", txn_date=date(2023, 1, 10),
                   quantity=100, price=100, brokerage=1000)
    await _add_txn(db, holding, txn_type="BUY", txn_date=date(2023, 6, 10),
                   quantity=100, price=200, brokerage=50)
    await _add_txn(db, holding, txn_type="BUY", txn_date=date(2026, 2, 1),
                   quantity=100, price=500, brokerage=300)
    sell = await _add_txn(db, holding, txn_type="SELL", txn_date=date(2026, 5, 1),
                          quantity=250, price=600, brokerage=1500)

    records = await compute_tax_for_transaction(sell.id, user.id, db)

    ltcg = _by_type(records, "LTCG")
    stcg = _by_type(records, "STCG")

    # (100+10+6)*100 + (200+0.5+6)*100
    assert float(ltcg.purchase_price) == 32_250.0
    assert float(ltcg.sale_price) == 120_000.0
    assert float(ltcg.gain_amount) == 87_750.0

    # (500+3+6)*50 — only HALF of lot 3's 300 brokerage
    assert float(stcg.purchase_price) == 25_450.0
    assert float(stcg.sale_price) == 30_000.0
    assert float(stcg.gain_amount) == 4_550.0
    assert float(stcg.tax_amount) == 910.0           # 20% of 4550

    # Apportionment invariant: nothing lost, nothing double-counted.
    assert sum(float(r.sale_price) for r in records) == pytest.approx(600 * 250)
    assert sum(float(r.purchase_price) for r in records) == pytest.approx(
        55_000.0 + 1_200.0 + 1_500.0
    )
    assert sum(float(r.gain_amount) for r in records) == pytest.approx(92_300.0)


@pytest.mark.asyncio
async def test_consumed_lot_carries_per_unit_buy_brokerage(db: AsyncSession):
    """The FIFO replay itself carries per-unit purchase brokerage on each lot."""
    from sqlalchemy import select

    from app.services.tax_service import _build_consumed_lots

    user = await _make_user(db, email="brk3@example.com")
    holding = await _make_holding(db, user, avg_price=266.67, quantity=300.0)

    await _add_txn(db, holding, txn_type="BUY", txn_date=date(2023, 1, 10),
                   quantity=100, price=100, brokerage=1000)
    await _add_txn(db, holding, txn_type="BUY", txn_date=date(2023, 6, 10),
                   quantity=100, price=200, brokerage=50)
    await _add_txn(db, holding, txn_type="BUY", txn_date=date(2026, 2, 1),
                   quantity=100, price=500, brokerage=300)
    sell = await _add_txn(db, holding, txn_type="SELL", txn_date=date(2026, 5, 1),
                          quantity=250, price=600, brokerage=1500)

    res = await db.execute(
        select(Transaction).where(Transaction.holding_id == holding.id)
    )
    lots = _build_consumed_lots(list(res.scalars().all()), sell.id)

    assert [lot["brokerage_per_unit"] for lot in lots] == [10.0, 0.5, 3.0]
    assert [lot["qty"] for lot in lots] == [100.0, 100.0, 50.0]


@pytest.mark.asyncio
async def test_zero_brokerage_numbers_unchanged(db: AsyncSession):
    """Regression lock: with no brokerage the numbers are byte-identical."""
    user = await _make_user(db, email="brk4@example.com")
    holding = await _make_holding(db, user)

    await _add_txn(db, holding, txn_type="BUY", txn_date=OLD_BUY_DATE, quantity=10, price=100)
    await _add_txn(db, holding, txn_type="BUY", txn_date=RECENT_BUY_DATE, quantity=10, price=500)
    sell = await _add_txn(
        db, holding, txn_type="SELL", txn_date=SALE_DATE, quantity=15, price=600
    )

    records = await compute_tax_for_transaction(sell.id, user.id, db)

    ltcg = _by_type(records, "LTCG")
    assert float(ltcg.purchase_price) == 1000.0
    assert float(ltcg.sale_price) == 6000.0
    assert float(ltcg.gain_amount) == 5000.0
    assert float(ltcg.tax_amount) == 0.0

    stcg = _by_type(records, "STCG")
    assert float(stcg.purchase_price) == 2500.0
    assert float(stcg.sale_price) == 3000.0
    assert float(stcg.gain_amount) == 500.0
    assert float(stcg.tax_amount) == 100.0


@pytest.mark.asyncio
async def test_german_gain_net_of_brokerage(db: AsyncSession):
    """§20(4) EStG: purchase commission is Anschaffungsnebenkosten, sale
    commission a directly-connected transfer cost."""
    user = await _make_user(db, email="brkde@example.com")
    portfolio = Portfolio(user_id=user.id, name="DE", currency="EUR")
    db.add(portfolio)
    await db.flush()
    holding = Holding(
        portfolio_id=portfolio.id,
        stock_symbol="SAP",
        stock_name="SAP SE",
        exchange="XETRA",
        currency="EUR",
        cumulative_quantity=100.0,
        average_price=100.0,
    )
    db.add(holding)
    await db.flush()

    await _add_txn(db, holding, txn_type="BUY", txn_date=date(2025, 1, 10),
                   quantity=100, price=100, brokerage=10)
    sell = await _add_txn(db, holding, txn_type="SELL", txn_date=date(2026, 1, 20),
                          quantity=100, price=220, brokerage=12)

    records = await compute_tax_for_transaction(sell.id, user.id, db)
    assert len(records) == 1
    rec = records[0]
    assert float(rec.purchase_price) == 10_022.0     # 10,000 + 10 + 12
    assert float(rec.sale_price) == 22_000.0
    assert float(rec.gain_amount) == 11_978.0        # NOT 12,000
    # (11,978 - 1,000 Freibetrag) * 25% = 2,744.50 + 5.5% Soli 150.95
    assert float(rec.tax_amount) == 2_895.45


@pytest.mark.asyncio
async def test_grandfathering_keeps_gross_fvc_and_brokerage_in_actual_cost(
    db: AsyncSession, monkeypatch
):
    """s.55(2)(ac): purchase brokerage sits INSIDE the actual-cost arm, the
    FVC arm stays gross, and the sale brokerage is added afterwards."""
    import app.services.tax_service as tax_service

    async def _fmv(symbol: str, exchange: str) -> float | None:
        return 300.0

    monkeypatch.setattr(tax_service, "get_fmv_31jan2018", _fmv)

    user = await _make_user(db, email="brkgf@example.com")
    holding = await _make_holding(db, user, avg_price=100.0, quantity=10.0)
    await _add_txn(db, holding, txn_type="BUY", txn_date=date(2017, 6, 1),
                   quantity=10, price=100, brokerage=50)
    sell = await _add_txn(db, holding, txn_type="SELL", txn_date=date(2026, 5, 1),
                          quantity=10, price=600, brokerage=20)

    rec = (await compute_tax_for_transaction(sell.id, user.id, db))[0]
    # basis = max(100 + 5, min(300, 600)) = 300; + 2/unit transfer expense
    assert float(rec.purchase_price) == 3020.0
    assert float(rec.sale_price) == 6000.0           # FVC stays GROSS
    assert float(rec.gain_amount) == 2980.0


@pytest.mark.asyncio
async def test_grandfathering_falls_back_to_brokerage_inclusive_cost(
    db: AsyncSession, monkeypatch
):
    """An FMV below the actual cost falls back to the brokerage-INCLUSIVE
    actual cost (105/unit), not the raw price."""
    import app.services.tax_service as tax_service

    async def _fmv(symbol: str, exchange: str) -> float | None:
        return 90.0

    monkeypatch.setattr(tax_service, "get_fmv_31jan2018", _fmv)

    user = await _make_user(db, email="brkgf2@example.com")
    holding = await _make_holding(db, user, avg_price=100.0, quantity=10.0)
    await _add_txn(db, holding, txn_type="BUY", txn_date=date(2017, 6, 1),
                   quantity=10, price=100, brokerage=50)
    sell = await _add_txn(db, holding, txn_type="SELL", txn_date=date(2026, 5, 1),
                          quantity=10, price=600, brokerage=20)

    rec = (await compute_tax_for_transaction(sell.id, user.id, db))[0]
    # max(105, min(90, 600)) = 105; + 2/unit -> 107 * 10
    assert float(rec.purchase_price) == 1070.0
    assert float(rec.gain_amount) == 4930.0


@pytest.mark.asyncio
async def test_zero_quantity_buy_does_not_divide_by_zero(db: AsyncSession):
    """Corporate actions inject synthetic zero-quantity BUYs; the per-unit
    apportionment must not blow up on them."""
    user = await _make_user(db, email="brkzero@example.com")
    holding = await _make_holding(db, user, avg_price=100.0, quantity=10.0)

    await _add_txn(db, holding, txn_type="BUY", txn_date=OLD_BUY_DATE,
                   quantity=10, price=100, brokerage=0)
    # Corporate-actions-shaped synthetic row.
    await _add_txn(db, holding, txn_type="BUY", txn_date=date(2026, 4, 1),
                   quantity=0, price=0, brokerage=0)
    sell = await _add_txn(db, holding, txn_type="SELL", txn_date=SALE_DATE,
                          quantity=10, price=300, brokerage=0)

    records = await compute_tax_for_transaction(sell.id, user.id, db)
    assert len(records) == 1
    assert float(records[0].gain_amount) == 2000.0   # (300-100)*10, unchanged


@pytest.mark.asyncio
async def test_partial_match_deducts_only_the_matched_share_of_sale_brokerage(
    db: AsyncSession,
):
    """An oversell books only the matched units' share of the sale brokerage —
    the unmatched units have no recorded gain to deduct it from."""
    user = await _make_user(db, email="brkover@example.com")
    holding = await _make_holding(db, user, avg_price=100.0, quantity=40.0)

    await _add_txn(db, holding, txn_type="BUY", txn_date=RECENT_BUY_DATE,
                   quantity=40, price=100, brokerage=0)
    sell = await _add_txn(db, holding, txn_type="SELL", txn_date=SALE_DATE,
                          quantity=100, price=200, brokerage=1000)

    rec = (await compute_tax_for_transaction(sell.id, user.id, db))[0]
    # 40 matched units x (100 cost + 10 apportioned sale brokerage)
    assert float(rec.purchase_price) == 4400.0
    assert float(rec.sale_price) == 8000.0
    assert float(rec.gain_amount) == 3600.0
