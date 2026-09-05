"""Regression tests for stale price/RSI/chart data.

Three defects made market data lag reality:

1. yfinance returns the CURRENT session as a row whose ``Close`` is NaN until
   it is finalised. ``fetch_historical_data`` skipped that row, so every chart
   and RSI value was exactly one trading day behind — the "data is a day old"
   symptom — even though the live quote was correct.
2. The refresh asked for a 1-day history window, which returns ZERO bars, so
   the price-history table never gained a row and portfolio charts froze.
3. The scheduler's interval trigger waited a full interval before its first
   run, so a freshly opened app showed stale values for minutes.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest
from sqlalchemy import select

from app.services import market_data_service as mds


def _frame_with_pending_row() -> pd.DataFrame:
    """Two settled sessions plus today's row with a NaN close (as yfinance does)."""
    idx = pd.to_datetime(
        [date.today() - timedelta(days=2), date.today() - timedelta(days=1), date.today()]
    )
    return pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.5],
            "High": [103.0, 104.0, 105.0],
            "Low": [99.0, 100.5, 101.0],
            "Close": [102.0, 103.0, float("nan")],  # pending session
            "Volume": [1000, 1100, float("nan")],
        },
        index=idx,
    )


@pytest.mark.asyncio
async def test_pending_session_completed_from_quote(monkeypatch):
    """The NaN-close row is filled from the live quote, not dropped."""
    monkeypatch.setattr(mds, "_fetch_history_frame", None, raising=False)

    def fake_hist(*_a, **_k):
        return _frame_with_pending_row()

    fake_ticker = type("T", (), {"history": staticmethod(fake_hist)})
    monkeypatch.setattr(mds.yf, "Ticker", lambda *_a, **_k: fake_ticker())

    quote = {
        "current_price": 104.25,
        "open": 102.5,
        "high": 105.0,
        "low": 101.0,
        "volume": 2222,
    }
    rows = await mds.fetch_historical_data("RELIANCE", "NSE", 5, quote=quote)

    assert len(rows) == 3, "the pending session must be kept, not skipped"
    latest = rows[-1]
    assert latest["date"] == date.today()
    assert latest["close"] == 104.25  # taken from the live quote
    assert latest["volume"] == 2222


@pytest.mark.asyncio
async def test_pending_session_dropped_when_quote_unusable(monkeypatch):
    """Without a usable quote the old, safe behaviour still applies."""
    def fake_hist(*_a, **_k):
        return _frame_with_pending_row()

    fake_ticker = type("T", (), {"history": staticmethod(fake_hist)})
    monkeypatch.setattr(mds.yf, "Ticker", lambda *_a, **_k: fake_ticker())

    async def no_quote(*_a, **_k):
        return {}

    monkeypatch.setattr(mds, "fetch_current_price", no_quote)
    rows = await mds.fetch_historical_data("RELIANCE", "NSE", 5)
    assert len(rows) == 2, "unusable quote → pending row skipped rather than faked"


def test_history_backfill_window_is_not_one_day():
    """days=1 returns zero bars from yfinance, so the refresh must use a real window."""
    assert mds.HISTORY_BACKFILL_DAYS >= 5


def test_scheduler_jobs_run_immediately():
    """Jobs must not wait a full interval before their first run."""
    import inspect

    from app.tasks import scheduler

    src = inspect.getsource(scheduler.start_scheduler)
    assert "next_run_time" in src


# ===========================================================================
# Wave-3: the refreshed numbers must actually reach the browser
# ===========================================================================
#
# 4. ``ConnectionManager.broadcast_price_update`` had ZERO callers: the task
#    only emitted a coarse ``prices_refreshed`` event, so the DB refreshed
#    every 5 minutes while every number on screen stayed frozen.
# 5. ``get_portfolio_summary`` reported a never-fetched price as the *purchase*
#    price, so an unpriced holding rendered as a real quote at +0.00 %.
# 6. Naive-UTC timestamps were serialised without an offset and read by the
#    browser as local time.
# 7. ``refresh_all_prices`` only ever selected ``Holding``, so
#    ``WatchlistItem.current_price`` stayed NULL and watchlist alerts — which
#    skip an item with no price — could never fire.

from datetime import datetime  # noqa: E402

from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.models.alert import Alert  # noqa: E402
from app.models.holding import Holding  # noqa: E402
from app.models.portfolio import Portfolio  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.watchlist import WatchlistItem  # noqa: E402
from app.services.portfolio_service import get_portfolio_summary  # noqa: E402
from tests.conftest import TestSessionFactory  # noqa: E402


async def _seed_user(db: AsyncSession, email: str) -> User:
    user = User(email=email, password_hash="x", display_name="Fresh")
    db.add(user)
    await db.flush()
    return user


def _fake_fetch(price: float = 250.0, rsi: float = 55.0):
    """Stand-in for ``_fetch_holding_data`` — no network, deterministic values."""

    async def _fetch(symbol: str, exchange: str) -> dict:
        return {
            "symbol": symbol,
            "exchange": exchange,
            "ok": True,
            "quote": {"current_price": price},
            "rsi": rsi,
            "ohlcv": [],
        }

    return _fetch


class _RecordingManager:
    """Captures every broadcast so tests can assert on symbols and payloads."""

    def __init__(self) -> None:
        self.price_updates: list[tuple[str, dict]] = []
        self.broadcasts: list[dict] = []

    async def broadcast_price_update(
        self, symbol: str, data: dict, exchange: str | None = None
    ) -> None:
        self.price_updates.append((symbol, data))

    async def broadcast_all(self, data: dict) -> None:
        self.broadcasts.append(data)


# ── 4. Live price updates reach subscribed clients ──────────────────────────

@pytest.mark.asyncio
async def test_refresh_returns_per_holding_updates(db: AsyncSession, monkeypatch):
    """``refresh_all_prices`` reports what it changed, not just how many."""
    user = await _seed_user(db, "updates@example.com")
    portfolio = Portfolio(user_id=user.id, name="P", currency="INR")
    db.add(portfolio)
    await db.flush()
    for symbol in ("RELIANCE", "INFY"):
        db.add(
            Holding(
                portfolio_id=portfolio.id,
                stock_symbol=symbol,
                stock_name=symbol,
                exchange="NSE",
                currency="INR",
                cumulative_quantity=10.0,
                average_price=100.0,
            )
        )
    await db.commit()

    monkeypatch.setattr(mds, "_fetch_holding_data", _fake_fetch(250.0, 61.0))
    summary = await mds.refresh_all_prices(db)

    assert summary["updated"] == 2
    assert summary["total"] == 2
    assert {u["symbol"] for u in summary["updates"]} == {"RELIANCE", "INFY"}
    payload = summary["updates"][0]
    assert set(payload) == {
        "symbol",
        "exchange",
        "current_price",
        "rsi",
        "action_needed",
        "last_price_update",
    }
    assert payload["current_price"] == 250.0
    assert payload["rsi"] == 61.0
    assert payload["exchange"] == "NSE"
    # Offset-aware so the browser cannot read it as local time.
    assert payload["last_price_update"].endswith("+00:00")


@pytest.mark.asyncio
async def test_task_broadcasts_once_per_updated_holding(db: AsyncSession, monkeypatch):
    """One ``price_update`` per refreshed symbol, plus the coarse fallback."""
    from app.tasks import fetch_prices as fp

    user = await _seed_user(db, "broadcast@example.com")
    portfolio = Portfolio(user_id=user.id, name="P", currency="INR")
    db.add(portfolio)
    await db.flush()
    for symbol in ("RELIANCE", "INFY"):
        db.add(
            Holding(
                portfolio_id=portfolio.id,
                stock_symbol=symbol,
                stock_name=symbol,
                exchange="NSE",
                currency="INR",
                cumulative_quantity=10.0,
                average_price=100.0,
            )
        )
    await db.commit()

    recorder = _RecordingManager()
    monkeypatch.setattr(fp, "manager", recorder)
    monkeypatch.setattr(fp, "async_session_factory", TestSessionFactory)
    monkeypatch.setattr(mds, "_fetch_holding_data", _fake_fetch(303.5, 42.0))

    result = await fp.fetch_prices_task()

    assert result["updated"] == 2
    assert result["broadcast"] == 2
    assert len(recorder.price_updates) == 2
    assert {sym for sym, _ in recorder.price_updates} == {"RELIANCE", "INFY"}
    for symbol, data in recorder.price_updates:
        assert data["symbol"] == symbol
        assert data["current_price"] == 303.5
        assert data["rsi"] == 42.0
        assert data["last_price_update"].endswith("+00:00")

    # The coarse fallback event is still emitted (counts only, no payloads).
    assert [b["type"] for b in recorder.broadcasts] == ["prices_refreshed"]
    assert "updates" not in recorder.broadcasts[0]["data"]


@pytest.mark.asyncio
async def test_broadcast_failure_never_breaks_the_refresh(monkeypatch):
    """A dead WebSocket must not take the price refresh down with it."""
    from app.tasks import fetch_prices as fp

    class _Exploding:
        async def broadcast_price_update(
            self, symbol: str, data: dict, exchange: str | None = None
        ) -> None:
            raise RuntimeError("socket gone")

    monkeypatch.setattr(fp, "manager", _Exploding())
    sent = await fp._broadcast_updates([{"symbol": "RELIANCE", "current_price": 1.0}])
    assert sent == 0


# ── 5. A never-fetched price is not the purchase price ──────────────────────

@pytest.mark.asyncio
async def test_summary_reports_none_for_unpriced_holding(db: AsyncSession):
    """An unpriced holding reports ``None``, not its average price at +0.00 %."""
    user = await _seed_user(db, "unpriced-summary@example.com")
    portfolio = Portfolio(user_id=user.id, name="P", currency="INR")
    db.add(portfolio)
    await db.flush()
    db.add(
        Holding(
            portfolio_id=portfolio.id,
            stock_symbol="NOPRICE",
            stock_name="NOPRICE",
            exchange="NSE",
            currency="INR",
            cumulative_quantity=10.0,
            average_price=2500.0,
        )
    )
    db.add(
        Holding(
            portfolio_id=portfolio.id,
            stock_symbol="PRICED",
            stock_name="PRICED",
            exchange="NSE",
            currency="INR",
            cumulative_quantity=10.0,
            average_price=2500.0,
            current_price=2800.0,
            last_price_update=datetime(2026, 8, 29, 10, 0, 0),  # naive UTC, as stored
        )
    )
    await db.commit()

    summary = await get_portfolio_summary(portfolio.id, db)
    rows = {r["stock_symbol"]: r for r in summary["holdings"]}

    unpriced = rows["NOPRICE"]
    assert unpriced["current_price"] is None
    assert unpriced["pnl_percent"] is None
    assert unpriced["last_price_update"] is None

    priced = rows["PRICED"]
    assert priced["current_price"] == 2800.0
    assert priced["pnl_percent"] == 12.0
    assert priced["last_price_update"] == "2026-08-29T10:00:00+00:00"

    # Totals keep the average-price fallback so the portfolio total is unchanged.
    assert summary["total_current_value"] == 10 * 2500.0 + 10 * 2800.0


@pytest.mark.asyncio
async def test_summary_endpoint_exposes_null_current_price(
    client, auth_headers: dict[str, str], db: AsyncSession
):
    """The masked price must not survive the API layer either."""
    create = await client.post(
        "/api/v1/portfolios/", json={"name": "Fresh", "currency": "INR"},
        headers=auth_headers,
    )
    pid = create.json()["id"]
    db.add(
        Holding(
            portfolio_id=pid,
            stock_symbol="NOPRICE",
            stock_name="NOPRICE",
            exchange="NSE",
            currency="INR",
            cumulative_quantity=10.0,
            average_price=2500.0,
        )
    )
    await db.commit()

    resp = await client.get(f"/api/v1/portfolios/{pid}/summary", headers=auth_headers)
    assert resp.status_code == 200
    row = resp.json()["holdings"][0]
    assert row["current_price"] is None
    assert row["pnl_percent"] is None
    # The freshness field must survive response_model filtering.
    assert "last_price_update" in row
    assert row["last_price_update"] is None


# ── 6. Offset-aware alert timestamps ────────────────────────────────────────

@pytest.mark.asyncio
async def test_alert_history_timestamp_carries_utc_offset(
    client, auth_headers: dict[str, str], db: AsyncSession
):
    """A naive ISO string is read by JS as local time — always stamp the offset."""
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    user_id = me.json()["id"]

    db.add(
        Alert(
            user_id=user_id,
            alert_type="PRICE_RANGE",
            condition={"below": 100.0},
            is_active=True,
            last_triggered=datetime(2026, 8, 29, 10, 0, 0),  # naive UTC, as stored
        )
    )
    await db.commit()

    resp = await client.get("/api/v1/alerts/history", headers=auth_headers)
    assert resp.status_code == 200
    entries = resp.json()["history"]
    assert entries, "the triggered alert should appear in the history"
    triggered_at = entries[0]["triggered_at"]
    assert triggered_at.endswith("+00:00") or triggered_at.endswith("Z")
    assert triggered_at == "2026-08-29T10:00:00+00:00"


# ── 7. Watchlist items get priced, so watchlist alerts can fire ─────────────

@pytest.mark.asyncio
async def test_watchlist_refresh_writes_current_price(db: AsyncSession, monkeypatch):
    """``WatchlistItem.current_price`` was never written by any code path."""
    user = await _seed_user(db, "watchlist-refresh@example.com")
    db.add(
        WatchlistItem(
            user_id=user.id,
            stock_symbol="INFY",
            stock_name="Infosys",
            exchange="NSE",
            lower_mid_range_1=1600.0,
            lower_mid_range_2=1500.0,
            upper_mid_range_1=1900.0,
            upper_mid_range_2=2000.0,
        )
    )
    await db.commit()

    monkeypatch.setattr(mds, "_fetch_holding_data", _fake_fetch(1450.0, 27.0))
    summary = await mds.refresh_watchlist_prices(db)
    await db.commit()

    assert summary == {
        "updated": 1,
        "failed": 0,
        "total": 1,
        "updates": summary["updates"],
    }
    assert summary["updates"][0]["symbol"] == "INFY"

    result = await db.execute(select(WatchlistItem))
    item = result.scalars().one()
    assert float(item.current_price) == 1450.0
    assert float(item.current_rsi) == 27.0
    # 1450 is at/below lower_mid_range_2 -> strong-buy zone.
    assert item.action_needed == "Y_DARK_RED"


@pytest.mark.asyncio
async def test_watchlist_refresh_fetches_each_symbol_once(
    db: AsyncSession, monkeypatch
):
    """The same symbol watched by several users costs one fetch, not N."""
    calls: list[str] = []

    async def _counting(symbol: str, exchange: str) -> dict:
        calls.append(symbol)
        return {
            "symbol": symbol,
            "exchange": exchange,
            "ok": True,
            "quote": {"current_price": 99.0},
            "rsi": None,
            "ohlcv": [],
        }

    for idx in range(2):
        user = await _seed_user(db, f"dupe{idx}@example.com")
        db.add(
            WatchlistItem(
                user_id=user.id,
                stock_symbol="INFY",
                stock_name="Infosys",
                exchange="NSE",
            )
        )
    await db.commit()

    monkeypatch.setattr(mds, "_fetch_holding_data", _counting)
    summary = await mds.refresh_watchlist_prices(db)

    assert summary["updated"] == 2
    assert calls == ["INFY"], "duplicate symbols must share a single fetch"


@pytest.mark.asyncio
async def test_task_prices_watchlist_after_holdings(db: AsyncSession, monkeypatch):
    """The scheduled task covers watchlist items too, and reports their counts."""
    from app.tasks import fetch_prices as fp

    user = await _seed_user(db, "task-watchlist@example.com")
    db.add(
        WatchlistItem(
            user_id=user.id,
            stock_symbol="TCS",
            stock_name="TCS",
            exchange="NSE",
        )
    )
    await db.commit()

    recorder = _RecordingManager()
    monkeypatch.setattr(fp, "manager", recorder)
    monkeypatch.setattr(fp, "async_session_factory", TestSessionFactory)
    monkeypatch.setattr(mds, "_fetch_holding_data", _fake_fetch(3900.0, 50.0))

    result = await fp.fetch_prices_task()

    assert result["watchlist"] == {"updated": 1, "failed": 0, "total": 1}
    assert [sym for sym, _ in recorder.price_updates] == ["TCS"]

    result_db = await db.execute(select(WatchlistItem))
    assert float(result_db.scalars().one().current_price) == 3900.0


@pytest.mark.asyncio
async def test_scheduler_jobs_are_scheduled_not_paused():
    """Every JOBS entry must be ACTIVE, and only startup jobs run immediately.

    Regression: `next_run_time=None` was passed for jobs with
    run_at_startup=False. APScheduler treats an explicit None as "add this job
    PAUSED", so the daily AI digest never fired at all — silently, with no
    error anywhere. The correct "schedule normally" value is the `undefined`
    sentinel.
    """
    from datetime import UTC, datetime

    from app.tasks import scheduler as sched
    from app.tasks.celery_app import JOBS

    sched.stop_scheduler()
    try:
        sched.start_scheduler()
        s = sched.get_scheduler()
        assert s is not None
        jobs = {j.id: j for j in s.get_jobs()}
        assert set(jobs) == {spec.id for spec in JOBS}

        now = datetime.now(UTC)
        for spec in JOBS:
            job = jobs[spec.id]
            # None here means PAUSED — the exact bug this guards.
            assert job.next_run_time is not None, f"{spec.id} was added PAUSED"
            delay = (job.next_run_time - now).total_seconds()
            if spec.run_at_startup:
                assert delay < 5, f"{spec.id} should run at startup, got {delay}s"
            else:
                # Scheduled roughly one full interval out, not immediately.
                assert delay > 60, f"{spec.id} must not fire at startup, got {delay}s"
    finally:
        sched.stop_scheduler()
