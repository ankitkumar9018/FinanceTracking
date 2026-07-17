"""Tests for advanced tax features:

1. Indian LTCG grandfathering (31-Jan-2018 fair-market-value cost basis)
2. German Teilfreistellung (fund partial exemption)
3. German Vorabpauschale (advance lump-sum tax estimate)
4. German Sparer-Pauschbetrag allowance tracker (single vs joint)

Exercises the tax service directly against the in-memory SQLite DB from
conftest.py, following the ORM-driven pattern of test_fifo_tax.py. The
31-Jan-2018 FMV lookup (yfinance / network) is monkeypatched so the tests are
deterministic and offline.

Run with:
    uv run pytest tests/test_tax_advanced.py -q
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.tax_service as tax_service
from app.models.dividend import Dividend
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.tax_record import TaxRecord
from app.models.user import User
from app.models.user_preferences import UserPreferences
from app.services.tax_service import (
    basiszins_for_year,
    calculate_german_tax,
    compute_german_allowance,
    compute_tax_for_transaction,
    compute_vorabpauschale,
    teilfreistellung_for_fund_type,
)

# ---------------------------------------------------------------------------
# ORM builder helpers (mirroring test_fifo_tax.py)
# ---------------------------------------------------------------------------


async def _make_user(db: AsyncSession, email: str = "adv@example.com") -> User:
    user = User(email=email, password_hash="x", display_name="Adv Tester")
    db.add(user)
    await db.flush()
    return user


async def _make_holding(
    db: AsyncSession,
    user: User,
    *,
    symbol: str = "RELIANCE",
    exchange: str = "NSE",
    currency: str = "INR",
    fund_type: str | None = None,
    avg_price: float = 100.0,
    quantity: float = 10.0,
) -> Holding:
    portfolio = Portfolio(user_id=user.id, name="Adv Portfolio", currency=currency)
    db.add(portfolio)
    await db.flush()

    holding = Holding(
        portfolio_id=portfolio.id,
        stock_symbol=symbol,
        stock_name=symbol,
        exchange=exchange,
        currency=currency,
        fund_type=fund_type,
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
):
    from app.models.transaction import Transaction

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


def _patch_fmv(monkeypatch, value: float | None) -> None:
    """Force get_fmv_31jan2018 to return a fixed value (no network)."""

    async def _fake(symbol: str, exchange: str) -> float | None:
        return value

    monkeypatch.setattr(tax_service, "get_fmv_31jan2018", _fake)


def _one(records: list, gain_type: str):
    matches = [r for r in records if r.gain_type == gain_type]
    assert len(matches) == 1, f"expected one {gain_type} record, got {len(matches)}"
    return matches[0]


# ===========================================================================
# 1. Indian LTCG grandfathering
# ===========================================================================


@pytest.mark.asyncio
async def test_grandfathering_uses_higher_fmv_reducing_ltcg(db, monkeypatch):
    """Pre-2018 lot: basis = max(cost, min(FMV, sale)). FMV 400 > cost 100 and
    < sale 600 -> basis 400, gain (600-400)*10 = 2000, not 5000."""
    _patch_fmv(monkeypatch, 400.0)
    user = await _make_user(db)
    holding = await _make_holding(db, user, avg_price=100.0, quantity=10.0)

    await _add_txn(db, holding, txn_type="BUY", txn_date=date(2016, 1, 10), quantity=10, price=100)
    sell = await _add_txn(
        db, holding, txn_type="SELL", txn_date=date(2020, 5, 1), quantity=10, price=600
    )

    records = await compute_tax_for_transaction(sell.id, user.id, db)
    ltcg = _one(records, "LTCG")

    assert float(ltcg.gain_amount) == 2000.0        # grandfathered (was 5000)
    assert float(ltcg.purchase_price) == 4000.0     # 400 * 10
    assert float(ltcg.sale_price) == 6000.0
    # 2000 LTCG is within the Rs 1.25L exemption -> no tax.
    assert float(ltcg.tax_amount) == 0.0


@pytest.mark.asyncio
async def test_grandfathering_capped_by_sale_price(db, monkeypatch):
    """When sale price < FMV, basis = min(FMV, sale) = sale, gain shrinks to 0."""
    _patch_fmv(monkeypatch, 400.0)
    user = await _make_user(db)
    holding = await _make_holding(db, user, avg_price=100.0, quantity=10.0)

    await _add_txn(db, holding, txn_type="BUY", txn_date=date(2016, 1, 10), quantity=10, price=100)
    sell = await _add_txn(
        db, holding, txn_type="SELL", txn_date=date(2020, 5, 1), quantity=10, price=300
    )

    records = await compute_tax_for_transaction(sell.id, user.id, db)
    ltcg = _one(records, "LTCG")
    # basis = max(100, min(400, 300)) = 300 -> gain (300-300)*10 = 0
    assert float(ltcg.purchase_price) == 3000.0
    assert float(ltcg.gain_amount) == 0.0


@pytest.mark.asyncio
async def test_grandfathering_never_below_actual_cost(db, monkeypatch):
    """FMV below actual cost -> basis stays at the actual cost (higher-of rule)."""
    _patch_fmv(monkeypatch, 50.0)
    user = await _make_user(db)
    holding = await _make_holding(db, user, avg_price=100.0, quantity=10.0)

    await _add_txn(db, holding, txn_type="BUY", txn_date=date(2016, 1, 10), quantity=10, price=100)
    sell = await _add_txn(
        db, holding, txn_type="SELL", txn_date=date(2020, 5, 1), quantity=10, price=600
    )

    records = await compute_tax_for_transaction(sell.id, user.id, db)
    ltcg = _one(records, "LTCG")
    # basis = max(100, min(50, 600)) = 100 -> gain 5000
    assert float(ltcg.purchase_price) == 1000.0
    assert float(ltcg.gain_amount) == 5000.0


@pytest.mark.asyncio
async def test_grandfathering_fallback_when_fmv_unavailable(db, monkeypatch):
    """FMV unavailable (None) -> fall back to actual cost, gain never worse."""
    _patch_fmv(monkeypatch, None)
    user = await _make_user(db)
    holding = await _make_holding(db, user, avg_price=100.0, quantity=10.0)

    await _add_txn(db, holding, txn_type="BUY", txn_date=date(2016, 1, 10), quantity=10, price=100)
    sell = await _add_txn(
        db, holding, txn_type="SELL", txn_date=date(2020, 5, 1), quantity=10, price=600
    )

    records = await compute_tax_for_transaction(sell.id, user.id, db)
    ltcg = _one(records, "LTCG")
    assert float(ltcg.purchase_price) == 1000.0     # actual cost
    assert float(ltcg.gain_amount) == 5000.0


@pytest.mark.asyncio
async def test_grandfathering_does_not_touch_stcg(db, monkeypatch):
    """A pre-2018 lot sold within 12 months is STCG -> grandfathering NOT applied."""
    _patch_fmv(monkeypatch, 400.0)
    user = await _make_user(db)
    holding = await _make_holding(db, user, avg_price=100.0, quantity=10.0)

    # buy 15-Jan-2018 (pre cutoff), sell 1-Jun-2018 (~4.5 months -> STCG)
    await _add_txn(db, holding, txn_type="BUY", txn_date=date(2018, 1, 15), quantity=10, price=100)
    sell = await _add_txn(
        db, holding, txn_type="SELL", txn_date=date(2018, 6, 1), quantity=10, price=600
    )

    records = await compute_tax_for_transaction(sell.id, user.id, db)
    stcg = _one(records, "STCG")
    # actual cost, not grandfathered
    assert float(stcg.purchase_price) == 1000.0
    assert float(stcg.gain_amount) == 5000.0
    assert float(stcg.tax_amount) == 1000.0          # 20% of 5000


# ===========================================================================
# 2. German Teilfreistellung
# ===========================================================================


def test_teilfreistellung_percentages():
    assert teilfreistellung_for_fund_type("EQUITY_ETF") == 30.0
    assert teilfreistellung_for_fund_type("MIXED_ETF") == 15.0
    assert teilfreistellung_for_fund_type("REAL_ESTATE_ETF") == 60.0
    assert teilfreistellung_for_fund_type("BOND_ETF") == 0.0
    assert teilfreistellung_for_fund_type("STOCK") == 0.0
    assert teilfreistellung_for_fund_type(None) == 0.0
    assert teilfreistellung_for_fund_type("unknown") == 0.0


def test_teilfreistellung_equity_etf_taxes_70_percent():
    """EQUITY_ETF (30% exempt): a 10000 gain is taxed as if it were 7000."""
    result = calculate_german_tax(10_000.0, freibetrag_remaining=0.0, teilfreistellung_pct=30.0)
    reference = calculate_german_tax(7_000.0, freibetrag_remaining=0.0)

    assert result["teilfreistellung_exempt"] == 3_000.0
    assert result["tax_amount"] == reference["tax_amount"]  # taxed on the 70%
    # explicit: taxable 7000 -> kap 1750 + soli 96.25 = 1846.25
    assert result["tax_amount"] == 1846.25


def test_teilfreistellung_default_zero_unchanged():
    """Default teilfreistellung_pct=0 leaves the previous behaviour intact."""
    with_default = calculate_german_tax(5_000.0, freibetrag_remaining=0.0)
    explicit_zero = calculate_german_tax(
        5_000.0, freibetrag_remaining=0.0, teilfreistellung_pct=0.0
    )
    assert with_default["tax_amount"] == explicit_zero["tax_amount"] == 1318.75
    assert with_default["teilfreistellung_exempt"] == 0.0


@pytest.mark.asyncio
async def test_teilfreistellung_threaded_through_compute(db):
    """German EQUITY_ETF sale: stored gain is gross, tax is on the 70% portion."""
    user = await _make_user(db)
    etf = await _make_holding(
        db, user, symbol="IWDA", exchange="XETRA", currency="EUR",
        fund_type="EQUITY_ETF", avg_price=50.0, quantity=100.0,
    )
    await _add_txn(db, etf, txn_type="BUY", txn_date=date(2020, 1, 1), quantity=100, price=50)
    sell = await _add_txn(
        db, etf, txn_type="SELL", txn_date=date(2023, 6, 1), quantity=100, price=150
    )

    records = await compute_tax_for_transaction(sell.id, user.id, db)
    rec = _one(records, "ABGELTUNGSSTEUER")

    assert rec.tax_jurisdiction == "DE"
    assert float(rec.gain_amount) == 10_000.0        # gross economic gain
    # gain 10000 -> 30% exempt = 7000 -> minus 1000 Freibetrag = 6000 taxable
    # kap 1500 + soli 82.5 = 1582.5
    assert float(rec.tax_amount) == 1582.5


@pytest.mark.asyncio
async def test_stock_holding_no_teilfreistellung(db):
    """Same numbers but a plain STOCK (0% exemption) is taxed more than the ETF."""
    user = await _make_user(db, email="stockde@example.com")
    stock = await _make_holding(
        db, user, symbol="SAP", exchange="XETRA", currency="EUR",
        fund_type=None, avg_price=50.0, quantity=100.0,
    )
    await _add_txn(db, stock, txn_type="BUY", txn_date=date(2020, 1, 1), quantity=100, price=50)
    sell = await _add_txn(
        db, stock, txn_type="SELL", txn_date=date(2023, 6, 1), quantity=100, price=150
    )

    records = await compute_tax_for_transaction(sell.id, user.id, db)
    rec = _one(records, "ABGELTUNGSSTEUER")
    # gain 10000 -> minus 1000 Freibetrag = 9000 taxable; kap 2250 + soli 123.75
    assert float(rec.gain_amount) == 10_000.0
    assert float(rec.tax_amount) == 2373.75


# ===========================================================================
# 3. German Vorabpauschale
# ===========================================================================


def test_vorabpauschale_documented_output():
    """value_start 100000, basiszins 2% -> Basisertrag 1400; capped by 10000
    appreciation -> Vorabpauschale 1400; no Teilfreistellung -> tax 369.25."""
    res = compute_vorabpauschale(
        value_start=100_000.0,
        value_end=110_000.0,
        distributions=0.0,
        basiszins_pct=2.0,
        fund_type=None,
        months_held=12,
    )
    assert res["basisertrag"] == 1400.0             # 100000 * 0.02 * 0.7
    assert res["vorabpauschale"] == 1400.0
    assert res["taxable_vorabpauschale"] == 1400.0
    # 1400 * 26.375% -> kap 350 + soli 19.25 = 369.25
    assert res["tax_amount"] == 369.25


def test_vorabpauschale_with_teilfreistellung():
    """EQUITY_ETF: the 1400 Vorabpauschale is taxed on 70% = 980."""
    res = compute_vorabpauschale(
        value_start=100_000.0,
        value_end=110_000.0,
        distributions=0.0,
        basiszins_pct=2.0,
        fund_type="EQUITY_ETF",
        months_held=12,
    )
    assert res["vorabpauschale"] == 1400.0
    assert res["taxable_vorabpauschale"] == 980.0
    assert res["tax_amount"] == calculate_german_tax(980.0, freibetrag_remaining=0.0)["tax_amount"]


def test_vorabpauschale_capped_by_appreciation():
    """Vorabpauschale never exceeds the year's actual value gain."""
    res = compute_vorabpauschale(
        value_start=100_000.0,
        value_end=100_050.0,   # only 50 appreciation
        distributions=0.0,
        basiszins_pct=2.0,
        fund_type=None,
    )
    assert res["basisertrag"] == 1400.0
    assert res["vorabpauschale"] == 50.0


def test_vorabpauschale_reduced_by_distributions():
    """Distributions reduce the Basisertrag before the appreciation cap."""
    res = compute_vorabpauschale(
        value_start=100_000.0,
        value_end=110_000.0,
        distributions=1_000.0,
        basiszins_pct=2.0,
        fund_type=None,
    )
    # min(1400 - 1000, 10000) = 400
    assert res["vorabpauschale"] == 400.0


def test_vorabpauschale_zero_in_loss_year():
    """A loss year (value_end < value_start) -> Vorabpauschale 0, tax 0."""
    res = compute_vorabpauschale(
        value_start=100_000.0,
        value_end=90_000.0,
        distributions=0.0,
        basiszins_pct=2.0,
        fund_type="EQUITY_ETF",
    )
    assert res["vorabpauschale"] == 0.0
    assert res["tax_amount"] == 0.0


def test_vorabpauschale_prorated_by_months():
    """Half a year held halves the Basisertrag."""
    res = compute_vorabpauschale(
        value_start=100_000.0,
        value_end=200_000.0,
        distributions=0.0,
        basiszins_pct=2.0,
        fund_type=None,
        months_held=6,
    )
    assert res["basisertrag"] == 700.0              # 1400 * 6/12


def test_basiszins_lookup():
    assert basiszins_for_year(2024) == 2.29
    assert basiszins_for_year(2023) == 2.55
    assert basiszins_for_year(2021) == 0.0          # negative published rate floored
    assert basiszins_for_year(3000) == 2.29         # documented default


# ===========================================================================
# 4. Sparer-Pauschbetrag allowance tracker
# ===========================================================================


async def _add_de_gain_record(
    db: AsyncSession, user: User, gain: float, fy: str = "2024"
) -> None:
    rec = TaxRecord(
        user_id=user.id,
        transaction_id=None,
        financial_year=fy,
        tax_jurisdiction="DE",
        gain_type="ABGELTUNGSSTEUER",
        purchase_date=date(2024, 1, 1),
        sale_date=date(2024, 6, 1),
        purchase_price=1000.0,
        sale_price=1000.0 + gain,
        gain_amount=gain,
        tax_amount=0.0,
        currency="EUR",
    )
    db.add(rec)
    await db.flush()


async def _set_filing(db: AsyncSession, user: User, filing: str) -> None:
    from sqlalchemy import select

    res = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == user.id)
    )
    prefs = res.scalar_one_or_none()
    if prefs is None:
        prefs = UserPreferences(user_id=user.id, tax_settings={"filing": filing})
        db.add(prefs)
    else:
        prefs.tax_settings = {"filing": filing}
    await db.flush()


@pytest.mark.asyncio
async def test_allowance_single_caps_at_1000(db):
    user = await _make_user(db, email="single@example.com")
    await _set_filing(db, user, "single")
    await _add_de_gain_record(db, user, 800.0)
    await _add_de_gain_record(db, user, 900.0)   # total 1700 gains

    result = await compute_german_allowance(user.id, "2024", db)
    assert result["filing"] == "single"
    assert result["total_allowance"] == 1000.0
    assert result["used"] == 1000.0              # min(1000, 1700)
    assert result["remaining"] == 0.0


@pytest.mark.asyncio
async def test_allowance_joint_caps_at_2000(db):
    user = await _make_user(db, email="joint@example.com")
    await _set_filing(db, user, "joint")
    await _add_de_gain_record(db, user, 800.0)
    await _add_de_gain_record(db, user, 900.0)   # total 1700 gains

    result = await compute_german_allowance(user.id, "2024", db)
    assert result["filing"] == "joint"
    assert result["total_allowance"] == 2000.0
    assert result["used"] == 1700.0
    assert result["remaining"] == 300.0


@pytest.mark.asyncio
async def test_allowance_defaults_to_single_without_prefs(db):
    user = await _make_user(db, email="noprefs@example.com")
    await _add_de_gain_record(db, user, 400.0)

    result = await compute_german_allowance(user.id, "2024", db)
    assert result["filing"] == "single"
    assert result["total_allowance"] == 1000.0
    assert result["used"] == 400.0
    assert result["remaining"] == 600.0


@pytest.mark.asyncio
async def test_allowance_includes_german_dividends(db):
    """German dividends consume the allowance alongside capital gains."""
    user = await _make_user(db, email="div@example.com")
    await _set_filing(db, user, "single")
    holding = await _make_holding(
        db, user, symbol="ALV", exchange="XETRA", currency="EUR", fund_type=None
    )
    div = Dividend(
        holding_id=holding.id,
        ex_date=date(2024, 5, 1),
        total_amount=200.0,
        amount_per_share=2.0,
    )
    db.add(div)
    await db.flush()
    await _add_de_gain_record(db, user, 500.0)

    result = await compute_german_allowance(user.id, "2024", db)
    # gains 500 + dividends 200 = 700 used
    assert result["used"] == 700.0
    assert result["remaining"] == 300.0


@pytest.mark.asyncio
async def test_allowance_etf_gain_reduced_by_teilfreistellung(db):
    """An ETF gain only consumes the allowance on its taxable (post-30%) portion."""
    user = await _make_user(db, email="etfallow@example.com")
    await _set_filing(db, user, "single")
    etf = await _make_holding(
        db, user, symbol="IWDA", exchange="XETRA", currency="EUR",
        fund_type="EQUITY_ETF", avg_price=50.0, quantity=100.0,
    )
    await _add_txn(db, etf, txn_type="BUY", txn_date=date(2020, 1, 1), quantity=100, price=50)
    sell = await _add_txn(
        db, etf, txn_type="SELL", txn_date=date(2024, 3, 1), quantity=100, price=60
    )
    await compute_tax_for_transaction(sell.id, user.id, db)

    # gross gain 1000 -> 30% exempt -> 700 taxable consumes the allowance
    result = await compute_german_allowance(user.id, "2024", db)
    assert result["used"] == 700.0
    assert result["remaining"] == 300.0
