"""Realized losses must set off realized gains, within the year's rules.

India (ss.70/71 with s.112A):
  * STCL sets off against BOTH STCG and LTCG, highest-rate bucket first;
  * a net LTCL sets off ONLY against LTCG — s.70(3) — and may NEVER reach
    STCG. That guard-rail was already right and must stay right;
  * the annual s.112A exemption applies to what survives the set-off.

Germany (§20(6) EStG, §20 InvStG):
  * two Verlustverrechnungstöpfe — share losses only against share gains,
    other losses against any capital income;
  * Teilfreistellung applies to losses as well as gains;
  * set-off happens BEFORE the Sparer-Pauschbetrag, so a year netting to zero
    consumes none of the allowance.

Run with:
    uv run pytest tests/test_loss_offset.py -q
"""

from __future__ import annotations

import itertools
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
    allocate_fy_tax_de,
    allocate_fy_tax_in,
    compute_german_allowance,
    compute_tax_for_transaction,
    generate_tax_summary,
)

# ---------------------------------------------------------------------------
# ORM builders
# ---------------------------------------------------------------------------


async def _make_user(db: AsyncSession, email: str, currency: str = "INR") -> User:
    user = User(
        email=email,
        password_hash="x",
        display_name="Setoff Tester",
        preferred_currency=currency,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_holding(
    db: AsyncSession,
    user: User,
    *,
    symbol: str,
    exchange: str = "NSE",
    currency: str = "INR",
    fund_type: str | None = None,
) -> Holding:
    portfolio = Portfolio(user_id=user.id, name=f"P-{symbol}", currency=currency)
    db.add(portfolio)
    await db.flush()
    holding = Holding(
        portfolio_id=portfolio.id,
        stock_symbol=symbol,
        stock_name=symbol,
        exchange=exchange,
        currency=currency,
        fund_type=fund_type,
        cumulative_quantity=0.0,
        average_price=100.0,
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


async def _trade(
    db: AsyncSession,
    user: User,
    symbol: str,
    *,
    buy_date: date,
    buy_price: float,
    sell_date: date,
    sell_price: float,
    quantity: float = 100.0,
    exchange: str = "NSE",
    currency: str = "INR",
    fund_type: str | None = None,
) -> Transaction:
    """One holding, one BUY and one SELL; returns the SELL transaction."""
    holding = await _make_holding(
        db, user, symbol=symbol, exchange=exchange,
        currency=currency, fund_type=fund_type,
    )
    await _add_txn(db, holding, txn_type="BUY", txn_date=buy_date,
                   quantity=quantity, price=buy_price)
    return await _add_txn(db, holding, txn_type="SELL", txn_date=sell_date,
                          quantity=quantity, price=sell_price)


async def _record_for(db: AsyncSession, sell: Transaction) -> TaxRecord:
    res = await db.execute(
        select(TaxRecord).where(TaxRecord.transaction_id == sell.id)
    )
    return res.scalars().one()


# ===========================================================================
# India
# ===========================================================================


@pytest.mark.asyncio
async def test_stcl_sets_off_stcg(db: AsyncSession):
    """STCL 60,000 then STCG 100,000 -> tax on 40,000, not on 100,000."""
    user = await _make_user(db, "in-stcl@example.com")
    loss = await _trade(db, user, "LOSSCO", buy_date=date(2025, 8, 1),
                        buy_price=1000, sell_date=date(2025, 9, 1), sell_price=400)
    gain = await _trade(db, user, "GAINCO", buy_date=date(2025, 10, 1),
                        buy_price=1000, sell_date=date(2025, 12, 1), sell_price=2000)

    await compute_tax_for_transaction(loss.id, user.id, db)
    await compute_tax_for_transaction(gain.id, user.id, db)

    loss_rec = await _record_for(db, loss)
    gain_rec = await _record_for(db, gain)
    assert float(loss_rec.gain_amount) == -60_000.0
    assert float(loss_rec.tax_amount) == 0.0
    assert float(gain_rec.gain_amount) == 100_000.0
    assert float(gain_rec.tax_amount) == 8_000.0     # 40,000 * 20 %, not 20,000

    summary = await generate_tax_summary(user.id, "2025-26", "IN", db)
    assert summary["total_tax"] == 8_000.0


@pytest.mark.asyncio
async def test_ltcl_sets_off_ltcg_before_the_exemption(db: AsyncSession):
    """LTCL 100,000 + LTCG 200,000 -> net 100,000, fully inside the pool."""
    user = await _make_user(db, "in-ltcl@example.com")
    loss = await _trade(db, user, "LTLOSS", buy_date=date(2023, 1, 10),
                        buy_price=2000, sell_date=date(2025, 9, 1), sell_price=1000)
    gain = await _trade(db, user, "LTGAIN", buy_date=date(2023, 1, 10),
                        buy_price=1000, sell_date=date(2025, 12, 1), sell_price=3000)

    await compute_tax_for_transaction(loss.id, user.id, db)
    await compute_tax_for_transaction(gain.id, user.id, db)

    summary = await generate_tax_summary(user.id, "2025-26", "IN", db)
    assert summary["total_tax"] == 0.0               # was 9,375
    assert summary["exemption_used"] == 100_000.0
    assert float((await _record_for(db, gain)).tax_amount) == 0.0


@pytest.mark.asyncio
async def test_stcl_sets_off_ltcg(db: AsyncSession):
    """A short-term loss may land on a long-term gain (s.70(2))."""
    user = await _make_user(db, "in-stcl-ltcg@example.com")
    loss = await _trade(db, user, "STLOSS", buy_date=date(2025, 8, 1),
                        buy_price=2000, sell_date=date(2025, 9, 1), sell_price=1000)
    gain = await _trade(db, user, "LTGAIN", buy_date=date(2023, 1, 10),
                        buy_price=1000, sell_date=date(2025, 12, 1), sell_price=3000)

    await compute_tax_for_transaction(loss.id, user.id, db)
    await compute_tax_for_transaction(gain.id, user.id, db)

    summary = await generate_tax_summary(user.id, "2025-26", "IN", db)
    assert summary["total_tax"] == 0.0               # 200k - 100k loss - 125k pool


@pytest.mark.asyncio
async def test_later_loss_offsets_earlier_gain(db: AsyncSession):
    """Set-off is ANNUAL: a December loss rewrites a September gain's tax."""
    user = await _make_user(db, "in-later-loss@example.com")
    gain = await _trade(db, user, "GAINCO", buy_date=date(2025, 7, 1),
                        buy_price=1000, sell_date=date(2025, 9, 1), sell_price=2000)
    loss = await _trade(db, user, "LOSSCO", buy_date=date(2025, 10, 1),
                        buy_price=1000, sell_date=date(2025, 12, 1), sell_price=400)

    await compute_tax_for_transaction(gain.id, user.id, db)
    assert float((await _record_for(db, gain)).tax_amount) == 20_000.0

    await compute_tax_for_transaction(loss.id, user.id, db)

    # The STORED record of the earlier sale was rewritten, not just the summary.
    assert float((await _record_for(db, gain)).tax_amount) == 8_000.0
    summary = await generate_tax_summary(user.id, "2025-26", "IN", db)
    assert summary["total_tax"] == 8_000.0


@pytest.mark.asyncio
async def test_ltcl_does_not_offset_stcg(db: AsyncSession):
    """s.70(3) guard-rail: a net long-term LOSS may not touch short-term gains."""
    user = await _make_user(db, "in-70-3@example.com")
    loss = await _trade(db, user, "LTLOSS", buy_date=date(2023, 1, 10),
                        buy_price=3000, sell_date=date(2025, 9, 1), sell_price=1000)
    gain = await _trade(db, user, "STGAIN", buy_date=date(2025, 10, 1),
                        buy_price=1000, sell_date=date(2025, 12, 1), sell_price=2000)

    await compute_tax_for_transaction(loss.id, user.id, db)
    await compute_tax_for_transaction(gain.id, user.id, db)

    assert float((await _record_for(db, loss)).gain_amount) == -200_000.0
    summary = await generate_tax_summary(user.id, "2025-26", "IN", db)
    assert summary["total_tax"] == 20_000.0          # must NOT become 0


async def _stcl_stcg_ltcg_year(db: AsyncSession, user: User):
    """STCL -100,000 (Jul), LTCG +200,000 (Sep), STCG +60,000 (Dec)."""
    stcl = await _trade(db, user, "STLOSS", buy_date=date(2025, 6, 1),
                        buy_price=2000, sell_date=date(2025, 7, 1), sell_price=1000)
    ltcg = await _trade(db, user, "LTGAIN", buy_date=date(2023, 1, 10),
                        buy_price=1000, sell_date=date(2025, 9, 1), sell_price=3000)
    stcg = await _trade(db, user, "STGAIN", buy_date=date(2025, 8, 1),
                        buy_price=1000, sell_date=date(2025, 12, 1), sell_price=1600)
    return stcl, ltcg, stcg


@pytest.mark.asyncio
async def test_stcl_prefers_stcg_over_ltcg(db: AsyncSession):
    """The STCL pool is spent on the 20 % bucket before the 12.5 % one.

    Chronologically the LTCG comes first and a naive pass would spend the loss
    there, leaving 60,000 of STCG taxed at 20 % = 12,000. Spending it on the
    STCG first leaves 160,000 of LTCG, of which 125,000 is exempt: 4,375.
    """
    user = await _make_user(db, "in-s10@example.com")
    stcl, ltcg, stcg = await _stcl_stcg_ltcg_year(db, user)
    for sell in (stcl, ltcg, stcg):
        await compute_tax_for_transaction(sell.id, user.id, db)

    assert float((await _record_for(db, stcg)).tax_amount) == 0.0
    assert float((await _record_for(db, ltcg)).tax_amount) == 4_375.0
    summary = await generate_tax_summary(user.id, "2025-26", "IN", db)
    assert summary["total_tax"] == 4_375.0           # a naive pass gives 12,000


@pytest.mark.asyncio
async def test_loss_offset_is_compute_order_independent(db: AsyncSession):
    """Every order of computing the same three sales gives the same year."""
    for n, order in enumerate(itertools.permutations(range(3))):
        user = await _make_user(db, f"in-order{n}@example.com")
        sells = await _stcl_stcg_ltcg_year(db, user)
        for idx in order:
            await compute_tax_for_transaction(sells[idx].id, user.id, db)
        summary = await generate_tax_summary(user.id, "2025-26", "IN", db)
        assert summary["total_tax"] == 4_375.0, f"order {order}"
        assert summary["exemption_used"] == 125_000.0, f"order {order}"


@pytest.mark.asyncio
async def test_no_losses_regression(db: AsyncSession):
    """With no losses the allocation is exactly what it always was."""
    user = await _make_user(db, "in-noloss@example.com")
    holding = await _make_holding(db, user, symbol="RELIANCE")
    await _add_txn(db, holding, txn_type="BUY", txn_date=date(2023, 1, 10),
                   quantity=200, price=100)
    sell_a = await _add_txn(db, holding, txn_type="SELL", txn_date=date(2025, 6, 1),
                            quantity=100, price=1100)
    sell_b = await _add_txn(db, holding, txn_type="SELL", txn_date=date(2025, 8, 1),
                            quantity=100, price=1100)

    await compute_tax_for_transaction(sell_a.id, user.id, db)
    await compute_tax_for_transaction(sell_b.id, user.id, db)

    assert float((await _record_for(db, sell_a)).tax_amount) == 0.0
    assert float((await _record_for(db, sell_b)).tax_amount) == 9_375.0
    summary = await generate_tax_summary(user.id, "2025-26", "IN", db)
    assert summary["total_tax"] == 9_375.0


# ===========================================================================
# Germany
# ===========================================================================


@pytest.mark.asyncio
async def test_de_share_loss_offsets_share_gain(db: AsyncSession):
    user = await _make_user(db, "de-share@example.com", currency="EUR")
    loss = await _trade(db, user, "BAYER", buy_date=date(2020, 1, 1),
                        buy_price=100, sell_date=date(2024, 3, 1), sell_price=60,
                        exchange="XETRA", currency="EUR", fund_type="STOCK")
    gain = await _trade(db, user, "SAP", buy_date=date(2020, 1, 1),
                        buy_price=100, sell_date=date(2024, 6, 1), sell_price=140,
                        exchange="XETRA", currency="EUR", fund_type="STOCK")

    await compute_tax_for_transaction(loss.id, user.id, db)
    await compute_tax_for_transaction(gain.id, user.id, db)

    assert float((await _record_for(db, loss)).gain_amount) == -4_000.0
    summary = await generate_tax_summary(user.id, "2024", "DE", db)
    assert summary["total_tax"] == 0.0               # was 791.25


@pytest.mark.asyncio
async def test_de_fund_loss_offsets_fund_gain_after_teilfreistellung(db: AsyncSession):
    """Teilfreistellung applies to the loss too, so 7,000 nets 7,000."""
    user = await _make_user(db, "de-fund@example.com", currency="EUR")
    loss = await _trade(db, user, "EMIM", buy_date=date(2020, 1, 1),
                        buy_price=200, sell_date=date(2024, 3, 1), sell_price=100,
                        exchange="XETRA", currency="EUR", fund_type="EQUITY_ETF")
    gain = await _trade(db, user, "IWDA", buy_date=date(2020, 1, 1),
                        buy_price=100, sell_date=date(2024, 6, 1), sell_price=200,
                        exchange="XETRA", currency="EUR", fund_type="EQUITY_ETF")

    await compute_tax_for_transaction(loss.id, user.id, db)
    await compute_tax_for_transaction(gain.id, user.id, db)

    summary = await generate_tax_summary(user.id, "2024", "DE", db)
    assert summary["total_tax"] == 0.0               # was 1,582.50


@pytest.mark.asyncio
async def test_de_net_loss_does_not_consume_freibetrag(db: AsyncSession):
    """A year that nets to a loss spends none of the Sparer-Pauschbetrag."""
    user = await _make_user(db, "de-netloss@example.com", currency="EUR")
    loss = await _trade(db, user, "BAYER", buy_date=date(2020, 1, 1),
                        buy_price=200, sell_date=date(2024, 3, 1), sell_price=100,
                        exchange="XETRA", currency="EUR", fund_type="STOCK")
    gain = await _trade(db, user, "SAP", buy_date=date(2020, 1, 1),
                        buy_price=100, sell_date=date(2024, 6, 1), sell_price=140,
                        exchange="XETRA", currency="EUR", fund_type="STOCK")

    await compute_tax_for_transaction(loss.id, user.id, db)
    await compute_tax_for_transaction(gain.id, user.id, db)

    summary = await generate_tax_summary(user.id, "2024", "DE", db)
    assert summary["total_tax"] == 0.0
    allowance = await compute_german_allowance(user.id, "2024", db)
    assert allowance["used"] == 0.0
    assert allowance["remaining"] == 1000.0


@pytest.mark.asyncio
async def test_de_share_loss_cannot_offset_fund_gain(db: AsyncSession):
    """§20(6) Satz 4: the Aktien pot is sealed off from fund income."""
    user = await _make_user(db, "de-pots@example.com", currency="EUR")
    loss = await _trade(db, user, "BAYER", buy_date=date(2020, 1, 1),
                        buy_price=100, sell_date=date(2024, 3, 1), sell_price=60,
                        exchange="XETRA", currency="EUR", fund_type="STOCK")
    gain = await _trade(db, user, "IWDA", buy_date=date(2020, 1, 1),
                        buy_price=100, sell_date=date(2024, 6, 1), sell_price=140,
                        exchange="XETRA", currency="EUR", fund_type="EQUITY_ETF")

    await compute_tax_for_transaction(loss.id, user.id, db)
    await compute_tax_for_transaction(gain.id, user.id, db)

    # ETF gain 4,000 -> 30 % Teilfreistellung -> 2,800; less the EUR 1,000
    # Freibetrag -> 1,800 taxable -> 450 KapESt + 24.75 Soli.
    summary = await generate_tax_summary(user.id, "2024", "DE", db)
    assert summary["total_tax"] == 474.75            # must NOT be 0


@pytest.mark.asyncio
async def test_de_no_loss_regression(db: AsyncSession):
    """A lone share gain is taxed exactly as before."""
    user = await _make_user(db, "de-noloss@example.com", currency="EUR")
    gain = await _trade(db, user, "SAP", buy_date=date(2020, 1, 1),
                        buy_price=100, sell_date=date(2024, 6, 1), sell_price=140,
                        exchange="XETRA", currency="EUR", fund_type="STOCK")
    await compute_tax_for_transaction(gain.id, user.id, db)
    assert float((await _record_for(db, gain)).tax_amount) == 791.25


@pytest.mark.asyncio
async def test_de_unclassified_holdings_fall_back_to_one_pot(db: AsyncSession):
    """``fund_type`` is unset by default, so the pot split is not guessed.

    An unclassified position may be a share or an ETF; blocking a legal
    Sonstige offset and inventing an illegal Aktien one are both real
    mis-charges, so such a year is allocated with a single pot.
    """
    user = await _make_user(db, "de-unclassified@example.com", currency="EUR")
    loss = await _trade(db, user, "MYSTERY", buy_date=date(2020, 1, 1),
                        buy_price=100, sell_date=date(2024, 3, 1), sell_price=60,
                        exchange="XETRA", currency="EUR", fund_type=None)
    gain = await _trade(db, user, "IWDA", buy_date=date(2020, 1, 1),
                        buy_price=100, sell_date=date(2024, 6, 1), sell_price=140,
                        exchange="XETRA", currency="EUR", fund_type="EQUITY_ETF")

    await compute_tax_for_transaction(loss.id, user.id, db)
    await compute_tax_for_transaction(gain.id, user.id, db)

    summary = await generate_tax_summary(user.id, "2024", "DE", db)
    assert summary["total_tax"] == 0.0               # -4,000 vs +2,800


# ===========================================================================
# Pure-unit allocator tests (no DB)
# ===========================================================================


def _in_row(key, gain_type, gain, sale_date, txn_id=None):
    return {
        "key": key,
        "gain_type": gain_type,
        "gain": gain,
        "sale_date": sale_date,
        "transaction_id": txn_id,
    }


def test_allocate_fy_tax_in_prefers_the_higher_rate_bucket():
    rows = [
        _in_row(0, "STCG", -100_000.0, date(2025, 7, 1), 1),
        _in_row(1, "LTCG", 200_000.0, date(2025, 9, 1), 2),
        _in_row(2, "STCG", 60_000.0, date(2025, 12, 1), 3),
    ]
    out = allocate_fy_tax_in(rows, "2025-26")
    assert out["tax_by_key"] == {0: 0.0, 1: 4_375.0, 2: 0.0}
    assert out["total_tax"] == 4_375.0
    assert out["exemption_used"] == 125_000.0
    assert out["unabsorbed_stcl"] == 0.0


def test_allocate_fy_tax_in_never_lets_ltcl_reach_stcg():
    rows = [
        _in_row(0, "LTCG", -200_000.0, date(2025, 9, 1), 1),
        _in_row(1, "STCG", 100_000.0, date(2025, 12, 1), 2),
    ]
    out = allocate_fy_tax_in(rows, "2025-26")
    assert out["tax_by_key"] == {0: 0.0, 1: 20_000.0}
    # The unused long-term loss is reported, not silently claimed as spent.
    assert out["unabsorbed_ltcl"] == 200_000.0


def test_allocate_fy_tax_in_is_rate_aware_across_the_2024_cutover():
    """FY 2024-25 straddles 23-Jul-2024: the STCL is worth 20 %, not 15 %."""
    rows = [
        _in_row(0, "STCG", -100_000.0, date(2024, 5, 10), 1),
        _in_row(1, "STCG", 100_000.0, date(2024, 5, 10), 2),   # 15 % slice
        _in_row(2, "STCG", 100_000.0, date(2024, 9, 15), 3),   # 20 % slice
    ]
    out = allocate_fy_tax_in(rows, "2024-25")
    # The loss lands on the 20 % row; the 15 % row survives and pays 15,000.
    assert out["tax_by_key"] == {0: 0.0, 1: 15_000.0, 2: 0.0}
    assert out["total_tax"] == 15_000.0


def test_allocate_fy_tax_in_handles_null_dates_and_empty_years():
    assert allocate_fy_tax_in([], "2025-26")["total_tax"] == 0.0
    rows = [_in_row(0, "LTCG", None, None), _in_row(1, "STCG", 10_000.0, None)]
    out = allocate_fy_tax_in(rows, "2025-26")
    assert out["tax_by_key"] == {0: 0.0, 1: 2_000.0}


def _de_row(key, gain, teil_pct, pot, sale_date, txn_id=None):
    return {
        "key": key,
        "gain": gain,
        "teil_pct": teil_pct,
        "pot": pot,
        "sale_date": sale_date,
        "transaction_id": txn_id,
    }


def test_allocate_fy_tax_de_keeps_the_two_pots_apart():
    rows = [
        _de_row(0, -4_000.0, 0.0, "SHARE", date(2024, 3, 1), 1),
        _de_row(1, 4_000.0, 30.0, "OTHER", date(2024, 6, 1), 2),
    ]
    out = allocate_fy_tax_de(rows, total_freibetrag=1000.0)
    assert out["two_pot"] is True
    assert out["tax_by_key"] == {0: 0.0, 1: 474.75}
    assert out["unabsorbed_share_loss"] == 4_000.0


def test_allocate_fy_tax_de_lets_other_losses_cover_share_gains():
    rows = [
        _de_row(0, -4_000.0, 0.0, "OTHER", date(2024, 3, 1), 1),
        _de_row(1, 4_000.0, 0.0, "SHARE", date(2024, 6, 1), 2),
    ]
    out = allocate_fy_tax_de(rows, total_freibetrag=1000.0)
    assert out["tax_by_key"] == {0: 0.0, 1: 0.0}
    assert out["allowance_used"] == 0.0


def test_allocate_fy_tax_de_falls_back_to_one_pot_when_unclassified():
    rows = [
        _de_row(0, -4_000.0, 0.0, None, date(2024, 3, 1), 1),
        _de_row(1, 4_000.0, 30.0, "OTHER", date(2024, 6, 1), 2),
    ]
    out = allocate_fy_tax_de(rows, total_freibetrag=1000.0)
    assert out["two_pot"] is False
    assert out["total_tax"] == 0.0


def test_allocate_fy_tax_de_dividends_consume_the_allowance_first():
    rows = [_de_row(0, 1_000.0, 0.0, "SHARE", date(2024, 6, 1), 1)]
    out = allocate_fy_tax_de(rows, total_freibetrag=1000.0, dividends_used=1200.0)
    assert out["tax_by_key"] == {0: 263.75}


# ===========================================================================
# Records this service did not compute
# ===========================================================================


@pytest.mark.asyncio
async def test_imported_record_consumes_exemption_but_keeps_its_own_tax(
    db: AsyncSession,
):
    """A CSV-imported / restored / orphaned row is a real disposal.

    Its gain consumes the annual s.112A pool, so a later engine-computed sale
    is taxed on the remainder — but its own ``tax_amount`` came from the
    user's statement and must not be restated by our model.
    """
    user = await _make_user(db, "in-imported@example.com")
    db.add(
        TaxRecord(
            user_id=user.id,
            transaction_id=None,
            financial_year="2025-26",
            tax_jurisdiction="IN",
            gain_type="LTCG",
            purchase_date=date(2022, 1, 10),
            sale_date=date(2025, 6, 10),
            purchase_price=400_000.0,
            sale_price=500_000.0,
            gain_amount=100_000.0,
            tax_amount=4_242.0,          # the user's own figure
            currency="INR",
        )
    )
    await db.flush()

    sell = await _trade(db, user, "LTGAIN", buy_date=date(2023, 1, 10),
                        buy_price=1000, sell_date=date(2025, 11, 20), sell_price=2000)
    records = await compute_tax_for_transaction(sell.id, user.id, db)

    assert float(records[0].gain_amount) == 100_000.0
    # 25,000 of pool left after the imported disposal -> 75,000 at 12.5 %.
    assert float(records[0].tax_amount) == 9_375.0

    imported = (
        await db.execute(
            select(TaxRecord).where(
                TaxRecord.user_id == user.id,
                TaxRecord.transaction_id.is_(None),
            )
        )
    ).scalars().one()
    assert float(imported.tax_amount) == 4_242.0     # untouched


@pytest.mark.asyncio
async def test_imported_loss_still_offsets_an_engine_gain(db: AsyncSession):
    """An orphaned loss row carries a real loss, so it still feeds the pool."""
    user = await _make_user(db, "in-imported-loss@example.com")
    db.add(
        TaxRecord(
            user_id=user.id,
            transaction_id=None,
            financial_year="2025-26",
            tax_jurisdiction="IN",
            gain_type="STCG",
            purchase_date=date(2025, 5, 1),
            sale_date=date(2025, 6, 10),
            purchase_price=160_000.0,
            sale_price=100_000.0,
            gain_amount=-60_000.0,
            tax_amount=0.0,
            currency="INR",
        )
    )
    await db.flush()

    sell = await _trade(db, user, "STGAIN", buy_date=date(2025, 10, 1),
                        buy_price=1000, sell_date=date(2025, 12, 1), sell_price=2000)
    records = await compute_tax_for_transaction(sell.id, user.id, db)
    assert float(records[0].tax_amount) == 8_000.0   # (100,000 - 60,000) * 20 %
