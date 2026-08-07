"""Wave-2 finance-service fixes: verified-bug regression tests.

Covers:

1.  Benchmark comparison: fewer than two aligned portfolio points (or a
    zero-value start) reports ``insufficient_history`` honestly — the old
    silent fallback to the unclipped series is gone.
2.  Indian FY exemption netting is order-independent: netting is strictly
    against PRECEDING sales and recomputing an earlier sale cascades a
    recompute over the later ones.
3.  German sale-path Freibetrag now subtracts German dividends (previously
    only ``compute_german_allowance`` counted them).
4.  ``generate_tax_summary`` (DE) delegates to ``compute_german_allowance``
    (filing-aware, Teilfreistellung-aware) instead of a hardcoded €1000 cap.
5.  ``goal.is_achieved`` is two-way: raising the target un-achieves.
6.  Stock comparison: a legitimate 0.0% day change stays 0.0, not None.
7.  ``forex_service.RateCache``: one fetch per pair; failures memoized.
8.  Dividend summary converts per-holding currencies into the user's
    preferred currency before summing (no raw INR+EUR addition).
9.  ``fetch_index_window`` extraction: whatif's benchmark return delegates.
10. FIFO ``_replay_fifo`` consolidation: open + consumed lots stay coherent.

Run with:
    uv run pytest tests/test_wave2_finance.py -q
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.benchmark_service as benchmark_service
import app.services.comparison_service as comparison_service
import app.services.forex_service as forex_service
import app.services.tax_service as tax_service
import app.services.whatif_service as whatif_service
from app.models.dividend import Dividend
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.tax_record import TaxRecord
from app.models.transaction import Transaction
from app.models.user import User
from app.models.user_preferences import UserPreferences
from app.schemas.goal import GoalCreate, GoalUpdate
from app.services.dividend_service import get_dividend_summary
from app.services.goal_service import create_goal, update_goal
from app.services.tax_service import (
    INDIA_LTCG_EXEMPTION,
    INDIA_LTCG_RATE,
    _build_consumed_lots,
    build_open_lots,
    compute_german_allowance,
    compute_tax_for_transaction,
    generate_tax_summary,
)

# ---------------------------------------------------------------------------
# ORM builder helpers (mirroring test_fifo_tax.py)
# ---------------------------------------------------------------------------


async def _make_user(
    db: AsyncSession, email: str, currency: str = "INR"
) -> User:
    user = User(
        email=email,
        password_hash="x",
        display_name="Wave2 Tester",
        preferred_currency=currency,
    )
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
    portfolio = Portfolio(
        user_id=user.id, name=f"P-{symbol}", currency=currency
    )
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
            TaxRecord.user_id == user_id,
            TaxRecord.financial_year == fy,
        )
    )
    return sum(float(r.tax_amount or 0.0) for r in result.scalars().all())


def _fake_benchmark_ticker(dates: list[date], closes: list[float]):
    df = pd.DataFrame(
        {"Close": closes},
        index=pd.to_datetime([d.isoformat() for d in dates]),
    )

    class _FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, start=None, end=None):
            return df

    return _FakeTicker


# ===========================================================================
# 1. Benchmark: no silent fallback to the unclipped series
# ===========================================================================


@pytest.mark.asyncio
async def test_benchmark_no_fallback_when_portfolio_outside_window(monkeypatch):
    """Portfolio history that lies entirely BEFORE the benchmark window used
    to be silently substituted unclipped (fabricating alpha). Now it reports
    insufficient_history with null portfolio return / alpha."""
    today = date.today()
    bench_dates = [today - timedelta(days=i) for i in range(20, 0, -1)]
    closes = [100.0 + i for i in range(len(bench_dates))]
    monkeypatch.setattr(
        benchmark_service.yf, "Ticker", _fake_benchmark_ticker(bench_dates, closes)
    )

    # Plenty of points — but all older than the benchmark window.
    stale = [
        {"date": (today - timedelta(days=100 + i)).isoformat(), "value": 1000.0 + i}
        for i in range(30)
    ]
    result = await benchmark_service.compare_with_benchmark(
        stale, benchmark_name="NIFTY50", days=30
    )
    assert result is not None
    assert result.insufficient_history is True
    assert result.portfolio_return_pct is None
    assert result.alpha is None
    # The benchmark's own return is still computed honestly.
    assert result.benchmark_return_pct is not None


@pytest.mark.asyncio
async def test_benchmark_single_aligned_point_is_insufficient(monkeypatch):
    today = date.today()
    bench_dates = [today - timedelta(days=i) for i in range(10, 0, -1)]
    closes = [100.0] * len(bench_dates)
    monkeypatch.setattr(
        benchmark_service.yf, "Ticker", _fake_benchmark_ticker(bench_dates, closes)
    )

    one_point = [{"date": bench_dates[3].isoformat(), "value": 5000.0}]
    result = await benchmark_service.compare_with_benchmark(
        one_point, benchmark_name="NIFTY50", days=30
    )
    assert result is not None
    assert result.insufficient_history is True
    assert result.alpha is None


@pytest.mark.asyncio
async def test_benchmark_zero_value_start_not_fabricated_as_zero_return(monkeypatch):
    """A zero-value series start has no meaningful return — previously it was
    fabricated as 0.0%; now it is reported as insufficient."""
    today = date.today()
    bench_dates = [today - timedelta(days=i) for i in range(10, 0, -1)]
    closes = [100.0 + i for i in range(len(bench_dates))]
    monkeypatch.setattr(
        benchmark_service.yf, "Ticker", _fake_benchmark_ticker(bench_dates, closes)
    )

    pf = [{"date": d.isoformat(), "value": 0.0 if i == 0 else 1000.0}
          for i, d in enumerate(bench_dates)]
    result = await benchmark_service.compare_with_benchmark(
        pf, benchmark_name="NIFTY50", days=30
    )
    assert result is not None
    assert result.insufficient_history is True
    assert result.portfolio_return_pct is None
    assert result.alpha is None


@pytest.mark.asyncio
async def test_benchmark_zero_portfolio_value_day_kept_in_data_points(monkeypatch):
    """A legitimate 0-value day normalizes to 0.0 — not dropped to None by a
    falsy-zero guard."""
    today = date.today()
    bench_dates = [today - timedelta(days=i) for i in range(5, 0, -1)]
    closes = [100.0, 101.0, 102.0, 103.0, 104.0]
    monkeypatch.setattr(
        benchmark_service.yf, "Ticker", _fake_benchmark_ticker(bench_dates, closes)
    )

    pf = [{"date": d.isoformat(), "value": 1000.0} for d in bench_dates]
    pf[2]["value"] = 0.0  # mid-series zero
    result = await benchmark_service.compare_with_benchmark(
        pf, benchmark_name="NIFTY50", days=30
    )
    assert result is not None
    zero_day = next(
        p for p in result.data_points if p["date"] == bench_dates[2].isoformat()
    )
    assert zero_day["portfolio_value"] == 0.0


# ===========================================================================
# 2. Indian FY netting: order-independent + cascade on recompute
# ===========================================================================


SALE_A_DATE = date(2025, 6, 1)
SALE_B_DATE = date(2025, 8, 1)
BUY_1_DATE = date(2023, 1, 10)
BUY_2_DATE = date(2023, 2, 10)


async def _two_ltcg_sells(db: AsyncSession, user: User):
    """Two 100k LTCG sells in the same FY (2025-26), FIFO over two lots."""
    holding = await _make_holding(db, user, avg_price=100.0, quantity=20.0)
    await _add_txn(db, holding, txn_type="BUY", txn_date=BUY_1_DATE, quantity=10, price=100)
    await _add_txn(db, holding, txn_type="BUY", txn_date=BUY_2_DATE, quantity=10, price=100)
    sell_a = await _add_txn(
        db, holding, txn_type="SELL", txn_date=SALE_A_DATE, quantity=10, price=10100
    )
    sell_b = await _add_txn(
        db, holding, txn_type="SELL", txn_date=SALE_B_DATE, quantity=10, price=10100
    )
    return sell_a, sell_b


@pytest.mark.asyncio
async def test_fy_netting_is_order_independent(db: AsyncSession):
    """Computing B (the later sell) before A yields the same FY total tax as
    the canonical chronological order: the cascade re-nets B against A."""
    # Canonical order: A then B.
    user1 = await _make_user(db, "order1@example.com")
    a1, b1 = await _two_ltcg_sells(db, user1)
    await compute_tax_for_transaction(a1.id, user1.id, db)
    await compute_tax_for_transaction(b1.id, user1.id, db)

    # Reverse order: B then A (the old code let A re-net against B's records,
    # double-spending the exemption).
    user2 = await _make_user(db, "order2@example.com")
    a2, b2 = await _two_ltcg_sells(db, user2)
    await compute_tax_for_transaction(b2.id, user2.id, db)
    await compute_tax_for_transaction(a2.id, user2.id, db)

    # Combined taxable == net gains - exemption, in both orders.
    expected_total_tax = round(
        (200_000.0 - INDIA_LTCG_EXEMPTION) * INDIA_LTCG_RATE, 2
    )
    assert await _fy_total_tax(db, user1.id, "2025-26") == expected_total_tax
    assert await _fy_total_tax(db, user2.id, "2025-26") == expected_total_tax

    # The allocation itself is chronological in both cases: A (earlier) uses
    # the exemption first and pays nothing; B pays on the remainder.
    for user, sell_b in ((user1, b1), (user2, b2)):
        res = await db.execute(
            select(TaxRecord).where(TaxRecord.transaction_id == sell_b.id)
        )
        rec_b = res.scalars().one()
        assert float(rec_b.tax_amount) == expected_total_tax, (
            f"user {user.id}: later sale should carry the whole tax"
        )


@pytest.mark.asyncio
async def test_editing_earlier_sell_cascades_to_later_sell(db: AsyncSession):
    """Editing sale A (already computed) and recomputing it re-nets sale B —
    the year's taxable amount always equals net gains − exemption."""
    user = await _make_user(db, "cascade@example.com")
    sell_a, sell_b = await _two_ltcg_sells(db, user)
    await compute_tax_for_transaction(sell_a.id, user.id, db)
    await compute_tax_for_transaction(sell_b.id, user.id, db)

    # Sanity: canonical totals first.
    assert await _fy_total_tax(db, user.id, "2025-26") == round(
        (200_000.0 - INDIA_LTCG_EXEMPTION) * INDIA_LTCG_RATE, 2
    )

    # Edit sale A: price drops 10100 -> 5100, so its gain halves to 50k.
    sell_a.price = 5100
    await db.flush()
    await compute_tax_for_transaction(sell_a.id, user.id, db)

    # A: 50k gain fully inside the exemption -> 0 tax.
    res_a = await db.execute(
        select(TaxRecord).where(TaxRecord.transaction_id == sell_a.id)
    )
    rec_a = res_a.scalars().one()
    assert float(rec_a.gain_amount) == 50_000.0
    assert float(rec_a.tax_amount) == 0.0

    # B was recomputed by the cascade: remaining exemption 75k -> taxable 25k.
    res_b = await db.execute(
        select(TaxRecord).where(TaxRecord.transaction_id == sell_b.id)
    )
    rec_b = res_b.scalars().one()
    expected_b_tax = round(
        (150_000.0 - INDIA_LTCG_EXEMPTION) * INDIA_LTCG_RATE, 2
    )
    assert float(rec_b.tax_amount) == expected_b_tax

    # Combined taxable == net - exemption after the edit.
    assert await _fy_total_tax(db, user.id, "2025-26") == expected_b_tax


# ===========================================================================
# 3. German sale-path Freibetrag subtracts German dividends
# ===========================================================================


@pytest.mark.asyncio
async def test_de_sale_after_dividends_exhausts_freibetrag(db: AsyncSession):
    """EUR 1,200 of German dividends exhaust the EUR 1,000 Freibetrag, so a
    subsequent EUR 1,000 gain is fully taxable (tax > 0). The old sale path
    ignored dividends and would have taxed nothing."""
    user = await _make_user(db, "dedivs@example.com", currency="EUR")
    holding = await _make_holding(
        db, user, symbol="SAP", exchange="XETRA", currency="EUR",
        fund_type=None, avg_price=50.0, quantity=100.0,
    )
    db.add(
        Dividend(
            holding_id=holding.id,
            ex_date=date(2024, 5, 1),
            amount_per_share=12.0,
            total_amount=1200.0,
        )
    )
    await db.flush()

    await _add_txn(db, holding, txn_type="BUY", txn_date=date(2020, 1, 1), quantity=100, price=50)
    sell = await _add_txn(
        db, holding, txn_type="SELL", txn_date=date(2024, 6, 1), quantity=100, price=60
    )

    records = await compute_tax_for_transaction(sell.id, user.id, db)
    assert len(records) == 1
    rec = records[0]
    assert float(rec.gain_amount) == 1000.0
    # Freibetrag fully consumed by dividends -> whole 1000 taxable:
    # kap 250.00 + soli 13.75 = 263.75.
    assert float(rec.tax_amount) == 263.75
    assert float(rec.tax_amount) > 0

    # The standalone allowance tracker agrees with the sale path.
    allowance = await compute_german_allowance(user.id, "2024", db)
    assert allowance["remaining"] == 0.0


# ===========================================================================
# 4. DE tax summary delegates to the allowance tracker
# ===========================================================================


@pytest.mark.asyncio
async def test_de_summary_uses_filing_aware_allowance(db: AsyncSession):
    """Joint filers have a EUR 2,000 allowance; the summary used to hardcode
    the single EUR 1,000 cap over gross gains."""
    user = await _make_user(db, "desummary@example.com", currency="EUR")
    db.add(UserPreferences(user_id=user.id, tax_settings={"filing": "joint"}))
    db.add(
        TaxRecord(
            user_id=user.id,
            transaction_id=None,
            financial_year="2024",
            tax_jurisdiction="DE",
            gain_type="ABGELTUNGSSTEUER",
            purchase_date=date(2024, 1, 1),
            sale_date=date(2024, 6, 1),
            purchase_price=1000.0,
            sale_price=2500.0,
            gain_amount=1500.0,
            tax_amount=0.0,
            currency="EUR",
        )
    )
    await db.flush()

    summary = await generate_tax_summary(user.id, "2024", "DE", db)
    # Old behavior: min(1500, 1000) == 1000. Filing-aware: 1500 of 2000.
    assert summary["exemption_used"] == 1500.0

    allowance = await compute_german_allowance(user.id, "2024", db)
    assert summary["exemption_used"] == allowance["used"]


# ===========================================================================
# 5. goal.is_achieved is two-way
# ===========================================================================


@pytest.mark.asyncio
async def test_goal_unachieves_when_target_raised(db: AsyncSession):
    user = await _make_user(db, "goal@example.com")
    goal = await create_goal(
        user.id,
        GoalCreate(name="House", target_amount=1000.0, category="HOME"),
        db,
    )
    goal = await update_goal(
        goal.id, user.id, GoalUpdate(current_amount=1500.0), db
    )
    assert goal.is_achieved is True

    # Raising the target above the current amount must un-achieve.
    goal = await update_goal(
        goal.id, user.id, GoalUpdate(target_amount=2000.0), db
    )
    assert goal.is_achieved is False

    # A value drop below the target also un-achieves.
    goal = await update_goal(
        goal.id, user.id, GoalUpdate(target_amount=1400.0), db
    )
    assert goal.is_achieved is True
    goal = await update_goal(
        goal.id, user.id, GoalUpdate(current_amount=100.0), db
    )
    assert goal.is_achieved is False


# ===========================================================================
# 6. Comparison: 0.0% day change stays 0.0
# ===========================================================================


@pytest.mark.asyncio
async def test_comparison_zero_day_change_not_none(monkeypatch):
    def _fake_fetch(yf_symbol: str, days: int):
        info = {
            "currentPrice": 100.0,
            "previousClose": 100.0,  # flat day -> 0.0 % change
            "shortName": "Flat Corp",
        }
        return info, [{"date": "2026-08-01", "close": 100.0}]

    monkeypatch.setattr(
        comparison_service, "_sync_fetch_stock_data", _fake_fetch
    )

    result = await comparison_service.compare_stocks(["TCS"], ["NSE"], days=30)
    assert len(result.stocks) == 1
    assert result.stocks[0].day_change_pct == 0.0  # not None


# ===========================================================================
# 7. RateCache: one fetch per pair, failures memoized
# ===========================================================================


@pytest.mark.asyncio
async def test_rate_cache_single_fetch_per_pair(monkeypatch):
    calls: list[tuple[str, str]] = []

    async def _fake_rate(from_currency, to_currency, target_date, db):
        calls.append((from_currency, to_currency))
        if from_currency == "USD":
            raise RuntimeError("no rate")
        return 90.0

    monkeypatch.setattr(forex_service, "get_exchange_rate", _fake_rate)

    cache = forex_service.RateCache("INR", db=None)  # type: ignore[arg-type]

    assert await cache.to_base(10.0, "EUR") == (900.0, True)
    assert await cache.to_base(20.0, "EUR") == (1800.0, True)  # cached
    assert await cache.to_base(5.0, "INR") == (5.0, True)      # identity, no fetch
    assert await cache.to_base(7.0, "usd") == (7.0, False)     # failed, native
    assert await cache.to_base(8.0, "USD") == (8.0, False)     # failure memoized

    assert calls == [("EUR", "INR"), ("USD", "INR")]


# ===========================================================================
# 8. Dividend summary converts currencies before summing
# ===========================================================================


@pytest.mark.asyncio
async def test_dividend_summary_converts_currencies(db: AsyncSession, monkeypatch):
    async def _fake_rate(from_currency, to_currency, target_date, session):
        assert (from_currency, to_currency) == ("EUR", "INR")
        return 90.0

    monkeypatch.setattr(forex_service, "get_exchange_rate", _fake_rate)

    user = await _make_user(db, "divfx@example.com", currency="INR")
    inr_holding = await _make_holding(
        db, user, symbol="RELIANCE", exchange="NSE", currency="INR",
        avg_price=100.0, quantity=10.0,
    )
    inr_holding.current_price = 110.0  # value 1,100 INR
    eur_holding = await _make_holding(
        db, user, symbol="SAP", exchange="XETRA", currency="EUR",
        avg_price=40.0, quantity=5.0,
    )
    eur_holding.current_price = 50.0   # value 250 EUR -> 22,500 INR

    recent = date.today() - timedelta(days=10)
    db.add(
        Dividend(
            holding_id=inr_holding.id, ex_date=recent,
            amount_per_share=10.0, total_amount=100.0,
        )
    )
    db.add(
        Dividend(
            holding_id=eur_holding.id, ex_date=recent,
            amount_per_share=2.0, total_amount=10.0,  # EUR -> 900 INR
        )
    )
    await db.flush()

    summary = await get_dividend_summary(user.id, db)

    assert summary["currency"] == "INR"
    # 100 INR + 10 EUR * 90 = 1,000 INR (the old code reported 110).
    assert summary["total_dividends"] == 1000.0
    # Yield over the converted portfolio value: 1,100 + 22,500 = 23,600 INR.
    assert summary["dividend_yield"] == round(1000.0 / 23_600.0 * 100, 2)
    # Calendar buckets are converted too.
    month_key = recent.strftime("%Y-%m")
    month_row = next(r for r in summary["calendar"] if r["month"] == month_key)
    assert month_row["amount"] == 1000.0


# ===========================================================================
# 9. fetch_index_window extraction: whatif delegates
# ===========================================================================


@pytest.mark.asyncio
async def test_whatif_benchmark_delegates_to_index_window(monkeypatch):
    today = date.today()
    bench_dates = [today - timedelta(days=i) for i in range(10, 0, -1)]
    closes = [100.0 + i for i in range(len(bench_dates))]
    monkeypatch.setattr(
        benchmark_service.yf, "Ticker", _fake_benchmark_ticker(bench_dates, closes)
    )

    result = await whatif_service._fetch_benchmark_return(
        "NIFTY50", bench_dates[0], bench_dates[-1]
    )
    assert result is not None
    assert result["benchmark_name"] == "NIFTY50"
    assert result["benchmark_start_price"] == closes[0]
    assert result["benchmark_end_price"] == closes[-1]
    expected = round((closes[-1] - closes[0]) / closes[0] * 100, 2)
    assert result["benchmark_return_pct"] == expected


@pytest.mark.asyncio
async def test_fetch_index_window_unknown_benchmark_none():
    assert await benchmark_service.fetch_index_window(
        "NOT_A_BENCHMARK", date(2024, 1, 1), date(2024, 2, 1)
    ) is None


# ===========================================================================
# 10. FIFO replay consolidation: open + consumed lots stay coherent
# ===========================================================================


def _txn(txn_id, txn_type, txn_date, qty, price):
    return SimpleNamespace(
        id=txn_id,
        transaction_type=txn_type,
        date=txn_date,
        quantity=qty,
        price=price,
    )


def test_replay_fifo_open_and_consumed_lots_coherent():
    txns = [
        _txn(1, "BUY", date(2024, 1, 1), 10, 100.0),
        _txn(2, "BUY", date(2024, 2, 1), 10, 200.0),
        _txn(3, "SELL", date(2024, 6, 1), 15, 300.0),
    ]

    consumed = _build_consumed_lots(txns, taxed_txn_id=3)
    assert [(lot["qty"], lot["price"]) for lot in consumed] == [
        (10.0, 100.0),
        (5.0, 200.0),
    ]

    open_lots = build_open_lots(txns)
    assert [(lot["qty"], lot["price"]) for lot in open_lots] == [(5.0, 200.0)]

    # Conservation: bought 20 == consumed 15 + still open 5.
    assert sum(lot["qty"] for lot in consumed) + sum(
        lot["qty"] for lot in open_lots
    ) == 20.0

    # Both wrappers drive the same replay engine.
    open_direct, consumed_direct = tax_service._replay_fifo(txns, taxed_txn_id=3)
    assert consumed_direct == consumed
    # With a taxed txn the replay stops at that SELL; a full replay gives the
    # final open lots.
    assert tax_service._replay_fifo(txns)[0] == open_lots
    assert open_direct == open_lots  # sell 3 is the last txn here anyway
