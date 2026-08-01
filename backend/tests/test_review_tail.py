"""Regression tests for the review-tail LOW-priority fixes.

Covers:
1. German church-tax (Kirchensteuer) reduced-rate formula — the deductible
   Sonderausgabenabzug lowers the Kapitalertragsteuer; the default
   ``church_tax=False`` path stays numerically unchanged.
2. FMV 31-Jan-2018 grandfathering cache — a failed (None) lookup is NOT cached
   and is retried on the next call.
3. Net-worth FX fallback — an item whose currency has no available rate is
   flagged ``unconverted`` and excluded from the base-currency total instead of
   being silently mixed in 1:1.
4. Efficient frontier — returned points are non-dominated (an actual upper hull)
   and deterministic across runs.
5. Recurring-transaction detection — weekly / bi-weekly / monthly / quarterly
   cadences are all recognised via the median-gap clustering.
6. Forex cache staleness — a stale same-day cached rate is refetched; a fresh
   one is served without a network call.

Run with:
    uv run pytest tests/test_review_tail.py -q
"""

from __future__ import annotations

import sys
import types
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.forex_service as forex_service
import app.services.tax_service as tax_service
from app.ml.portfolio_optimizer import _generate_efficient_frontier
from app.models.forex_rates import ForexRate
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.user import User
from app.services.net_worth_service import get_net_worth
from app.services.recurring_detection_service import (
    _classify_frequency,
    _intervals_regular,
)
from app.services.tax_service import calculate_german_tax

# ===========================================================================
# 1. German church-tax reduced-rate formula
# ===========================================================================


def test_church_tax_uses_reduced_kapest_rate():
    """Church tax is deductible: KapESt = gain * 0.25 / (1 + 0.25 * KiSt).

    For a 10 000 EUR taxable gain (no Freibetrag, no Teilfreistellung) the
    reduced Kapitalertragsteuer is 2500 / 1.02 = 2450.98, NOT the naive 2500.
    """
    res = calculate_german_tax(
        10_000.0, freibetrag_remaining=0.0, church_tax=True, church_tax_rate=0.08
    )
    kap = res["breakdown"]["kapitalertragsteuer"]

    # Reduced base tax (2450.98) is strictly below the naive flat 25 % (2500).
    assert kap == pytest.approx(2450.98, abs=0.01)
    assert kap < 2500.0

    # Soli and Kirchensteuer are charged on the REDUCED KapESt.
    assert res["breakdown"]["solidaritaetszuschlag"] == pytest.approx(134.80, abs=0.01)
    assert res["breakdown"]["kirchensteuer"] == pytest.approx(196.08, abs=0.01)

    # Total is below the naive church-tax total (2500 * (1 + .055 + .08) = 2837.50).
    assert res["tax_amount"] == pytest.approx(2781.86, abs=0.02)
    assert res["tax_amount"] < 2837.50


def test_church_tax_bavaria_9_percent():
    """A 9 % KiSt state uses denominator 1.0225 -> KapESt 2444.99."""
    res = calculate_german_tax(
        10_000.0, freibetrag_remaining=0.0, church_tax=True, church_tax_rate=0.09
    )
    assert res["breakdown"]["kapitalertragsteuer"] == pytest.approx(2444.99, abs=0.01)


def test_church_tax_false_unchanged():
    """church_tax=False must be numerically identical to the old behaviour."""
    res = calculate_german_tax(10_000.0, freibetrag_remaining=0.0)
    assert res["breakdown"]["kapitalertragsteuer"] == 2500.0
    assert res["breakdown"]["solidaritaetszuschlag"] == 137.5
    assert res["breakdown"]["kirchensteuer"] == 0.0
    # 25 % * 1.055 * 10000 = 2637.50 (effective 26.375 %).
    assert res["tax_amount"] == 2637.5
    assert res["rate_applied"] == 0.26375


# ===========================================================================
# 2. FMV 31-Jan-2018 cache retries after a failed (None) lookup
# ===========================================================================


class _FakeHist:
    """Minimal stand-in for a yfinance history DataFrame."""

    def __init__(self, rows: list[tuple[date, float]]) -> None:
        self._rows = rows
        self.empty = len(rows) == 0

    def iterrows(self):
        for d, close in self._rows:
            yield d, {"Close": close}


class _FakeTicker:
    def __init__(self, next_hist) -> None:
        self._next_hist = next_hist

    def history(self, start=None, end=None):  # noqa: ARG002 - signature parity
        return self._next_hist()


async def test_fmv_cache_retries_after_none(monkeypatch):
    """First (failed) lookup returns None and is NOT cached; the second call
    retries, succeeds, and only then caches the value."""
    tax_service._FMV_2018_CACHE.pop("RELIANCE:NSE", None)

    seq = [
        _FakeHist([]),  # call 1: no data -> None
        _FakeHist([(date(2018, 1, 31), 1234.5)]),  # call 2: real close
    ]
    counter = {"n": 0}

    def _next_hist():
        h = seq[counter["n"]]
        counter["n"] += 1
        return h

    fake_yf = types.ModuleType("yfinance")
    fake_yf.Ticker = lambda symbol: _FakeTicker(_next_hist)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    first = await tax_service.get_fmv_31jan2018("RELIANCE", "NSE")
    assert first is None
    # A failure must NOT be memoised.
    assert "RELIANCE:NSE" not in tax_service._FMV_2018_CACHE

    second = await tax_service.get_fmv_31jan2018("RELIANCE", "NSE")
    assert second == 1234.5
    assert tax_service._FMV_2018_CACHE["RELIANCE:NSE"] == 1234.5
    assert counter["n"] == 2  # both calls actually hit the fetch path


# ===========================================================================
# 3. Net-worth marks an item unconverted when the FX rate is missing
# ===========================================================================


async def _make_user(db: AsyncSession, email: str, currency: str = "INR") -> User:
    user = User(
        email=email,
        password_hash="x",
        display_name="NW Tester",
        preferred_currency=currency,
    )
    db.add(user)
    await db.flush()
    return user


async def test_net_worth_flags_unconverted_when_rate_missing(db, monkeypatch):
    """A USD holding with no USD->INR rate is flagged unconverted and excluded
    from the base-currency total (never counted 1:1)."""

    async def _raise_no_rate(*args, **kwargs):
        raise RuntimeError("no rate")

    monkeypatch.setattr(forex_service, "get_exchange_rate", _raise_no_rate)

    user = await _make_user(db, "nw@example.com", currency="INR")
    portfolio = Portfolio(user_id=user.id, name="P", currency="USD")
    db.add(portfolio)
    await db.flush()
    holding = Holding(
        portfolio_id=portfolio.id,
        stock_symbol="AAPL",
        stock_name="Apple",
        exchange="NASDAQ",
        currency="USD",
        cumulative_quantity=10.0,
        average_price=100.0,
        current_price=150.0,
    )
    db.add(holding)
    await db.flush()

    result = await get_net_worth(user.id, db)

    assert result["currency"] == "INR"
    stock_group = next(b for b in result["breakdown"] if b["asset_type"] == "STOCK")
    item = stock_group["items"][0]
    assert item["unconverted"] is True
    assert item["current_value"] == 1500.0  # native USD value, unchanged
    # Excluded from the base-currency aggregates rather than mixed in 1:1.
    assert stock_group["total_value"] == 0.0
    assert result["total_net_worth"] == 0.0


async def test_net_worth_converts_when_rate_available(db, monkeypatch):
    """With a rate present the item converts and contributes to the total."""

    async def _rate(from_currency, to_currency, target_date, session):
        return 80.0  # 1 USD = 80 INR

    monkeypatch.setattr(forex_service, "get_exchange_rate", _rate)

    user = await _make_user(db, "nw2@example.com", currency="INR")
    portfolio = Portfolio(user_id=user.id, name="P", currency="USD")
    db.add(portfolio)
    await db.flush()
    holding = Holding(
        portfolio_id=portfolio.id,
        stock_symbol="AAPL",
        stock_name="Apple",
        exchange="NASDAQ",
        currency="USD",
        cumulative_quantity=10.0,
        average_price=100.0,
        current_price=150.0,
    )
    db.add(holding)
    await db.flush()

    result = await get_net_worth(user.id, db)
    stock_group = next(b for b in result["breakdown"] if b["asset_type"] == "STOCK")
    item = stock_group["items"][0]
    assert "unconverted" not in item
    assert item["value_in_base"] == 120000.0  # 1500 USD * 80
    assert stock_group["total_value"] == 120000.0
    assert result["total_net_worth"] == 120000.0


# ===========================================================================
# 4. Efficient frontier — non-dominated and deterministic
# ===========================================================================


def _sample_market():
    mean_daily = np.array([0.0010, 0.0012, 0.0008])
    cov_daily = np.array(
        [
            [0.00040, 0.00010, 0.00005],
            [0.00010, 0.00050, 0.00010],
            [0.00005, 0.00010, 0.00030],
        ]
    )
    return mean_daily, cov_daily


def test_efficient_frontier_points_are_non_dominated():
    mean_daily, cov_daily = _sample_market()
    frontier = _generate_efficient_frontier(mean_daily, cov_daily, n=3)

    assert len(frontier) >= 2
    # No point may have BOTH a higher return AND a lower volatility than another.
    for a in frontier:
        for b in frontier:
            if a is b:
                continue
            dominates = a["return"] > b["return"] and a["volatility"] < b["volatility"]
            assert not dominates, f"{a} dominates {b} — not an efficient envelope"

    # Sorted by volatility, return is monotonically non-decreasing (upper hull).
    by_vol = sorted(frontier, key=lambda p: p["volatility"])
    returns = [p["return"] for p in by_vol]
    assert returns == sorted(returns)


def test_efficient_frontier_is_deterministic():
    mean_daily, cov_daily = _sample_market()
    first = _generate_efficient_frontier(mean_daily, cov_daily, n=3)
    second = _generate_efficient_frontier(mean_daily, cov_daily, n=3)
    assert first == second


# ===========================================================================
# 5. Recurring detection — weekly / bi-weekly / monthly / quarterly
# ===========================================================================


def _series(start: date, gap_days: int, count: int) -> list[date]:
    return [start + timedelta(days=gap_days * i) for i in range(count)]


@pytest.mark.parametrize(
    ("gap", "expected"),
    [
        (7, "weekly"),
        (14, "bi-weekly"),
        (30, "monthly"),
        (91, "quarterly"),
    ],
)
def test_recurring_classifies_all_cadences(gap: int, expected: str):
    dates = _series(date(2025, 1, 1), gap, 5)
    regular, avg_interval = _intervals_regular(dates)
    assert regular is True
    assert _classify_frequency(avg_interval) == expected


def test_recurring_monthly_still_detected_like_before():
    """The original monthly path (exactly 30-day gaps) is unchanged."""
    dates = _series(date(2025, 1, 1), 30, 4)
    regular, avg_interval = _intervals_regular(dates)
    assert regular is True
    assert avg_interval == 30.0
    assert _classify_frequency(avg_interval) == "monthly"


def test_recurring_irregular_series_rejected():
    """A wildly irregular series is not flagged as recurring."""
    dates = [date(2025, 1, 1), date(2025, 1, 8), date(2025, 4, 1), date(2025, 4, 3)]
    regular, _ = _intervals_regular(dates)
    assert regular is False


# ===========================================================================
# 6. Forex cache staleness wiring
# ===========================================================================


async def test_forex_refetches_stale_same_day_rate(db, monkeypatch):
    """A same-day cached rate older than RATE_CACHE_STALE_HOURS is refetched."""
    today = date.today()
    stale_ts = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        hours=forex_service.RATE_CACHE_STALE_HOURS + 1
    )
    db.add(
        ForexRate(
            from_currency="USD",
            to_currency="INR",
            rate=70.0,
            date=today,
            source="test",
            created_at=stale_ts,
        )
    )
    await db.flush()

    async def _fresh(from_currency, to_currency, target_date):
        return 83.0

    monkeypatch.setattr(forex_service, "_fetch_rate_yfinance", _fresh)

    rate = await forex_service.get_exchange_rate("USD", "INR", None, db)
    assert rate == 83.0  # refreshed, not the stale 70.0


async def test_forex_serves_fresh_same_day_rate_without_fetch(db, monkeypatch):
    """A recently-cached same-day rate is served without any network call."""
    today = date.today()
    fresh_ts = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(
        ForexRate(
            from_currency="USD",
            to_currency="INR",
            rate=71.0,
            date=today,
            source="test",
            created_at=fresh_ts,
        )
    )
    await db.flush()

    async def _boom(from_currency, to_currency, target_date):
        raise AssertionError("should not refetch a fresh rate")

    monkeypatch.setattr(forex_service, "_fetch_rate_yfinance", _boom)

    rate = await forex_service.get_exchange_rate("USD", "INR", None, db)
    assert rate == 71.0
