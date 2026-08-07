"""Wave-2 ML / broker / background-task regression tests.

Covers:

1. Portfolio optimizer keyed by (symbol, exchange) — same symbol on NSE+BSE no
   longer collides (previously the covariance matrix mismatched the weight
   vector → matmul ValueError → 500).
2. ``fetch_return_series`` — single-query, tuple-keyed return series.
3. Price predictor date cursor — strictly increasing, unique, weekend-free.
4. ``StubBroker`` consolidation — six stub adapters behave declaratively.
5. ``connect_broker`` token preservation — a step-1 (login-URL) reconnect no
   longer wipes a working stored access token.
6. Expired broker sessions surface as ValueError / is_connected=False.
7. Scheduler mode decision — APScheduler runs unless USE_CELERY is set.
8. Backtester RSI now equals ``technical_indicators.calculate_rsi``.

Run with:
    uv run pytest tests/test_wave2_ml.py -q
"""

from __future__ import annotations

import itertools
import re
from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.brokers import BROKER_REGISTRY, StubBroker, get_broker
from app.brokers.base import (
    BrokerAdapter,
    BrokerHolding,
    BrokerOrder,
    BrokerPosition,
)
from app.brokers.icici_direct import ICICIDirectBroker
from app.brokers.zerodha import ZerodhaBroker
from app.ml import common, risk_calculator
from app.ml.backtester import _compute_backtest_metrics, rsi_strategy
from app.ml.portfolio_optimizer import optimize_portfolio
from app.ml.price_data import fetch_return_series
from app.ml.price_predictor import next_trading_days
from app.ml.technical_indicators import calculate_rsi
from app.models.broker_connection import BrokerConnection
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.price_history import PriceHistory
from app.models.user import User
from app.services import broker_service
from app.utils.security import decrypt_value, encrypt_value

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _weekdays_back(n: int, end: date | None = None) -> list[date]:
    """Return the last ``n`` weekdays ending at (or before) ``end``, ascending."""
    d = end or date.today()
    days: list[date] = []
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return list(reversed(days))


async def _make_user(db: AsyncSession, email: str) -> User:
    user = User(email=email, password_hash="x", display_name="Wave2")
    db.add(user)
    await db.flush()
    return user


async def _make_portfolio(db: AsyncSession, user: User) -> Portfolio:
    portfolio = Portfolio(user_id=user.id, name="Wave2", currency="INR")
    db.add(portfolio)
    await db.flush()
    return portfolio


async def _add_holding(
    db: AsyncSession,
    portfolio: Portfolio,
    symbol: str,
    exchange: str,
    quantity: float = 10.0,
    price: float = 100.0,
) -> Holding:
    holding = Holding(
        portfolio_id=portfolio.id,
        stock_symbol=symbol,
        stock_name=symbol,
        exchange=exchange,
        currency="INR",
        cumulative_quantity=quantity,
        average_price=price,
        current_price=price,
    )
    db.add(holding)
    await db.flush()
    return holding


async def _seed_prices(
    db: AsyncSession,
    symbol: str,
    exchange: str,
    closes: list[float],
    dates: list[date],
) -> None:
    db.add_all(
        PriceHistory(
            stock_symbol=symbol,
            exchange=exchange,
            date=d,
            open=c,
            high=c * 1.01,
            low=c * 0.99,
            close=c,
            volume=1000,
        )
        for d, c in zip(dates, closes, strict=True)
    )
    await db.flush()


# ---------------------------------------------------------------------------
# 1. Optimizer — same symbol on two exchanges must not collide
# ---------------------------------------------------------------------------


class TestOptimizerTupleKeys:
    async def test_same_symbol_on_nse_and_bse_both_represented(
        self, db: AsyncSession
    ):
        user = await _make_user(db, "wave2-opt@example.com")
        portfolio = await _make_portfolio(db, user)

        await _add_holding(db, portfolio, "RELIANCE", "NSE", 10, 2500.0)
        await _add_holding(db, portfolio, "RELIANCE", "BSE", 5, 2510.0)
        await _add_holding(db, portfolio, "TCS", "NSE", 3, 3600.0)

        dates = _weekdays_back(80)
        idx = np.arange(80)
        await _seed_prices(
            db, "RELIANCE", "NSE", list(2500 + 40 * np.sin(idx / 4) + idx), dates
        )
        await _seed_prices(
            db, "RELIANCE", "BSE", list(2510 + 35 * np.cos(idx / 5) + idx * 1.2), dates
        )
        await _seed_prices(
            db, "TCS", "NSE", list(3600 + 60 * np.sin(idx / 7) - idx * 0.5), dates
        )

        # Previously: symbol-keyed dicts collided → k-by-k covariance matrix
        # vs n-length weight vector → matmul ValueError → 500.
        result, suggestions = await optimize_portfolio(
            portfolio_id=portfolio.id,
            user_id=user.id,
            risk_tolerance="moderate",
            db=db,
        )

        # Both legs represented, disambiguated; unique symbol stays plain.
        expected_names = {"RELIANCE (NSE)", "RELIANCE (BSE)", "TCS"}
        assert set(result.current_weights) == expected_names
        assert set(result.optimal_weights) == expected_names
        assert {s.symbol for s in suggestions} == expected_names

        # Weights are sane distributions.
        assert sum(result.current_weights.values()) == pytest.approx(1.0, abs=1e-3)
        assert sum(result.optimal_weights.values()) == pytest.approx(1.0, abs=1e-3)
        assert all(w >= 0 for w in result.optimal_weights.values())
        assert np.isfinite(result.expected_return)
        assert np.isfinite(result.expected_volatility)


# ---------------------------------------------------------------------------
# 2. fetch_return_series — tuple-keyed, batched
# ---------------------------------------------------------------------------


class TestFetchReturnSeries:
    async def test_tuple_keys_and_no_collision(self, db: AsyncSession):
        dates = _weekdays_back(10)
        await _seed_prices(
            db, "RELIANCE", "NSE", [100 + i for i in range(10)], dates
        )
        await _seed_prices(
            db, "RELIANCE", "BSE", [200 * (1.02**i) for i in range(10)], dates
        )
        # Only one row → not enough for returns; must be omitted.
        await _seed_prices(db, "TCS", "NSE", [3600.0], dates[:1])

        holdings = [
            SimpleNamespace(stock_symbol="RELIANCE", exchange="NSE"),
            SimpleNamespace(stock_symbol="RELIANCE", exchange="BSE"),
            SimpleNamespace(stock_symbol="TCS", exchange="NSE"),
        ]
        cutoff = dates[0]

        series = await fetch_return_series(db, holdings, cutoff)

        assert set(series) == {("RELIANCE", "NSE"), ("RELIANCE", "BSE")}
        nse = series[("RELIANCE", "NSE")]
        bse = series[("RELIANCE", "BSE")]
        assert isinstance(nse, pd.Series)
        assert len(nse) == 9 and len(bse) == 9
        # Different price paths → different return series (no collision).
        assert not np.allclose(nse.to_numpy(), bse.to_numpy())
        # First NSE return: 100 → 101.
        assert nse.iloc[0] == pytest.approx(0.01)

    async def test_empty_holdings(self, db: AsyncSession):
        assert await fetch_return_series(db, [], date.today()) == {}


# ---------------------------------------------------------------------------
# 3. Predictor dates — one cursor, weekends skipped, never duplicated
# ---------------------------------------------------------------------------


class TestPredictorDates:
    @pytest.mark.parametrize(
        "start",
        [
            date(2026, 8, 6),  # Thursday — horizon crosses one weekend
            date(2026, 8, 7),  # Friday — first prediction lands on Monday
            date(2026, 8, 8),  # Saturday
            date(2026, 8, 3),  # Monday — crosses the following weekend
        ],
    )
    def test_strictly_increasing_unique_weekday_dates(self, start: date):
        days = next_trading_days(start, 7)

        assert len(days) == 7
        assert len(set(days)) == 7, "duplicate prediction dates"
        assert all(b > a for a, b in itertools.pairwise(days))
        assert all(d.weekday() < 5 for d in days)
        assert days[0] > start

    def test_thursday_crossing_weekend(self):
        # Thu 2026-08-06 → Fri 7th, then Mon 10th (not two Mondays).
        days = next_trading_days(date(2026, 8, 6), 3)
        assert days == [date(2026, 8, 7), date(2026, 8, 10), date(2026, 8, 11)]


# ---------------------------------------------------------------------------
# 4. StubBroker consolidation
# ---------------------------------------------------------------------------

STUB_NAMES = ["groww", "angel_one", "upstox", "5paisa", "deutsche_bank", "comdirect"]


class TestStubBrokers:
    @pytest.mark.parametrize("name", STUB_NAMES)
    async def test_stub_behaviour(self, name: str):
        broker = get_broker(name)

        assert isinstance(broker, StubBroker)
        assert type(broker).is_stub is True
        assert name == broker.BROKER_NAME
        # is_connected reports False instead of raising.
        assert broker.is_connected() is False
        # restore_session default: unsupported → False.
        assert await broker.restore_session("k", "s", "tok") is False

        with pytest.raises(
            NotImplementedError, match=rf"{re.escape(name)} integration coming soon"
        ):
            await broker.connect(api_key="k", api_secret="s")
        with pytest.raises(NotImplementedError):
            await broker.get_holdings()

    def test_real_adapters_are_not_stubs(self):
        assert ZerodhaBroker.is_stub is False
        assert ICICIDirectBroker.is_stub is False
        assert BrokerAdapter.is_stub is False

    def test_registry_stub_flags(self):
        flags = {name: cls.is_stub for name, cls in BROKER_REGISTRY.items()}
        assert flags == {
            "zerodha": False,
            "icici_direct": False,
            "groww": True,
            "angel_one": True,
            "upstox": True,
            "5paisa": True,
            "deutsche_bank": True,
            "comdirect": True,
        }


# ---------------------------------------------------------------------------
# 5 + 6. Broker service — token preservation and expired-session surfacing
# ---------------------------------------------------------------------------


class _FakeAdapter(BrokerAdapter):
    """Configurable fake: step-1 connect (no token) or token-yielding connect."""

    BROKER_NAME = "zerodha"

    def __init__(
        self, connect_token: str | None = None, restore_ok: bool = True
    ) -> None:
        self._connect_token = connect_token
        self._restore_ok = restore_ok
        self._connected = False

    async def connect(self, api_key: str, api_secret: str, **kwargs) -> dict:
        return {
            "access_token": self._connect_token,
            "login_url": None if self._connect_token else "https://login",
        }

    async def restore_session(
        self, api_key: str, api_secret: str, access_token: str
    ) -> bool:
        self._connected = self._restore_ok
        return self._restore_ok

    async def disconnect(self) -> None:
        self._connected = False

    async def get_holdings(self) -> list[BrokerHolding]:
        return []

    async def get_positions(self) -> list[BrokerPosition]:
        return []

    async def get_orders(self, from_date=None, to_date=None) -> list[BrokerOrder]:
        return []

    async def get_historical_data(
        self, symbol, exchange, from_date, to_date, interval="day"
    ) -> list[dict]:
        return []

    def is_connected(self) -> bool:
        return self._connected


async def _seed_connection(
    db: AsyncSession, user: User, token: str | None = "old-token"
) -> BrokerConnection:
    conn = BrokerConnection(
        user_id=user.id,
        broker_name="zerodha",
        encrypted_api_key=encrypt_value("k"),
        encrypted_api_secret=encrypt_value("s"),
        access_token_encrypted=encrypt_value(token) if token else None,
        is_active=True,
    )
    db.add(conn)
    await db.flush()
    return conn


class TestConnectBrokerTokenPreservation:
    async def test_step1_reconnect_keeps_stored_token(
        self, db: AsyncSession, monkeypatch
    ):
        user = await _make_user(db, "wave2-token@example.com")
        conn = await _seed_connection(db, user, "old-token")

        # Step-1 connect: broker returns access_token=None (login URL only).
        monkeypatch.setattr(
            broker_service, "get_broker", lambda name: _FakeAdapter(None)
        )
        result = await broker_service.connect_broker(
            user.id, "zerodha", "k2", "s2", db
        )

        assert result.id == conn.id
        assert result.access_token_encrypted is not None
        # The working stored token must survive the login-URL round-trip.
        assert decrypt_value(result.access_token_encrypted) == "old-token"

    async def test_completed_connect_overwrites_token(
        self, db: AsyncSession, monkeypatch
    ):
        user = await _make_user(db, "wave2-token2@example.com")
        await _seed_connection(db, user, "old-token")

        monkeypatch.setattr(
            broker_service, "get_broker", lambda name: _FakeAdapter("new-token")
        )
        result = await broker_service.connect_broker(
            user.id, "zerodha", "k2", "s2", db
        )

        assert decrypt_value(result.access_token_encrypted) == "new-token"


class TestExpiredSessionSurfacing:
    async def test_sync_holdings_raises_value_error(
        self, db: AsyncSession, monkeypatch
    ):
        user = await _make_user(db, "wave2-expired@example.com")
        conn = await _seed_connection(db, user, "dead-token")

        monkeypatch.setattr(
            broker_service,
            "get_broker",
            lambda name: _FakeAdapter(restore_ok=False),
        )

        # Route maps ValueError → 400 with a clear message (not a raw 500).
        with pytest.raises(ValueError, match="session expired"):
            await broker_service.sync_holdings(conn.id, user.id, db)

    async def test_status_reports_not_connected(
        self, db: AsyncSession, monkeypatch
    ):
        user = await _make_user(db, "wave2-expired2@example.com")
        conn = await _seed_connection(db, user, "dead-token")

        monkeypatch.setattr(
            broker_service,
            "get_broker",
            lambda name: _FakeAdapter(restore_ok=False),
        )

        status = await broker_service.get_connection_status(conn.id, user.id, db)
        assert status["is_active"] is True
        assert status["is_connected"] is False


# ---------------------------------------------------------------------------
# 7. Scheduler mode decision
# ---------------------------------------------------------------------------


class TestSchedulerModeDecision:
    async def test_apscheduler_starts_when_use_celery_false_despite_redis(
        self, monkeypatch
    ):
        """A pingable Redis must NOT disable APScheduler anymore."""
        from app.tasks import celery_app as celery_module
        from app.tasks import scheduler as sched

        monkeypatch.setattr(sched.settings, "use_celery", False)
        # Old heuristic said "redis pings → celery available"; prove ignored.
        monkeypatch.setattr(celery_module, "is_celery_available", lambda: True)

        sched.stop_scheduler()
        try:
            sched.start_scheduler()
            scheduler = sched.get_scheduler()
            assert scheduler is not None
            assert scheduler.running
            assert {j.id for j in scheduler.get_jobs()} == {
                "fetch_prices_job",
                "check_alerts_job",
            }
        finally:
            sched.stop_scheduler()

    async def test_use_celery_without_celery_installed_falls_back(
        self, monkeypatch
    ):
        from app.tasks import scheduler as sched

        monkeypatch.setattr(sched.settings, "use_celery", True)
        monkeypatch.setattr(sched, "celery_app", None)  # celery not importable

        sched.stop_scheduler()
        try:
            sched.start_scheduler()
            scheduler = sched.get_scheduler()
            assert scheduler is not None
            assert scheduler.running
        finally:
            sched.stop_scheduler()

    async def test_use_celery_with_celery_skips_apscheduler(self, monkeypatch):
        from app.tasks import scheduler as sched

        monkeypatch.setattr(sched.settings, "use_celery", True)
        monkeypatch.setattr(sched, "celery_app", object())  # celery importable

        sched.stop_scheduler()
        try:
            sched.start_scheduler()
            assert sched.get_scheduler() is None
        finally:
            sched.stop_scheduler()

    def test_jobs_spec_shared_between_modes(self):
        from app.tasks.celery_app import JOBS

        assert {j.id for j in JOBS} == {"fetch_prices_job", "check_alerts_job"}
        assert {j.celery_task for j in JOBS} == {
            "app.tasks.fetch_prices.fetch_prices_celery",
            "app.tasks.check_alerts.check_alerts_celery",
        }
        for job in JOBS:
            assert job.interval_seconds() > 0


# ---------------------------------------------------------------------------
# 8. Backtester RSI parity + shared metric helpers
# ---------------------------------------------------------------------------


class TestBacktesterRsiParity:
    def test_rsi_strategy_matches_calculate_rsi(self):
        # Decline then rise: forces both oversold and overbought regimes.
        closes = np.concatenate(
            [np.linspace(200, 100, 40), np.linspace(100, 220, 40)]
        )
        df = pd.DataFrame({"close": closes})

        rsi = calculate_rsi(df["close"], period=14)
        expected = pd.Series(0, index=df.index)
        expected[rsi < 30] = 1
        expected[rsi > 70] = -1

        signals = rsi_strategy(df, buy_threshold=30, sell_threshold=70)

        assert signals.equals(expected)
        # Sanity: the fixture actually produces both signal kinds.
        assert (signals == 1).any()
        assert (signals == -1).any()


class TestCommonMetricHelpers:
    def test_sharpe_parity_with_risk_calculator_wrapper(self):
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.001, 0.01, size=252))
        assert risk_calculator.calculate_sharpe_ratio(returns) == pytest.approx(
            common.sharpe(returns, min_obs=30)
        )

    def test_constants_single_source(self):
        from app.ml import backtester, portfolio_optimizer

        assert (
            risk_calculator.TRADING_DAYS_PER_YEAR
            is common.TRADING_DAYS_PER_YEAR
        )
        assert (
            portfolio_optimizer.RISK_FREE_RATE_ANNUAL
            == common.RISK_FREE_RATE_ANNUAL
        )
        assert backtester.TRADING_DAYS_PER_YEAR == common.TRADING_DAYS_PER_YEAR

    def test_max_drawdown_counts_t0_drawdown(self):
        # Equity 100 → 90 → 95: the drawdown starts on the very first bar and
        # must be counted (the equity curve includes its starting value).
        result = _compute_backtest_metrics([], [100.0, 90.0, 95.0], days=3)
        assert result.max_drawdown == pytest.approx(-10.0)

    def test_max_drawdown_no_drawdown(self):
        max_dd, duration = common.max_drawdown_from_returns(
            pd.Series([0.01] * 50)
        )
        assert max_dd == 0.0
        assert duration == 0
