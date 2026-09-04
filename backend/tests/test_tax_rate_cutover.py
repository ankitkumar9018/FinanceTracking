"""Date-aware Indian capital-gains rates (Finance (No. 2) Act 2024).

Transfers BEFORE 23-Jul-2024 are taxed at the old s.111A 15 % / s.112A 10 %;
transfers on or after are taxed at 20 % / 12.5 %. The s.112A exemption is a
per-FINANCIAL-YEAR pool (Rs 1,00,000 up to FY 2023-24, Rs 1,25,000 from
FY 2024-25), NOT a per-transfer entitlement — keying it to the transfer date
would make the pool size depend on the order sales are computed in during the
straddling FY 2024-25.

Run with:
    uv run pytest tests/test_tax_rate_cutover.py -q
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
    calculate_indian_tax,
    compute_tax_for_transaction,
    generate_tax_summary,
    india_ltcg_exemption_for_fy,
    india_rates_for,
)


async def _make_user(db: AsyncSession, email: str) -> User:
    user = User(email=email, password_hash="x", display_name="Cutover Tester")
    db.add(user)
    await db.flush()
    return user


async def _make_holding(
    db: AsyncSession, user: User, *, symbol: str = "RELIANCE"
) -> Holding:
    portfolio = Portfolio(user_id=user.id, name=f"P-{symbol}", currency="INR")
    db.add(portfolio)
    await db.flush()
    holding = Holding(
        portfolio_id=portfolio.id,
        stock_symbol=symbol,
        stock_name=symbol,
        exchange="NSE",
        currency="INR",
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


async def _fy_total_tax(db: AsyncSession, user_id: int, fy: str) -> float:
    result = await db.execute(
        select(TaxRecord).where(
            TaxRecord.user_id == user_id, TaxRecord.financial_year == fy
        )
    )
    return sum(float(r.tax_amount or 0.0) for r in result.scalars().all())


# ===========================================================================
# 1. The rate boundary is inclusive of 23 July 2024
# ===========================================================================


def test_stcg_rate_boundary_is_inclusive_of_23_july_2024():
    assert calculate_indian_tax(
        300_000.0, "STCG", sale_date=date(2024, 7, 22)
    ) == {"tax_amount": 45_000.0, "rate_applied": 0.15, "exemption_used": 0.0}
    assert calculate_indian_tax(
        300_000.0, "STCG", sale_date=date(2024, 7, 23)
    ) == {"tax_amount": 60_000.0, "rate_applied": 0.20, "exemption_used": 0.0}


def test_india_rates_for_lookup():
    assert india_rates_for(date(2024, 7, 22)) == (0.15, 0.10)
    assert india_rates_for(date(2024, 7, 23)) == (0.20, 0.125)
    assert india_rates_for(date(2018, 6, 1)) == (0.15, 0.10)
    assert india_rates_for(None) == (0.20, 0.125)   # current law


# ===========================================================================
# 2. LTCG rate + FY-keyed exemption pool, three regimes
# ===========================================================================


def test_ltcg_rate_and_fy_pool_across_the_three_regimes():
    # FY 2023-24: 10 % above Rs 1 lakh.
    r = calculate_indian_tax(300_000.0, "LTCG", sale_date=date(2024, 3, 15))
    assert r["tax_amount"] == 20_000.0
    assert r["rate_applied"] == 0.10
    assert r["exemption_used"] == 100_000.0

    # FY 2024-25 BEFORE the cutover: still the 10 % rate, but the FULL
    # Rs 1.25 lakh pool — the enhanced limit is an annual entitlement.
    r = calculate_indian_tax(300_000.0, "LTCG", sale_date=date(2024, 5, 10))
    assert r["tax_amount"] == 17_500.0
    assert r["rate_applied"] == 0.10
    assert r["exemption_used"] == 125_000.0

    # FY 2024-25 after the cutover: 12.5 % and Rs 1.25 lakh.
    r = calculate_indian_tax(300_000.0, "LTCG", sale_date=date(2024, 9, 15))
    assert r["tax_amount"] == 21_875.0
    assert r["rate_applied"] == 0.125
    assert r["exemption_used"] == 125_000.0


def test_exemption_pool_lookup_by_financial_year():
    assert india_ltcg_exemption_for_fy("2018-19") == 100_000.0
    assert india_ltcg_exemption_for_fy("2023-24") == 100_000.0
    assert india_ltcg_exemption_for_fy("2024-25") == 125_000.0
    assert india_ltcg_exemption_for_fy("2025-26") == 125_000.0
    assert india_ltcg_exemption_for_fy(None) == 125_000.0        # current law
    assert india_ltcg_exemption_for_fy("garbage") == 125_000.0   # no crash


# ===========================================================================
# 3. Backward compatibility — omitting the date means current law
# ===========================================================================


def test_omitting_sale_date_keeps_current_law():
    assert calculate_indian_tax(300_000.0, "STCG") == {
        "tax_amount": 60_000.0,
        "rate_applied": 0.20,
        "exemption_used": 0.0,
    }
    assert calculate_indian_tax(300_000.0, "LTCG")["tax_amount"] == 21_875.0
    # The third argument is still positional.
    assert calculate_indian_tax(300_000.0, "STCG", 0.0)["tax_amount"] == 60_000.0
    assert calculate_indian_tax(300_000.0, "LTCG", 125_000.0)["tax_amount"] == 37_500.0


# ===========================================================================
# 4. End to end: a historical FY nets against the RIGHT pool
# ===========================================================================


@pytest.mark.asyncio
async def test_fy_2023_24_uses_the_one_lakh_pool_end_to_end(db: AsyncSession):
    """Two 80,000 LTCG sells in FY 2023-24: the pool is Rs 1 lakh, not 1.25."""
    user = await _make_user(db, "fy2324@example.com")
    holding = await _make_holding(db, user)
    await _add_txn(db, holding, txn_type="BUY", txn_date=date(2021, 1, 10),
                   quantity=2000, price=100)
    sell1 = await _add_txn(db, holding, txn_type="SELL", txn_date=date(2023, 6, 15),
                           quantity=1000, price=180)
    sell2 = await _add_txn(db, holding, txn_type="SELL", txn_date=date(2023, 12, 15),
                           quantity=1000, price=180)

    rec1 = (await compute_tax_for_transaction(sell1.id, user.id, db))[0]
    rec2 = (await compute_tax_for_transaction(sell2.id, user.id, db))[0]

    assert float(rec1.gain_amount) == 80_000.0
    assert float(rec1.tax_amount) == 0.0          # inside the Rs 1 lakh pool
    assert float(rec2.tax_amount) == 6_000.0      # (160,000 - 100,000) * 10 %
    assert await _fy_total_tax(db, user.id, "2023-24") == 6_000.0

    summary = await generate_tax_summary(user.id, "2023-24", "IN", db)
    assert summary["total_tax"] == 6_000.0
    assert summary["exemption_used"] == 100_000.0  # NOT 125,000


@pytest.mark.asyncio
async def test_stcg_before_and_after_the_cutover(db: AsyncSession):
    """The same Rs 300,000 short-term gain, taxed on either side of 23-Jul-2024."""
    for email, sale_date, expected in (
        ("pre@example.com", date(2024, 3, 15), 45_000.0),
        ("post@example.com", date(2024, 9, 15), 60_000.0),
    ):
        user = await _make_user(db, email)
        holding = await _make_holding(db, user)
        await _add_txn(db, holding, txn_type="BUY", txn_date=date(2023, 11, 10),
                       quantity=1000, price=100)
        sell = await _add_txn(db, holding, txn_type="SELL", txn_date=sale_date,
                              quantity=1000, price=400)
        rec = (await compute_tax_for_transaction(sell.id, user.id, db))[0]
        assert rec.gain_type == "STCG"
        assert float(rec.gain_amount) == 300_000.0
        assert float(rec.tax_amount) == expected


# ===========================================================================
# 5. The straddling FY 2024-25 stays order-independent
# ===========================================================================


async def _two_straddling_ltcg_sells(db: AsyncSession, user: User):
    """80,000 LTCG on 10-May-2024 (10 %) and on 15-Sep-2024 (12.5 %)."""
    holding = await _make_holding(db, user)
    await _add_txn(db, holding, txn_type="BUY", txn_date=date(2021, 1, 10),
                   quantity=2000, price=100)
    sell_a = await _add_txn(db, holding, txn_type="SELL", txn_date=date(2024, 5, 10),
                            quantity=1000, price=180)
    sell_b = await _add_txn(db, holding, txn_type="SELL", txn_date=date(2024, 9, 15),
                            quantity=1000, price=180)
    return sell_a, sell_b


@pytest.mark.asyncio
async def test_straddling_fy_pool_is_one_annual_pool_spent_chronologically(
    db: AsyncSession,
):
    """FY 2024-25 has ONE Rs 1.25 lakh pool spanning two rate slices.

    It is spent chronologically: the 10-May sale (10 % slice) consumes 80,000
    and the 15-Sep sale (12.5 %) consumes the remaining 45,000, leaving 35,000
    taxed at 12.5 % = 4,375. The order the sales are COMPUTED in must not
    change that — keying the pool to the transfer date instead of the FY is
    what would make the pool size itself order-dependent.
    """
    user1 = await _make_user(db, "straddle1@example.com")
    a1, b1 = await _two_straddling_ltcg_sells(db, user1)
    await compute_tax_for_transaction(a1.id, user1.id, db)
    await compute_tax_for_transaction(b1.id, user1.id, db)

    user2 = await _make_user(db, "straddle2@example.com")
    a2, b2 = await _two_straddling_ltcg_sells(db, user2)
    await compute_tax_for_transaction(b2.id, user2.id, db)
    await compute_tax_for_transaction(a2.id, user2.id, db)

    assert await _fy_total_tax(db, user1.id, "2024-25") == 4_375.0
    assert await _fy_total_tax(db, user2.id, "2024-25") == 4_375.0

    for user in (user1, user2):
        summary = await generate_tax_summary(user.id, "2024-25", "IN", db)
        assert summary["total_tax"] == 4_375.0
        assert summary["exemption_used"] == 125_000.0
