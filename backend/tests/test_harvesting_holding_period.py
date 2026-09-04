"""Tax-loss harvesting must use the real holding period, rate and cost basis.

The old estimate hardcoded ``gain_type = "STCG"`` and the 20 % s.111A rate for
every Indian holding, priced the loss off ``Holding.average_price`` instead of
the FIFO open lots, and ignored the fact that FIFO gives the seller no choice
of lot — so a position whose older lots are in profit was advertised as a pure
harvest. All four are fixed here.

Dates are relative to ``date.today()`` so the file does not rot.

Run with:
    uv run pytest tests/test_harvesting_holding_period.py -q
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.transaction import Transaction
from app.models.user import User
from app.services.tax_service import _add_months, get_harvesting_suggestions

TODAY = date.today()


async def _make_user(db: AsyncSession, email: str = "harvest@example.com") -> User:
    user = User(email=email, password_hash="x", display_name="Harvest Tester")
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
    quantity: float,
    avg_price: float,
    current_price: float,
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
        cumulative_quantity=quantity,
        average_price=avg_price,
        current_price=current_price,
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


def _one(suggestions: list[dict], symbol: str) -> dict:
    matches = [s for s in suggestions if s["stock_symbol"] == symbol]
    assert len(matches) == 1, f"expected one {symbol}, got {len(matches)}"
    return matches[0]


# ===========================================================================
# Holding period drives the rate and the label
# ===========================================================================


@pytest.mark.asyncio
async def test_long_held_loser_is_valued_at_the_ltcg_rate(db: AsyncSession):
    """A >12-month loser realizes an LTCL, worth 12.5 %, not 20 %."""
    user = await _make_user(db, "harvest-lt@example.com")
    h = await _make_holding(db, user, symbol="INFY", quantity=100.0,
                            avg_price=1800.0, current_price=1500.0)
    await _add_txn(db, h, txn_type="BUY", txn_date=TODAY - timedelta(days=1500),
                   quantity=100, price=1800)

    s = _one(await get_harvesting_suggestions(user.id, "IN", db), "INFY")
    assert s["gain_type"] == "LTCL"
    assert s["long_term_loss"] == 30_000.0
    assert s["short_term_loss"] == 0.0
    assert s["unrealized_loss"] == 30_000.0
    assert s["potential_tax_saving"] == 3_750.0     # was 6,000 at the STCG rate


@pytest.mark.asyncio
async def test_recent_loser_keeps_the_stcg_rate(db: AsyncSession):
    """A <12-month loser is still an STCL at 20 % — no regression."""
    user = await _make_user(db, "harvest-st@example.com")
    h = await _make_holding(db, user, symbol="TCS", quantity=50.0,
                            avg_price=4000.0, current_price=3500.0)
    await _add_txn(db, h, txn_type="BUY", txn_date=TODAY - timedelta(days=60),
                   quantity=50, price=4000)

    s = _one(await get_harvesting_suggestions(user.id, "IN", db), "TCS")
    assert s["gain_type"] == "STCL"
    assert s["potential_tax_saving"] == 5_000.0     # 25,000 * 20 %


@pytest.mark.asyncio
async def test_mixed_age_lots_split_short_and_long_term(db: AsyncSession):
    """A mixed-age position yields BOTH components, each at its own rate."""
    user = await _make_user(db, "harvest-mixed@example.com")
    h = await _make_holding(db, user, symbol="WIPRO", quantity=100.0,
                            avg_price=1800.0, current_price=1000.0)
    await _add_txn(db, h, txn_type="BUY", txn_date=TODAY - timedelta(days=1100),
                   quantity=60, price=2000)
    await _add_txn(db, h, txn_type="BUY", txn_date=TODAY - timedelta(days=95),
                   quantity=40, price=1500)

    s = _one(await get_harvesting_suggestions(user.id, "IN", db), "WIPRO")
    assert s["gain_type"] == "MIXED"
    assert s["short_term_loss"] == 20_000.0
    assert s["long_term_loss"] == 60_000.0
    assert s["unrealized_loss"] == 80_000.0
    # 20,000 * 20 % + 60,000 * 12.5 %
    assert s["potential_tax_saving"] == 11_500.0    # was 16,000


@pytest.mark.asyncio
async def test_boundary_exactly_12_months_is_still_short_term(db: AsyncSession):
    """``classify_gain_type`` needs STRICTLY more than 12 months."""
    user = await _make_user(db, "harvest-boundary@example.com")
    h = await _make_holding(db, user, symbol="BOUND", quantity=10.0,
                            avg_price=1000.0, current_price=900.0)
    await _add_txn(db, h, txn_type="BUY", txn_date=_add_months(TODAY, -12),
                   quantity=10, price=1000)

    s = _one(await get_harvesting_suggestions(user.id, "IN", db), "BOUND")
    assert s["gain_type"] == "STCL"
    assert s["potential_tax_saving"] == 200.0      # 1,000 * 20 %

    # One day earlier and the same lot is long-term.
    res = await db.execute(
        select(Transaction).where(Transaction.holding_id == h.id)
    )
    txn = res.scalars().one()
    txn.date = _add_months(TODAY, -12) - timedelta(days=1)
    await db.flush()

    s = _one(await get_harvesting_suggestions(user.id, "IN", db), "BOUND")
    assert s["gain_type"] == "LTCL"
    assert s["potential_tax_saving"] == 125.0      # 1,000 * 12.5 %


# ===========================================================================
# Cost basis: FIFO open lots, not the weighted average
# ===========================================================================


@pytest.mark.asyncio
async def test_partial_sale_uses_fifo_basis_not_the_weighted_average(
    db: AsyncSession,
):
    """After a partial sale the weighted average is the wrong number."""
    user = await _make_user(db, "harvest-fifo@example.com")
    h = await _make_holding(db, user, symbol="BAJAJ", quantity=100.0,
                            avg_price=1500.0, current_price=1200.0)
    await _add_txn(db, h, txn_type="BUY", txn_date=TODAY - timedelta(days=1100),
                   quantity=100, price=1000)
    await _add_txn(db, h, txn_type="BUY", txn_date=TODAY - timedelta(days=95),
                   quantity=100, price=2000)
    await _add_txn(db, h, txn_type="SELL", txn_date=TODAY - timedelta(days=65),
                   quantity=100, price=1900)

    s = _one(await get_harvesting_suggestions(user.id, "IN", db), "BAJAJ")
    # The remaining lot is the 2,000 one -> an 80,000 short-term loss, not the
    # 30,000 the 1,500 weighted average implies.
    assert s["short_term_loss"] == 80_000.0
    assert s["unrealized_loss"] == 80_000.0
    assert s["potential_tax_saving"] == 16_000.0   # was 6,000
    assert s["lots_known"] is True


@pytest.mark.asyncio
async def test_holding_without_transactions_falls_back_and_says_so(
    db: AsyncSession,
):
    """Broker-synced positions have no ledger; they must not vanish."""
    user = await _make_user(db, "harvest-noledger@example.com")
    await _make_holding(db, user, symbol="NOLEDGER", quantity=10.0,
                        avg_price=1600.0, current_price=1400.0)

    s = _one(await get_harvesting_suggestions(user.id, "IN", db), "NOLEDGER")
    assert s["unrealized_loss"] == 2_000.0
    assert s["potential_tax_saving"] == 400.0
    assert s["lots_known"] is False


@pytest.mark.asyncio
async def test_partial_ledger_is_not_reported_as_known(db: AsyncSession):
    """A ledger covering only part of the position under-reports the loss."""
    user = await _make_user(db, "harvest-partial@example.com")
    h = await _make_holding(db, user, symbol="PARTIAL", quantity=100.0,
                            avg_price=2000.0, current_price=1000.0)
    await _add_txn(db, h, txn_type="BUY", txn_date=TODAY - timedelta(days=60),
                   quantity=10, price=2000)

    s = _one(await get_harvesting_suggestions(user.id, "IN", db), "PARTIAL")
    assert s["lots_known"] is False
    # The weighted-average fallback covers the whole 100 shares, not just 10.
    assert s["unrealized_loss"] == 100_000.0
    assert s["potential_tax_saving"] == 20_000.0


# ===========================================================================
# FIFO gives no lot choice: forced gains must be netted
# ===========================================================================


@pytest.mark.asyncio
async def test_profitable_holding_is_excluded(db: AsyncSession):
    user = await _make_user(db, "harvest-profit@example.com")
    h = await _make_holding(db, user, symbol="WINNER", quantity=10.0,
                            avg_price=100.0, current_price=150.0)
    await _add_txn(db, h, txn_type="BUY", txn_date=TODAY - timedelta(days=60),
                   quantity=10, price=100)

    assert await get_harvesting_suggestions(user.id, "IN", db) == []


@pytest.mark.asyncio
async def test_position_whose_lots_net_to_a_gain_is_not_suggested(
    db: AsyncSession,
):
    """A newer losing lot cannot be sold without realizing the older profit."""
    user = await _make_user(db, "harvest-straddle-up@example.com")
    h = await _make_holding(db, user, symbol="STRADDLE_UP", quantity=200.0,
                            avg_price=900.0, current_price=1000.0)
    await _add_txn(db, h, txn_type="BUY", txn_date=TODAY - timedelta(days=1100),
                   quantity=100, price=500)
    await _add_txn(db, h, txn_type="BUY", txn_date=TODAY - timedelta(days=60),
                   quantity=100, price=1300)

    assert await get_harvesting_suggestions(user.id, "IN", db) == []


@pytest.mark.asyncio
async def test_forced_gain_reduces_the_advertised_saving(db: AsyncSession):
    """A net loser still carrying a forced long-term gain is worth less."""
    user = await _make_user(db, "harvest-straddle-down@example.com")
    h = await _make_holding(db, user, symbol="STRADDLE_DN", quantity=200.0,
                            avg_price=1750.0, current_price=1000.0)
    await _add_txn(db, h, txn_type="BUY", txn_date=TODAY - timedelta(days=1100),
                   quantity=100, price=500)     # +50,000 long-term GAIN
    await _add_txn(db, h, txn_type="BUY", txn_date=TODAY - timedelta(days=60),
                   quantity=100, price=3000)    # -200,000 short-term loss

    s = _one(await get_harvesting_suggestions(user.id, "IN", db), "STRADDLE_DN")
    assert s["unrealized_loss"] == 150_000.0    # the whole-position P/L
    assert s["short_term_loss"] == 200_000.0
    assert s["long_term_loss"] == 0.0
    # 200,000 * 20 % - 50,000 * 12.5 %
    assert s["potential_tax_saving"] == 33_750.0


@pytest.mark.asyncio
async def test_zero_cost_lot_on_a_flat_position_is_not_a_harvest(
    db: AsyncSession,
):
    """A corporate-action adjustment lot must not fabricate a loss.

    A 1:2 split recorded as a zero-price BUY makes the old lot look 100 %
    under water while the new lot looks 100 % up. The position is flat, so it
    must not be suggested — acting on it would realize a taxable gain.
    """
    user = await _make_user(db, "harvest-split@example.com")
    h = await _make_holding(db, user, symbol="SPLITCO", quantity=200.0,
                            avg_price=900.0, current_price=900.0)
    await _add_txn(db, h, txn_type="BUY", txn_date=TODAY - timedelta(days=1100),
                   quantity=100, price=1800)
    await _add_txn(db, h, txn_type="BUY", txn_date=TODAY - timedelta(days=90),
                   quantity=100, price=0)

    assert await get_harvesting_suggestions(user.id, "IN", db) == []


# ===========================================================================
# Ranking and the untouched German branch
# ===========================================================================


@pytest.mark.asyncio
async def test_ranking_prefers_short_term_losses(db: AsyncSession):
    """A short-term loss is never worth less than a long-term one its size."""
    user = await _make_user(db, "harvest-rank@example.com")
    infy = await _make_holding(db, user, symbol="INFY", quantity=100.0,
                               avg_price=1800.0, current_price=1500.0)
    await _add_txn(db, infy, txn_type="BUY", txn_date=TODAY - timedelta(days=1500),
                   quantity=100, price=1800)
    tcs = await _make_holding(db, user, symbol="TCS", quantity=50.0,
                              avg_price=4000.0, current_price=3500.0)
    await _add_txn(db, tcs, txn_type="BUY", txn_date=TODAY - timedelta(days=60),
                   quantity=50, price=4000)

    out = await get_harvesting_suggestions(user.id, "IN", db)
    # TCS: 25,000 at 20 % = 5,000; INFY: 30,000 at 12.5 % = 3,750.
    assert [s["stock_symbol"] for s in out] == ["TCS", "INFY"]


@pytest.mark.asyncio
async def test_german_holdings_unchanged(db: AsyncSession):
    """Abgeltungssteuer has no holding-period split; the DE branch is untouched."""
    user = await _make_user(db, "harvest-de@example.com")
    h = await _make_holding(db, user, symbol="SAP", exchange="XETRA",
                            currency="EUR", quantity=10.0,
                            avg_price=100.0, current_price=80.0)
    await _add_txn(db, h, txn_type="BUY", txn_date=TODAY - timedelta(days=1500),
                   quantity=10, price=100)

    s = _one(await get_harvesting_suggestions(user.id, "DE", db), "SAP")
    assert s["gain_type"] == "ABGELTUNGSSTEUER"
    assert s["potential_tax_saving"] == round(200 * 0.25 * 1.055, 2) == 52.75


@pytest.mark.asyncio
async def test_harvesting_endpoint_serves_the_corrected_numbers(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    """API smoke: the corrected rate and label survive serialization.

    ``short_term_loss`` / ``long_term_loss`` / ``lots_known`` are computed by
    the service but stripped by ``TaxHarvestingSuggestion`` until that schema
    is widened — see the handoff note; the rate fix does not depend on them.
    """
    from tests.conftest import TEST_USER_EMAIL

    res = await db.execute(select(User).where(User.email == TEST_USER_EMAIL))
    user = res.scalars().one()
    h = await _make_holding(db, user, symbol="INFYAPI", quantity=100.0,
                            avg_price=1800.0, current_price=1500.0)
    await _add_txn(db, h, txn_type="BUY", txn_date=TODAY - timedelta(days=1500),
                   quantity=100, price=1800)
    await db.commit()

    resp = await client.get(
        "/api/v1/tax/harvesting?jurisdiction=IN", headers=auth_headers
    )
    assert resp.status_code == 200
    item = next(s for s in resp.json() if s["stock_symbol"] == "INFYAPI")
    assert item["gain_type"] == "LTCL"
    assert item["potential_tax_saving"] == 3_750.0
