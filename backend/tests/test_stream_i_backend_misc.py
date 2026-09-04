"""Regression tests for the backend-misc defect stream.

Each class pins one confirmed defect:

1.  Logging was NEVER configured, so every ``logger.info`` — the whole audit
    trail included — was discarded.
2.  ``/docs``, ``/redoc`` and ``/openapi.json`` were swallowed by the static
    frontend middleware and answered with the SPA's index.html and a 200.
3.  ``fetch_return_series`` treated a months-long hole in ``price_history`` as
    one trading day, and every risk/optimiser number annualised it as such.
4.  ``run_backtest`` reported an all-zero, green result when the strategy's
    warm-up exceeded the available bars.
5.  The scipy-free optimiser fallback sampled ``rng.random(n)/sum``, which
    never visits the simplex corners where the optima live.
6.  Broker sync wrote derived columns and no ledger, so the first recompute
    wiped the position.
7.  The forex cache had a check-then-insert race that raised a UNIQUE
    violation under concurrent requests.
8.  Portfolio XIRR ignored dividends and booked a DRIP as a phantom outflow.
9.  The holdings refresh fetched the same symbol once per holding and issued
    one SELECT per stored OHLCV bar.
10. CAS import substituted current market value for a missing cost basis.

Run with:
    uv run pytest tests/test_stream_i_backend_misc.py -q
"""

from __future__ import annotations

import io
import itertools
import logging
from datetime import date, timedelta

import numpy as np
import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import main as app_main
from app.brokers.base import (
    BrokerAdapter,
    BrokerHolding,
    BrokerOrder,
    BrokerPosition,
)
from app.core.logging_config import (
    DEFAULT_LOG_LEVEL,
    configure_logging,
    resolve_log_level,
)
from app.ml import backtester as bt
from app.ml.portfolio_optimizer import (
    HAS_SCIPY,
    _optimize_fallback,
    _sample_weights,
    optimize_portfolio,
)
from app.ml.price_data import fetch_return_series
from app.models.dividend import Dividend
from app.models.forex_rates import ForexRate
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.price_history import PriceHistory
from app.models.transaction import Transaction
from app.models.user import User
from app.services import broker_service, forex_service
from app.services import market_data_service as mds
from app.services.cas_import_service import _map_cas_to_mf
from app.services.dividend_service import _drip_marker
from app.services.portfolio_service import calculate_cumulative_holding
from app.services.portfolio_stats_service import (
    DRIP_NOTE_PREFIX,
    build_xirr_cashflows,
)
from app.services.xirr_service import xirr
from app.utils.audit import audit_log
from app.utils.security import encrypt_value
from tests.conftest import test_engine

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _weekdays(n: int, start: date) -> list[date]:
    """``n`` consecutive weekdays starting on/after ``start``, ascending."""
    days: list[date] = []
    cursor = start
    while len(days) < n:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _weekdays_back(n: int, end: date | None = None) -> list[date]:
    """The last ``n`` weekdays ending at (or before) ``end``, ascending."""
    cursor = end or date.today()
    days: list[date] = []
    while len(days) < n:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(days))


async def _make_user(db: AsyncSession, email: str) -> User:
    user = User(email=email, password_hash="x", display_name="StreamI")
    db.add(user)
    await db.flush()
    return user


async def _make_portfolio(db: AsyncSession, user: User, name: str = "Main") -> Portfolio:
    portfolio = Portfolio(user_id=user.id, name=name, currency="INR")
    db.add(portfolio)
    await db.flush()
    return portfolio


async def _add_holding(
    db: AsyncSession,
    portfolio: Portfolio,
    symbol: str,
    exchange: str = "NSE",
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
# 1. Logging is actually configured
# ---------------------------------------------------------------------------


@pytest.fixture
def restore_logging():
    """Snapshot and restore global logging state around a test."""
    root = logging.getLogger()
    audit_logger = logging.getLogger("audit")
    saved = (list(root.handlers), root.level, audit_logger.level)
    yield
    root.handlers[:] = saved[0]
    root.setLevel(saved[1])
    audit_logger.setLevel(saved[2])


class TestLoggingConfigured:
    def test_handler_installed_with_timestamped_format(self, restore_logging):
        buf = io.StringIO()
        applied = configure_logging(level="DEBUG", stream=buf)

        assert applied == "DEBUG"
        assert logging.getLogger().level == logging.DEBUG

        logging.getLogger("app.services.demo").info("hello %d", 7)
        line = buf.getvalue().strip()

        # Before the fix nothing was configured at all: this record was dropped
        # (root at WARNING with no handlers), and the warnings that did fire
        # went through logging.lastResort as bare text.
        assert "hello 7" in line
        assert "INFO" in line
        assert "app.services.demo" in line
        # "YYYY-MM-DD HH:MM:SS <level>..." — an attributable, timestamped line.
        assert line[:4].isdigit() and line[4] == "-" and line[10] == " "

    def test_repeat_calls_do_not_duplicate_handlers(self, restore_logging):
        buf = io.StringIO()
        configure_logging(level="INFO", stream=buf)
        before = len(logging.getLogger().handlers)
        configure_logging(level="INFO")
        configure_logging(level="INFO", reinstall=True)
        assert len(logging.getLogger().handlers) == before

    def test_log_level_env_var_is_honoured(self, monkeypatch, restore_logging):
        monkeypatch.setenv("LOG_LEVEL", "warning")
        assert resolve_log_level() == "WARNING"
        assert configure_logging(stream=io.StringIO()) == "WARNING"
        assert logging.getLogger().level == logging.WARNING

    def test_unknown_log_level_falls_back(self, monkeypatch, restore_logging):
        monkeypatch.setenv("LOG_LEVEL", "chatty")
        assert resolve_log_level() == DEFAULT_LOG_LEVEL

    async def test_audit_trail_survives_a_quiet_root(
        self, db: AsyncSession, monkeypatch, restore_logging
    ):
        """A failed login must be recorded even at LOG_LEVEL=WARNING."""
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        buf = io.StringIO()
        configure_logging(stream=buf)

        await audit_log(
            db,
            user_id=42,
            action="login_failed",
            resource_type="user",
            resource_id=42,
            details="bad password",
            ip_address="203.0.113.7",
        )

        written = buf.getvalue()
        assert "[AUDIT]" in written
        assert "action=login_failed" in written
        assert "user=42" in written
        assert "ip=203.0.113.7" in written


# ---------------------------------------------------------------------------
# 2. The OpenAPI docs are not swallowed by the static frontend
# ---------------------------------------------------------------------------


class TestDocsRoutesReachFastAPI:
    def test_backend_owned_paths(self):
        assert app_main._backend_owned("/openapi.json")
        assert app_main._backend_owned("/docs")
        assert app_main._backend_owned("/redoc")
        assert app_main._backend_owned("/docs/oauth2-redirect")
        assert app_main._backend_owned("/api/v1/portfolios")
        assert app_main._backend_owned("/health")
        # Frontend routes that merely start with the same letters stay on the
        # SPA — the guard matches whole path segments, not a bare prefix.
        assert not app_main._backend_owned("/docs-and-guides")
        assert not app_main._backend_owned("/dashboard")

    async def test_openapi_json_returns_json_not_index_html(self, client):
        resp = await client.get("/openapi.json")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        body = resp.json()
        assert body["openapi"].startswith("3.")
        assert "/api/v1/portfolios/" in body["paths"]

    async def test_docs_page_is_swagger_ui(self, client):
        resp = await client.get("/docs")
        assert resp.status_code == 200
        assert "swagger-ui" in resp.text.lower()

    async def test_spa_route_still_served_when_static_present(self, client):
        """The middleware must keep doing its job for non-API paths."""
        if app_main._static_dir is None:
            pytest.skip("no built static frontend in this checkout")
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "<html" in resp.text.lower()


# ---------------------------------------------------------------------------
# 3. Return series ignores date gaps
# ---------------------------------------------------------------------------


class TestReturnSeriesGaps:
    async def test_gap_spanning_return_is_dropped(self, db: AsyncSession):
        first = _weekdays(10, date(2024, 1, 1))
        # A 134-day hole — exactly the shape an intermittent refresh leaves.
        second = _weekdays(5, first[-1] + timedelta(days=134))

        await _seed_prices(
            db, "GAPPY", "NSE", [100.0 + i for i in range(10)], first
        )
        await _seed_prices(
            db, "GAPPY", "NSE", [200.0 + i for i in range(5)], second
        )

        holdings = [await _add_holding(db, await _make_portfolio(
            db, await _make_user(db, "gap@example.com")
        ), "GAPPY")]

        series = await fetch_return_series(db, holdings, first[0])
        returns = series[("GAPPY", "NSE")]

        # 14 consecutive-row steps exist; the one crossing the hole is gone.
        assert len(returns) == 13
        # That step was a +90% move (109 → 200) that used to be annualised as
        # a single trading day (times 252). Nothing of that size survives.
        assert float(returns.abs().max()) < 0.1
        assert second[0] not in list(returns.index)
        # Both contiguous blocks are still fully represented.
        assert first[-1] in list(returns.index)
        assert second[-1] in list(returns.index)

    async def test_weekend_steps_are_kept(self, db: AsyncSession):
        """Fri→Mon is a 3-day step but a perfectly normal daily return."""
        dates = _weekdays(15, date(2024, 3, 1))
        assert any((b - a).days == 3 for a, b in itertools.pairwise(dates))

        await _seed_prices(
            db, "WKND", "NSE", [100.0 * (1.001**i) for i in range(15)], dates
        )
        holdings = [await _add_holding(db, await _make_portfolio(
            db, await _make_user(db, "wknd@example.com")
        ), "WKND")]

        series = await fetch_return_series(db, holdings, dates[0])
        assert len(series[("WKND", "NSE")]) == 14

    async def test_gap_only_series_is_omitted_entirely(self, db: AsyncSession):
        """Two rows six months apart yield no usable daily observation."""
        dates = [date(2024, 1, 2), date(2024, 7, 2)]
        await _seed_prices(db, "SPARSE", "NSE", [100.0, 250.0], dates)
        holdings = [await _add_holding(db, await _make_portfolio(
            db, await _make_user(db, "sparse@example.com")
        ), "SPARSE")]

        series = await fetch_return_series(db, holdings, dates[0])
        assert ("SPARSE", "NSE") not in series


# ---------------------------------------------------------------------------
# 4. Backtest warm-up guard
# ---------------------------------------------------------------------------


class TestBacktestWarmup:
    def test_warmup_derived_from_resolved_params(self):
        assert bt.strategy_warmup_bars("sma_crossover") == 51
        assert bt.strategy_warmup_bars("sma_crossover", {"long_window": 200}) == 201
        assert bt.strategy_warmup_bars("rsi") == 15
        assert bt.strategy_warmup_bars("bollinger") == 20
        assert bt.strategy_warmup_bars("bollinger", {"window": 60}) == 60

    async def test_too_little_history_raises_instead_of_reporting_zero(
        self, db: AsyncSession
    ):
        dates = _weekdays_back(30)
        await _seed_prices(
            db, "SHORT", "NSE", [100.0 + i for i in range(30)], dates
        )

        # Previously: every SMA was NaN, no trade fired, and the result was
        # total_return 0.00% with a green "Max Drawdown 0.00% — Low Risk" card.
        with pytest.raises(ValueError, match="warm-up"):
            await bt.run_backtest(
                symbol="SHORT",
                exchange="NSE",
                strategy_name="sma_crossover",
                strategy_params=None,
                days=365,
                db=db,
            )

    async def test_result_reports_warmup_and_bars(self, db: AsyncSession):
        dates = _weekdays_back(90)
        closes = [100.0 + 15 * np.sin(i / 6) + i * 0.2 for i in range(90)]
        await _seed_prices(db, "LONG", "NSE", closes, dates)

        result = await bt.run_backtest(
            symbol="LONG",
            exchange="NSE",
            strategy_name="sma_crossover",
            strategy_params=None,
            days=365,
            db=db,
        )

        assert result.warmup_bars_required == 51
        assert result.bars_available == 90
        assert len(result.equity_curve) == 90

    async def test_custom_window_longer_than_history_is_refused(
        self, db: AsyncSession
    ):
        dates = _weekdays_back(60)
        await _seed_prices(
            db, "CUSTOM", "NSE", [100.0 + i for i in range(60)], dates
        )

        with pytest.raises(ValueError, match="200 bars of warm-up"):
            await bt.run_backtest(
                symbol="CUSTOM",
                exchange="NSE",
                strategy_name="sma_crossover",
                strategy_params={"short_window": 20, "long_window": 199},
                days=365,
                db=db,
            )


# ---------------------------------------------------------------------------
# 5. Optimiser fallback can reach corner solutions
# ---------------------------------------------------------------------------


class TestOptimizerFallbackSampling:
    def test_samples_include_every_corner_and_sum_to_one(self):
        samples = _sample_weights(4, 500)
        assert samples.shape[1] == 4
        assert np.allclose(samples.sum(axis=1), 1.0)
        for i in range(4):
            corner = np.zeros(4)
            corner[i] = 1.0
            assert any(np.allclose(row, corner) for row in samples)

    def test_max_return_finds_the_best_asset(self):
        # 8 assets: the realistic case. The old `rng.random(n)/sum` sampler
        # concentrated near equal weight — its best draw here put only 42% on
        # the winner and captured 61% of the achievable return.
        mean_daily = np.array(
            [0.0001, 0.0009, 0.0003, 0.0002, 0.0004, 0.0005, 0.0002, 0.0003]
        )
        cov = np.diag([4e-4] * 8)

        weights = _optimize_fallback(mean_daily, cov, 8, "max_return", 2_000)

        # The max-return optimum is a corner, so it must be hit exactly.
        assert weights[1] > 0.99
        achieved = float(weights @ mean_daily)
        assert achieved >= 0.99 * float(mean_daily.max())

    def test_min_variance_finds_the_quiet_asset(self):
        mean_daily = np.array(
            [0.0002, 0.0005, 0.0004, 0.0003, 0.0002, 0.0004, 0.0003, 0.0005]
        )
        cov = np.diag([1e-8] + [9e-4] * 7)

        weights = _optimize_fallback(mean_daily, cov, 8, "min_variance", 2_000)

        assert weights[0] > 0.99
        # The old sampler's best portfolio had variance 4.5e-05 — 4500x the
        # true minimum, because it could not reach the corner.
        assert float(weights @ cov @ weights) < 1e-7

    async def test_result_flags_whether_the_answer_is_exact(self, db: AsyncSession):
        user = await _make_user(db, "opt-exact@example.com")
        portfolio = await _make_portfolio(db, user)
        await _add_holding(db, portfolio, "AAA", "NSE", 10, 100.0)
        await _add_holding(db, portfolio, "BBB", "NSE", 10, 200.0)

        dates = _weekdays_back(80)
        idx = np.arange(80)
        await _seed_prices(
            db, "AAA", "NSE", list(100 + 5 * np.sin(idx / 4) + idx * 0.3), dates
        )
        await _seed_prices(
            db, "BBB", "NSE", list(200 + 8 * np.cos(idx / 5) + idx * 0.1), dates
        )

        result, _ = await optimize_portfolio(
            portfolio_id=portfolio.id,
            user_id=user.id,
            risk_tolerance="aggressive",
            db=db,
        )

        # Without scipy the answer is a sampling approximation and must say so.
        assert result.exact is HAS_SCIPY
        assert sum(result.optimal_weights.values()) == pytest.approx(1.0, abs=1e-3)


# ---------------------------------------------------------------------------
# 6. Broker sync writes the transaction ledger
# ---------------------------------------------------------------------------


class _HoldingsAdapter(BrokerAdapter):
    """Fake adapter returning a fixed holdings list."""

    BROKER_NAME = "zerodha"

    def __init__(self, holdings: list[BrokerHolding]) -> None:
        self._holdings = holdings

    async def connect(self, api_key: str, api_secret: str, **kwargs) -> dict:
        return {"access_token": "t", "login_url": None}

    async def restore_session(
        self, api_key: str, api_secret: str, access_token: str
    ) -> bool:
        return True

    async def disconnect(self) -> None:
        return None

    async def get_holdings(self) -> list[BrokerHolding]:
        return list(self._holdings)

    async def get_positions(self) -> list[BrokerPosition]:
        return []

    async def get_orders(self, from_date=None, to_date=None) -> list[BrokerOrder]:
        return []

    async def get_historical_data(
        self, symbol, exchange, from_date, to_date, interval="day"
    ) -> list[dict]:
        return []

    def is_connected(self) -> bool:
        return True


async def _broker_connection(db: AsyncSession, user: User):
    from app.models.broker_connection import BrokerConnection

    conn = BrokerConnection(
        user_id=user.id,
        broker_name="zerodha",
        encrypted_api_key=encrypt_value("k"),
        encrypted_api_secret=encrypt_value("s"),
        access_token_encrypted=encrypt_value("tok"),
        is_active=True,
    )
    db.add(conn)
    await db.flush()
    return conn


async def _ledger(db: AsyncSession, holding_id: int) -> list[Transaction]:
    rows = await db.execute(
        select(Transaction)
        .where(Transaction.holding_id == holding_id)
        .order_by(Transaction.id)
    )
    return list(rows.scalars().all())


class TestBrokerSyncWritesLedger:
    async def test_new_position_survives_a_recompute(
        self, db: AsyncSession, monkeypatch
    ):
        user = await _make_user(db, "broker-new@example.com")
        conn = await _broker_connection(db, user)
        monkeypatch.setattr(
            broker_service,
            "get_broker",
            lambda name: _HoldingsAdapter(
                [BrokerHolding("RELIANCE", "NSE", 246.0, 2400.0, 2500.0)]
            ),
        )

        summary = await broker_service.sync_holdings(conn.id, user.id, db)
        assert summary["new_holdings"] == 1

        holding = (
            await db.execute(select(Holding).where(Holding.stock_symbol == "RELIANCE"))
        ).scalar_one()
        assert float(holding.cumulative_quantity) == 246.0
        assert float(holding.average_price) == 2400.0

        ledger = await _ledger(db, holding.id)
        assert [t.transaction_type for t in ledger] == ["BUY"]
        assert float(ledger[0].quantity) == 246.0
        assert ledger[0].source == "BROKER"

        # The actual regression: any later recompute (a dividend, an
        # AI-logged trade, a CSV import) used to wipe the position to zero
        # because the ledger was empty.
        recomputed = await calculate_cumulative_holding(holding.id, db)
        assert float(recomputed.cumulative_quantity) == 246.0
        assert float(recomputed.average_price) == 2400.0

    async def test_legacy_ledgerless_holding_is_healed(
        self, db: AsyncSession, monkeypatch
    ):
        """A position written by an older sync gets a seed BUY, not a wipe."""
        user = await _make_user(db, "broker-legacy@example.com")
        portfolio = await _make_portfolio(db, user, name="Default")
        legacy = await _add_holding(db, portfolio, "INFY", "NSE", 246.0, 1400.0)
        assert await _ledger(db, legacy.id) == []

        conn = await _broker_connection(db, user)
        monkeypatch.setattr(
            broker_service,
            "get_broker",
            lambda name: _HoldingsAdapter(
                [BrokerHolding("INFY", "NSE", 246.0, 1400.0, 1500.0)]
            ),
        )
        summary = await broker_service.sync_holdings(conn.id, user.id, db)
        assert summary["updated_holdings"] == 1

        ledger = await _ledger(db, legacy.id)
        assert len(ledger) == 1
        assert float(ledger[0].quantity) == 246.0

        recomputed = await calculate_cumulative_holding(legacy.id, db)
        assert float(recomputed.cumulative_quantity) == 246.0

    async def test_quantity_change_is_recorded_as_a_trade(
        self, db: AsyncSession, monkeypatch
    ):
        user = await _make_user(db, "broker-delta@example.com")
        portfolio = await _make_portfolio(db, user, name="Default")
        holding = await _add_holding(db, portfolio, "TCS", "NSE", 100.0, 3000.0)
        db.add(
            Transaction(
                holding_id=holding.id,
                transaction_type="BUY",
                date=date.today() - timedelta(days=30),
                quantity=100.0,
                price=3000.0,
                brokerage=0,
                source="MANUAL",
            )
        )
        await db.flush()

        conn = await _broker_connection(db, user)
        monkeypatch.setattr(
            broker_service,
            "get_broker",
            lambda name: _HoldingsAdapter(
                [BrokerHolding("TCS", "NSE", 150.0, 3200.0, 3300.0)]
            ),
        )
        await broker_service.sync_holdings(conn.id, user.id, db)

        ledger = await _ledger(db, holding.id)
        assert len(ledger) == 2
        assert ledger[1].transaction_type == "BUY"
        assert float(ledger[1].quantity) == 50.0
        assert float(ledger[1].price) == 3200.0

        await db.refresh(holding)
        assert float(holding.cumulative_quantity) == 150.0
        # Weighted average of the two lots, derived from the ledger.
        assert float(holding.average_price) == pytest.approx(
            (100 * 3000 + 50 * 3200) / 150
        )

    async def test_broker_sell_is_recorded(self, db: AsyncSession, monkeypatch):
        user = await _make_user(db, "broker-sell@example.com")
        portfolio = await _make_portfolio(db, user, name="Default")
        holding = await _add_holding(db, portfolio, "HDFC", "NSE", 80.0, 1600.0)

        conn = await _broker_connection(db, user)
        monkeypatch.setattr(
            broker_service,
            "get_broker",
            lambda name: _HoldingsAdapter(
                [BrokerHolding("HDFC", "NSE", 30.0, 1600.0, 1700.0)]
            ),
        )
        await broker_service.sync_holdings(conn.id, user.id, db)

        ledger = await _ledger(db, holding.id)
        assert [t.transaction_type for t in ledger] == ["BUY", "SELL"]
        assert float(ledger[1].quantity) == 50.0
        await db.refresh(holding)
        assert float(holding.cumulative_quantity) == 30.0


# ---------------------------------------------------------------------------
# 7. Forex cache insert race
# ---------------------------------------------------------------------------


class TestForexCacheRace:
    async def test_reuses_the_row_a_concurrent_request_inserted(
        self, db: AsyncSession
    ):
        today = date.today()
        db.add(
            ForexRate(
                from_currency="EUR",
                to_currency="INR",
                rate=90.0,
                date=today,
                source="yfinance",
            )
        )
        await db.flush()

        # We fetched 95.0 over the network while another request cached 90.0.
        rate = await forex_service._cache_rate(db, "EUR", "INR", today, 95.0)

        assert rate == 90.0
        rows = (
            await db.execute(
                select(ForexRate).where(ForexRate.from_currency == "EUR")
            )
        ).scalars().all()
        assert len(rows) == 1

    async def test_integrity_error_is_absorbed_and_session_stays_usable(
        self, db: AsyncSession, monkeypatch
    ):
        """The loser of the race must not poison the transaction."""
        today = date.today()
        db.add(
            ForexRate(
                from_currency="USD",
                to_currency="INR",
                rate=83.0,
                date=today,
                source="yfinance",
            )
        )
        await db.flush()

        real_select = forex_service._select_cached
        calls = {"n": 0}

        async def _blind_first_read(session, frm, to, when):
            calls["n"] += 1
            if calls["n"] == 1:
                return None  # the winner's row is not visible to us yet
            return await real_select(session, frm, to, when)

        monkeypatch.setattr(forex_service, "_select_cached", _blind_first_read)

        rate = await forex_service._cache_rate(db, "USD", "INR", today, 84.5)

        # The UNIQUE violation was caught at the savepoint and turned back
        # into a read instead of 500ing /forex/rate.
        assert rate == 83.0
        assert calls["n"] == 2

        # Session still healthy: an unrelated write flushes fine.
        db.add(
            ForexRate(
                from_currency="GBP",
                to_currency="INR",
                rate=105.0,
                date=today,
                source="yfinance",
            )
        )
        await db.flush()
        rows = (
            await db.execute(
                select(ForexRate).where(ForexRate.from_currency == "USD")
            )
        ).scalars().all()
        assert len(rows) == 1

    async def test_first_fetch_is_cached(self, db: AsyncSession):
        today = date.today()
        rate = await forex_service._cache_rate(db, "CHF", "INR", today, 94.25)
        assert rate == 94.25
        row = (
            await db.execute(
                select(ForexRate).where(ForexRate.from_currency == "CHF")
            )
        ).scalar_one()
        assert float(row.rate) == pytest.approx(94.25)


# ---------------------------------------------------------------------------
# 8. XIRR counts dividends and ignores DRIP round-trips
# ---------------------------------------------------------------------------


class TestXirrDividends:
    def test_drip_prefix_matches_dividend_service(self):
        # The marker is duplicated as a constant; this catches any drift.
        assert _drip_marker(7).startswith(DRIP_NOTE_PREFIX)

    async def test_cash_dividend_counts_as_money_in(self, db: AsyncSession):
        user = await _make_user(db, "xirr-div@example.com")
        portfolio = await _make_portfolio(db, user)
        holding = await _add_holding(db, portfolio, "ITC", "NSE", 100.0, 100.0)
        holding.current_price = 100.0  # flat price: all return is the dividend

        bought = date.today() - timedelta(days=730)
        db.add(
            Transaction(
                holding_id=holding.id,
                transaction_type="BUY",
                date=bought,
                quantity=100.0,
                price=100.0,
                brokerage=0,
                source="MANUAL",
            )
        )
        db.add(
            Dividend(
                holding_id=holding.id,
                ex_date=date.today() - timedelta(days=370),
                payment_date=date.today() - timedelta(days=365),
                amount_per_share=6.0,
                total_amount=600.0,
                is_reinvested=False,
            )
        )
        await db.flush()

        flows = await build_xirr_cashflows(portfolio.id, db)
        amounts = sorted(cf.amount for cf in flows.cash_flows)

        # buy -10 000, dividend +600, terminal +10 000.
        assert amounts == [-10000.0, 600.0, 10000.0]
        rate = xirr(flows.cash_flows)
        assert rate is not None and rate > 0.02, (
            "a 6% cash dividend must lift XIRR above zero; ignoring dividends "
            "reported a flat 0%"
        )

    async def test_drip_is_internal_not_a_fresh_outflow(self, db: AsyncSession):
        user = await _make_user(db, "xirr-drip@example.com")
        portfolio = await _make_portfolio(db, user)
        holding = await _add_holding(db, portfolio, "HDFCBANK", "NSE", 105.0, 100.0)
        holding.current_price = 100.0

        db.add(
            Transaction(
                holding_id=holding.id,
                transaction_type="BUY",
                date=date.today() - timedelta(days=730),
                quantity=100.0,
                price=100.0,
                brokerage=0,
                source="MANUAL",
            )
        )
        dividend = Dividend(
            holding_id=holding.id,
            ex_date=date.today() - timedelta(days=365),
            payment_date=date.today() - timedelta(days=365),
            amount_per_share=5.0,
            total_amount=500.0,
            is_reinvested=True,
            reinvest_price=100.0,
            reinvest_shares=5.0,
        )
        db.add(dividend)
        await db.flush()
        db.add(
            Transaction(
                holding_id=holding.id,
                transaction_type="BUY",
                date=date.today() - timedelta(days=365),
                quantity=5.0,
                price=100.0,
                brokerage=0,
                source="MANUAL",
                notes=_drip_marker(dividend.id),
            )
        )
        await db.flush()

        flows = await build_xirr_cashflows(portfolio.id, db)
        amounts = sorted(cf.amount for cf in flows.cash_flows)

        # Only the real purchase and the terminal value. The DRIP's -500 used
        # to be booked as fresh external money out with nothing coming in.
        assert amounts == [-10000.0, 10500.0]
        assert all(cf.amount != -500.0 for cf in flows.cash_flows)


# ---------------------------------------------------------------------------
# 9. Holdings refresh dedup + batched history upsert
# ---------------------------------------------------------------------------


def _counting_fetch(calls: list[tuple[str, str]], bars: list[dict]):
    async def _fetch(symbol: str, exchange: str) -> dict:
        calls.append((symbol, exchange))
        return {
            "symbol": symbol,
            "exchange": exchange,
            "ok": True,
            "quote": {"current_price": 2500.0},
            "rsi": 55.0,
            "ohlcv": bars,
        }

    return _fetch


class TestRefreshDeduplication:
    async def test_same_symbol_in_two_portfolios_costs_one_fetch(
        self, db: AsyncSession, monkeypatch
    ):
        user = await _make_user(db, "dedup@example.com")
        p1 = await _make_portfolio(db, user, name="One")
        p2 = await _make_portfolio(db, user, name="Two")
        await _add_holding(db, p1, "RELIANCE", "NSE", 10, 2400.0)
        await _add_holding(db, p2, "RELIANCE", "NSE", 5, 2450.0)
        await _add_holding(db, p2, "INFY", "NSE", 7, 1400.0)

        bar_date = date.today() - timedelta(days=1)
        bars = [
            {
                "date": bar_date,
                "open": 2490.0,
                "high": 2510.0,
                "low": 2480.0,
                "close": 2500.0,
                "volume": 1000,
            }
        ]
        calls: list[tuple[str, str]] = []
        monkeypatch.setattr(mds, "_fetch_holding_data", _counting_fetch(calls, bars))

        summary = await mds.refresh_all_prices(db)

        assert summary["updated"] == 3
        # One fetch per distinct (symbol, exchange), not one per holding.
        assert sorted(calls) == [("INFY", "NSE"), ("RELIANCE", "NSE")]

        rows = (
            await db.execute(
                select(PriceHistory).where(PriceHistory.stock_symbol == "RELIANCE")
            )
        ).scalars().all()
        assert len(rows) == 1

    async def test_price_history_upsert_uses_one_select(self, db: AsyncSession):
        """The per-bar SELECT (≈21 per symbol per refresh) is now a single IN."""
        dates = _weekdays_back(4)
        await _seed_prices(db, "BATCH", "NSE", [10.0], dates[:1])

        selects: list[str] = []

        def _record(conn, cursor, statement, parameters, context, executemany):
            if "price_history" in statement and statement.lstrip().upper().startswith(
                "SELECT"
            ):
                selects.append(statement)

        event.listen(test_engine.sync_engine, "before_cursor_execute", _record)
        try:
            await mds._store_price_history(
                db,
                "BATCH",
                "NSE",
                [
                    {
                        "date": d,
                        "open": 10.0 + i,
                        "high": 11.0 + i,
                        "low": 9.0 + i,
                        "close": 10.5 + i,
                        "volume": 100,
                    }
                    for i, d in enumerate(dates)
                ],
                61.0,
                date.today(),
            )
            await db.flush()
        finally:
            event.remove(test_engine.sync_engine, "before_cursor_execute", _record)

        assert len(selects) == 1, f"expected one batched SELECT, got {len(selects)}"

        rows = (
            await db.execute(
                select(PriceHistory)
                .where(PriceHistory.stock_symbol == "BATCH")
                .order_by(PriceHistory.date)
            )
        ).scalars().all()
        assert len(rows) == 4
        # The pre-existing row was updated in place, not duplicated.
        assert float(rows[0].close) == pytest.approx(10.5)
        # RSI is stamped on the latest bar only.
        assert float(rows[-1].rsi_14) == pytest.approx(61.0)
        assert rows[0].rsi_14 is None


# ---------------------------------------------------------------------------
# 10. CAS import cost basis
# ---------------------------------------------------------------------------


def _cas(valuation: dict, transactions: list[dict] | None = None) -> dict:
    return {
        "folios": [
            {
                "folio": "123456",
                "schemes": [
                    {
                        "scheme": "Axis Bluechip Fund - Direct Growth",
                        "amfi": "120503",
                        "close": 100.0,
                        "valuation": valuation,
                        "transactions": transactions or [],
                    }
                ],
            }
        ]
    }


class TestCasCostBasis:
    def test_statement_cost_is_used_when_present(self):
        rows = _map_cas_to_mf(_cas({"nav": 60.0, "value": 6000.0, "cost": 4200.0}))
        assert rows[0]["invested_amount"] == 4200.0
        assert rows[0]["invested_amount_is_estimate"] is False

    def test_missing_cost_is_replayed_from_transactions(self):
        rows = _map_cas_to_mf(
            _cas(
                {"nav": 60.0, "value": 6000.0},
                [
                    {"units": 80.0, "amount": 3200.0, "type": "PURCHASE"},
                    {"units": 40.0, "amount": 2000.0, "type": "PURCHASE_SIP"},
                    {"units": 0.0, "amount": 120.0, "type": "DIVIDEND_PAYOUT"},
                    {"units": -20.0, "amount": -1100.0, "type": "REDEMPTION"},
                ],
            )
        )

        # 5200 cost on 120 units; redeeming 20 removes 1/6 of the basis.
        assert rows[0]["invested_amount"] == pytest.approx(5200 * (100 / 120), abs=0.01)
        assert rows[0]["invested_amount_is_estimate"] is False
        # The bug: the current valuation (6000) used to be stored as cost,
        # showing exactly zero gain/loss.
        assert rows[0]["invested_amount"] != 6000.0

    def test_falls_back_and_flags_when_nothing_is_available(self):
        rows = _map_cas_to_mf(_cas({"nav": 60.0, "value": 6000.0}))
        assert rows[0]["invested_amount"] == 6000.0
        assert rows[0]["invested_amount_is_estimate"] is True

    def test_full_redemption_resets_the_basis(self):
        rows = _map_cas_to_mf(
            _cas(
                {"nav": 60.0, "value": 6000.0},
                [
                    {"units": 50.0, "amount": 2500.0, "type": "PURCHASE"},
                    {"units": -50.0, "amount": -3000.0, "type": "REDEMPTION"},
                    {"units": 100.0, "amount": 5500.0, "type": "PURCHASE"},
                ],
            )
        )
        assert rows[0]["invested_amount"] == pytest.approx(5500.0)
