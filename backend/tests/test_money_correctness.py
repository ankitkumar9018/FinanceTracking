"""Money-correctness regression tests — each one pins a verified bug.

Every test below fails on the pre-fix code and describes real money moving the
wrong way:

1.  The Indian LTCG holding-period timer marked a lot long-term on the
    12-month anniversary itself, one day before ``classify_gain_type`` (the
    engine, and the law) agrees — selling on the timer's word costs 20 % STCG
    instead of 12.5 % LTCG.
2.  A SELL that matched no FIFO lot recorded zero tax and returned 201, so a
    real realized gain vanished from /tax/summary. Two causes: same-day
    buy-then-sell replayed in id order (SELL first), and the silent
    empty-result return.
3.  The dividend "trailing 12 months" window had no upper bound, so a
    future-dated dividend inflated the trailing yield.
4.  The forward dividend forecast anchored its 12-month window to the last
    payment EVER, projecting income from stocks that stopped paying years ago.
5.  The 24-hour FX cache TTL was unreachable (a row dated today is always
    younger than 24 h), freezing today's rate at the first fetch.
6.  The German Sparer-Pauschbetrag attributed dividends by ex-date instead of
    the payment (Zufluss) date.
7.  The Vorabpauschale estimate hardcoded distributions=0 / months_held=12.
8.  A price of 0 never triggered a stop-loss (falsy guard).
9.  Fixed deposits / bonds / property had no update route at all.

Run with:
    uv run pytest tests/test_money_correctness.py -q
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.dividend_service as dividend_service
import app.services.forex_service as forex_service
from app.models.asset import Asset
from app.models.dividend import Dividend
from app.models.forex_rates import ForexRate
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.transaction import Transaction
from app.models.user import User
from app.services.dividend_service import get_dividend_summary
from app.services.stop_loss_service import get_stop_loss_holdings
from app.services.tax_service import (
    _add_months,
    classify_gain_type,
    compute_german_allowance,
    compute_tax_for_transaction,
    estimate_portfolio_vorabpauschale,
)

from .conftest import TEST_USER_EMAIL

# ---------------------------------------------------------------------------
# ORM builders (mirroring tests/test_wave2_finance.py)
# ---------------------------------------------------------------------------


async def _make_user(
    db: AsyncSession, email: str, currency: str = "INR"
) -> User:
    user = User(
        email=email,
        password_hash="x",
        display_name="Money Correctness Tester",
        preferred_currency=currency,
    )
    db.add(user)
    await db.flush()
    return user


async def _current_user(db: AsyncSession) -> User:
    """The user registered by the ``auth_headers`` fixture."""
    res = await db.execute(select(User).where(User.email == TEST_USER_EMAIL))
    user = res.scalar_one()
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
    current_price: float | None = None,
    custom_fields: dict | None = None,
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
        cumulative_quantity=quantity,
        average_price=avg_price,
        current_price=current_price,
        custom_fields=custom_fields,
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


def _anniversary_purchase(today: date) -> date:
    """A purchase date whose 12-month anniversary falls exactly on ``today``.

    Searched rather than assumed so leap-day / month-end clamping in
    ``_add_months`` cannot make the test lie.
    """
    for delta in range(360, 373):
        candidate = today - timedelta(days=delta)
        if _add_months(candidate, 12) == today:
            return candidate
    raise AssertionError(f"no purchase date whose +12m lands on {today}")


# ===========================================================================
# 1. LTCG holding-period timer agrees with the engine on the boundary day
# ===========================================================================


async def test_ltcg_timer_agrees_with_engine_on_boundary_and_after(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    """The timer must never call a lot LTCG before ``classify_gain_type`` does.

    On the 12-month anniversary itself the engine still says STCG (the law
    requires the sale to be STRICTLY later). The old timer said LTCG, telling
    the user to sell a day early at 20 % instead of 12.5 %.
    """
    user = await _current_user(db)
    today = date.today()
    boundary = _anniversary_purchase(today)          # +12m == today  -> STCG
    day_before = boundary - timedelta(days=1)        # +12m <  today  -> LTCG
    day_after = boundary + timedelta(days=1)         # +12m >  today  -> STCG

    holding = await _make_holding(db, user, symbol="TIMERCO", quantity=30.0)
    for purchase in (boundary, day_before, day_after):
        await _add_txn(
            db, holding, txn_type="BUY", txn_date=purchase, quantity=10.0, price=1000.0
        )
    await db.commit()

    resp = await client.get(
        f"/api/v1/tax/holding-period/{holding.portfolio_id}", headers=auth_headers
    )
    assert resp.status_code == 200
    lots = {
        date.fromisoformat(lot["purchase_date"]): lot for lot in resp.json()["lots"]
    }
    assert set(lots) == {boundary, day_before, day_after}

    # The engine is the source of truth — the timer must match it for EVERY lot.
    for purchase, lot in lots.items():
        assert lot["status"] == classify_gain_type(purchase, today, "IN"), (
            f"timer disagrees with classify_gain_type for a lot bought {purchase}"
        )

    # And it must report the first day the lot actually qualifies.
    assert lots[boundary]["status"] == "STCG"
    assert lots[boundary]["days_remaining"] == 1
    assert date.fromisoformat(lots[boundary]["ltcg_date"]) == today + timedelta(days=1)
    assert classify_gain_type(
        boundary, date.fromisoformat(lots[boundary]["ltcg_date"]), "IN"
    ) == "LTCG"

    assert lots[day_before]["status"] == "LTCG"
    assert lots[day_after]["status"] == "STCG"

    # next_eligible_date is the soonest STCG lot's (corrected) eligibility date.
    assert resp.json()["summary"]["next_eligible_date"] == (
        today + timedelta(days=1)
    ).isoformat()


# ===========================================================================
# 2. A SELL must never silently record zero tax
# ===========================================================================


async def test_same_day_buy_then_sell_with_lower_sell_id_is_taxed(db: AsyncSession):
    """An intraday buy-then-sell whose SELL row carries the LOWER id.

    The FIFO replay used to order by ``(date, id)`` only, so the SELL was
    replayed before its own buy lot existed, matched nothing, and a real
    Rs 500 gain disappeared.
    """
    user = await _make_user(db, email="sameday@example.com")
    holding = await _make_holding(db, user, symbol="INTRADAY", quantity=0.0)
    trade_day = date(2025, 6, 10)

    # SELL inserted FIRST -> lower autoincrement id than its own BUY.
    sell = await _add_txn(
        db, holding, txn_type="SELL", txn_date=trade_day, quantity=10.0, price=150.0
    )
    await _add_txn(
        db, holding, txn_type="BUY", txn_date=trade_day, quantity=10.0, price=100.0
    )

    records = await compute_tax_for_transaction(sell.id, user.id, db)

    assert records, "same-day buy-then-sell produced no tax record"
    assert len(records) == 1
    assert float(records[0].gain_amount) == pytest.approx(500.0)
    # Same-day sale can never be long-term.
    assert records[0].gain_type == "STCG"


async def test_sell_with_no_lots_raises_instead_of_returning_empty(db: AsyncSession):
    """A SELL with no purchase history is an error, not a zero-tax no-op."""
    user = await _make_user(db, email="nolots@example.com")
    holding = await _make_holding(db, user, symbol="ORPHAN", quantity=0.0)
    sell = await _add_txn(
        db,
        holding,
        txn_type="SELL",
        txn_date=date(2025, 6, 10),
        quantity=10.0,
        price=150.0,
    )

    with pytest.raises(ValueError, match="No purchase lots"):
        await compute_tax_for_transaction(sell.id, user.id, db)


async def test_compute_tax_route_returns_400_for_unmatched_sell(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    """The route surfaces the unmatched-sale error as a 400 the user can read."""
    user = await _current_user(db)
    holding = await _make_holding(db, user, symbol="ORPHANAPI", quantity=0.0)
    sell = await _add_txn(
        db,
        holding,
        txn_type="SELL",
        txn_date=date(2025, 6, 10),
        quantity=5.0,
        price=200.0,
    )
    await db.commit()

    resp = await client.post(f"/api/v1/tax/compute/{sell.id}", headers=auth_headers)
    assert resp.status_code == 400
    assert "purchase lots" in resp.json()["detail"].lower()


# ===========================================================================
# 3. Trailing-12-month dividends are bounded on BOTH sides
# ===========================================================================


async def test_dividend_summary_excludes_future_dividend_from_trailing_yield(
    db: AsyncSession,
):
    """A dividend dated in the FUTURE must not inflate the trailing yield.

    Portfolio worth Rs 100,000; Rs 1,000 received 30 days ago and Rs 9,000
    declared 60 days out. The honest trailing yield is 1.0 %, not 10.0 %.
    """
    user = await _make_user(db, email="futurediv@example.com")
    holding = await _make_holding(
        db,
        user,
        symbol="YIELDCO",
        quantity=1000.0,
        avg_price=100.0,
        current_price=100.0,  # 1000 x 100 = Rs 100,000
    )
    today = date.today()
    past = today - timedelta(days=30)
    future = today + timedelta(days=60)
    for ex_date, amount in ((past, 1000.0), (future, 9000.0)):
        db.add(
            Dividend(
                holding_id=holding.id,
                ex_date=ex_date,
                amount_per_share=amount / 1000.0,
                total_amount=amount,
            )
        )
    await db.flush()

    summary = await get_dividend_summary(user.id, db)

    # Lifetime total still counts everything recorded...
    assert summary["total_dividends"] == pytest.approx(10000.0)
    # ...but the trailing-12m yield only counts what has actually gone ex.
    assert summary["dividend_yield"] == pytest.approx(1.0)
    assert summary["yield_on_cost"] == pytest.approx(1.0)

    # Calendar decision: future dividends are KEPT but flagged `projected`.
    calendar = {row["month"]: row for row in summary["calendar"]}
    assert calendar[past.strftime("%Y-%m")]["projected"] is False
    assert calendar[future.strftime("%Y-%m")]["projected"] is True
    assert calendar[future.strftime("%Y-%m")]["amount"] == pytest.approx(9000.0)


# ===========================================================================
# 4. Forward forecast anchors to TODAY, not to the last payment ever
# ===========================================================================


def _fake_dividend_ticker(pay_dates: list[str], amounts: list[float], info: dict):
    series = pd.Series(amounts, index=pd.to_datetime(pay_dates))

    class _FakeTicker:
        def __init__(self, symbol: str):
            self.symbol = symbol
            self.info = info
            self.dividends = series

    return _FakeTicker


def test_forecast_flags_stale_payer_instead_of_projecting(monkeypatch):
    """A ticker whose last dividend was years ago yields no forward income."""
    monkeypatch.setattr(
        dividend_service.yf,
        "Ticker",
        _fake_dividend_ticker(
            ["2014-12-15", "2015-06-15"], [5.0, 5.0], {"dividendRate": 10.0}
        ),
    )

    prim = dividend_service._sync_fetch_dividend_forecast("EXPAYER.NS")

    assert prim is not None
    assert prim["stale_since"] == "2015-06-15"
    assert prim["annual_rate"] == 0.0
    assert prim["pay_months"] == []
    # Nothing is projected from it.
    schedule = dividend_service._holding_monthly_schedule(
        prim, dividend_service._forward_months(2026, 1)
    )
    assert sum(schedule.values()) == 0.0


async def test_forecast_endpoint_flags_stale_payer_and_forecasts_nothing(
    db: AsyncSession, monkeypatch
):
    """End-to-end: a stale payer is listed with ``stale_since`` and adds Rs 0."""
    user = await _make_user(db, email="staleforecast@example.com")
    await _make_holding(
        db,
        user,
        symbol="EXPAYER",
        quantity=100.0,
        avg_price=100.0,
        current_price=120.0,
    )
    await db.flush()

    monkeypatch.setattr(
        dividend_service.yf,
        "Ticker",
        _fake_dividend_ticker(
            ["2014-12-15", "2015-06-15"], [5.0, 5.0], {"dividendRate": 10.0}
        ),
    )

    forecast = await dividend_service.get_dividend_forecast(user.id, db)

    assert forecast["total_forward_12m"] == 0.0
    assert all(row["amount"] == 0.0 for row in forecast["monthly"])
    assert len(forecast["by_holding"]) == 1
    assert forecast["by_holding"][0]["stale_since"] == "2015-06-15"
    assert forecast["by_holding"][0]["annual_estimate"] == 0.0


def test_forecast_still_projects_for_a_current_payer(monkeypatch):
    """A payer with dividends inside the trailing year still forecasts."""
    today = date.today()
    recent = [
        (today - timedelta(days=200)).isoformat(),
        (today - timedelta(days=30)).isoformat(),
    ]
    monkeypatch.setattr(
        dividend_service.yf,
        "Ticker",
        _fake_dividend_ticker(recent, [4.0, 4.0], {}),
    )

    prim = dividend_service._sync_fetch_dividend_forecast("PAYER.NS")

    assert prim is not None
    assert prim["stale_since"] is None
    assert prim["annual_rate"] == pytest.approx(8.0)
    assert prim["frequency"] == 2


# ===========================================================================
# 5. The intraday FX cache TTL actually fires
# ===========================================================================


async def test_forex_refetches_todays_rate_within_24h(db: AsyncSession, monkeypatch):
    """A row dated today is always younger than 24 h — the old TTL was dead.

    90 minutes old: unreachable under the previous 24-hour window, refetched
    under the corrected intraday TTL.
    """
    assert forex_service.RATE_CACHE_STALE_HOURS < 24, (
        "a >=24h TTL can never fire for a row dated today"
    )
    aged = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=90)
    db.add(
        ForexRate(
            from_currency="EUR",
            to_currency="INR",
            rate=80.0,
            date=date.today(),
            source="test",
            created_at=aged,
        )
    )
    await db.flush()

    calls: list[tuple] = []

    async def _fresh(from_currency, to_currency, target_date):
        calls.append((from_currency, to_currency, target_date))
        return 95.0

    monkeypatch.setattr(forex_service, "_fetch_rate_yfinance", _fresh)

    rate = await forex_service.get_exchange_rate("EUR", "INR", None, db)
    assert rate == 95.0
    assert len(calls) == 1


async def test_forex_serves_recent_rate_without_refetch(
    db: AsyncSession, monkeypatch
):
    """Inside the TTL the cached rate is served with no network call."""
    fresh_ts = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5)
    db.add(
        ForexRate(
            from_currency="EUR",
            to_currency="INR",
            rate=81.0,
            date=date.today(),
            source="test",
            created_at=fresh_ts,
        )
    )
    await db.flush()

    calls: list[tuple] = []

    async def _fresh(from_currency, to_currency, target_date):
        calls.append((from_currency, to_currency, target_date))
        return 95.0

    monkeypatch.setattr(forex_service, "_fetch_rate_yfinance", _fresh)

    assert await forex_service.get_exchange_rate("EUR", "INR", None, db) == 81.0
    assert calls == []


async def test_forex_falls_back_to_cache_when_refetch_fails(
    db: AsyncSession, monkeypatch
):
    """Graceful degradation survives the tighter TTL."""
    aged = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=90)
    db.add(
        ForexRate(
            from_currency="EUR",
            to_currency="INR",
            rate=82.0,
            date=date.today(),
            source="test",
            created_at=aged,
        )
    )
    await db.flush()

    async def _boom(from_currency, to_currency, target_date):
        raise RuntimeError("yfinance down")

    monkeypatch.setattr(forex_service, "_fetch_rate_yfinance", _boom)

    assert await forex_service.get_exchange_rate("EUR", "INR", None, db) == 82.0


# ===========================================================================
# 6. German allowance follows the Zuflussprinzip (payment date)
# ===========================================================================


async def test_german_allowance_uses_payment_year_not_ex_date_year(
    db: AsyncSession,
):
    """A December ex-date paid in January belongs to the PAYMENT year."""
    user = await _make_user(db, email="zufluss@example.com", currency="EUR")
    holding = await _make_holding(
        db, user, symbol="SAP", exchange="XETRA", currency="EUR"
    )
    db.add(
        Dividend(
            holding_id=holding.id,
            ex_date=date(2025, 12, 29),
            payment_date=date(2026, 1, 5),
            amount_per_share=80.0,
            total_amount=800.0,
        )
    )
    await db.flush()

    used_2025 = await compute_german_allowance(user.id, "2025", db)
    used_2026 = await compute_german_allowance(user.id, "2026", db)

    assert used_2025["used"] == 0.0
    assert used_2025["remaining"] == 1000.0
    assert used_2026["used"] == pytest.approx(800.0)
    assert used_2026["remaining"] == pytest.approx(200.0)


async def test_german_allowance_falls_back_to_ex_date_when_unpaid(db: AsyncSession):
    """Without a payment date the ex-date is still used (no data, no guess)."""
    user = await _make_user(db, email="noexpay@example.com", currency="EUR")
    holding = await _make_holding(
        db, user, symbol="BAS", exchange="XETRA", currency="EUR"
    )
    db.add(
        Dividend(
            holding_id=holding.id,
            ex_date=date(2025, 5, 2),
            payment_date=None,
            amount_per_share=30.0,
            total_amount=300.0,
        )
    )
    await db.flush()

    assert (await compute_german_allowance(user.id, "2025", db))["used"] == (
        pytest.approx(300.0)
    )


# ===========================================================================
# 7. Vorabpauschale uses real distributions and real months held
# ===========================================================================


async def test_vorabpauschale_uses_distributions_and_months_held(db: AsyncSession):
    """§18 InvStG: distributions reduce the Basisertrag, months held pro-rate it."""
    user = await _make_user(db, email="vorab@example.com", currency="EUR")
    holding = await _make_holding(
        db,
        user,
        symbol="EUNL",
        exchange="XETRA",
        currency="EUR",
        fund_type="EQUITY_ETF",
        avg_price=100.0,
        quantity=100.0,
        current_price=130.0,
    )
    # First bought in April 2025: Jan/Feb/Mar precede the acquisition month, so
    # 3/12 falls away and 13 - 4 = 9 months are counted.
    await _add_txn(
        db,
        holding,
        txn_type="BUY",
        txn_date=date(2025, 4, 10),
        quantity=100.0,
        price=100.0,
    )
    db.add(
        Dividend(
            holding_id=holding.id,
            ex_date=date(2025, 7, 1),
            payment_date=date(2025, 7, 10),
            amount_per_share=1.0,
            total_amount=100.0,
        )
    )
    await db.flush()

    result = await estimate_portfolio_vorabpauschale(
        holding.portfolio_id, db, year=2025
    )
    fund = result["funds"][0]

    assert fund["months_held"] == 9
    assert fund["distributions"] == pytest.approx(100.0)

    basiszins = result["basiszins_pct"]
    basisertrag = 10_000.0 * (basiszins / 100.0) * 0.7 * (9 / 12)
    expected_gross = max(0.0, min(basisertrag - 100.0, 3_000.0))
    assert fund["vorabpauschale"] == pytest.approx(round(expected_gross, 2))


# ===========================================================================
# 8. A price of 0 triggers the stop-loss
# ===========================================================================


async def test_stop_loss_triggers_at_zero_price(db: AsyncSession):
    """A collapsed / suspended price of 0 is the WORST case, not a non-event."""
    user = await _make_user(db, email="stoploss@example.com")
    holding = await _make_holding(
        db,
        user,
        symbol="COLLAPSE",
        current_price=0.0,
        custom_fields={"stop_loss_price": 50.0},
    )

    statuses = await get_stop_loss_holdings(holding.portfolio_id, db)

    assert len(statuses) == 1
    assert statuses[0].is_triggered is True
    assert statuses[0].distance_pct == pytest.approx(-100.0)


async def test_stop_loss_unknown_price_is_not_triggered(db: AsyncSession):
    """A missing price is still unknown — never reported as triggered."""
    user = await _make_user(db, email="stoplossnone@example.com")
    holding = await _make_holding(
        db,
        user,
        symbol="NOPRICE",
        current_price=None,
        custom_fields={"stop_loss_price": 50.0},
    )

    statuses = await get_stop_loss_holdings(holding.portfolio_id, db)

    assert statuses[0].is_triggered is False
    assert statuses[0].distance_pct is None


# ===========================================================================
# 9. Fixed-income assets can be revalued
# ===========================================================================


async def test_patch_asset_updates_user_maintained_value(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """FD / bond / property values are user-maintained — PATCH keeps them honest."""
    created = await client.post(
        "/api/v1/net-worth/assets",
        json={
            "asset_type": "FIXED_DEPOSIT",
            "name": "HDFC FD",
            "quantity": 1,
            "purchase_price": 100000.0,
            "current_value": 100000.0,
            "currency": "INR",
            "interest_rate": 7.1,
        },
        headers=auth_headers,
    )
    assert created.status_code == 201
    asset_id = created.json()["id"]

    resp = await client.patch(
        f"/api/v1/net-worth/assets/{asset_id}",
        json={"current_value": 107100.0, "notes": "after 1 year"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_value"] == pytest.approx(107100.0)
    assert data["notes"] == "after 1 year"
    # Untouched fields survive a partial update.
    assert data["name"] == "HDFC FD"
    assert data["interest_rate"] == pytest.approx(7.1)
    assert data["asset_type"] == "FIXED_DEPOSIT"


async def test_patch_asset_of_another_user_is_404(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    """Ownership is enforced exactly like the add/remove routes."""
    other = await _make_user(db, email="otherowner@example.com")
    asset = Asset(
        user_id=other.id,
        asset_type="BOND",
        name="Someone else's bond",
        quantity=1,
        purchase_price=5000.0,
        current_value=5000.0,
        currency="INR",
    )
    db.add(asset)
    await db.commit()

    resp = await client.patch(
        f"/api/v1/net-worth/assets/{asset.id}",
        json={"current_value": 999999.0},
        headers=auth_headers,
    )
    assert resp.status_code == 404

    # And the value is untouched.
    await db.refresh(asset)
    assert float(asset.current_value) == pytest.approx(5000.0)


async def test_patch_asset_ignores_explicit_nulls_on_required_fields(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """An explicit null for a NOT NULL column is dropped, not written."""
    created = await client.post(
        "/api/v1/net-worth/assets",
        json={
            "asset_type": "REAL_ESTATE",
            "name": "Flat",
            "quantity": 1,
            "purchase_price": 5000000.0,
            "current_value": 6000000.0,
            "currency": "INR",
            "notes": "temp note",
        },
        headers=auth_headers,
    )
    asset_id = created.json()["id"]

    resp = await client.patch(
        f"/api/v1/net-worth/assets/{asset_id}",
        json={"currency": None, "name": None, "notes": None},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["currency"] == "INR"
    assert data["name"] == "Flat"
    # Nullable fields CAN be cleared.
    assert data["notes"] is None


async def test_patch_missing_asset_is_404(
    client: AsyncClient, auth_headers: dict[str, str]
):
    resp = await client.patch(
        "/api/v1/net-worth/assets/999999",
        json={"current_value": 1.0},
        headers=auth_headers,
    )
    assert resp.status_code == 404
