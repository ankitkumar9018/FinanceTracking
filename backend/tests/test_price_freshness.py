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
