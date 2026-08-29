"""Chart & analytics correctness regressions.

Each test here pins a bug that produced *plausible-looking but wrong* numbers
on a chart — the worst kind, because nothing errors out:

1. drawdown fabricated ~-96 % cliffs on cross-exchange holidays
2. beta / alpha / information ratio were permanently ``None``
3. the correlation matrix aligned series by POSITION, not by date
4. benchmark comparison was always one trading day behind (exclusive ``end``)
5. the stock-comparison chart had the same exclusive-``end`` bug
6. indicators demanded more stored history than the refresh ever back-fills
7. the performance chart fabricated a step jump for newly added holdings
8. everything read "stale" for the whole of every weekend
9. monthly SIP projections drifted backwards off their anchor day
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.holding import Holding
from app.models.price_history import PriceHistory
from app.services import benchmark_service, comparison_service, freshness_service
from app.services import market_data_service as mds
from app.services import sip_calendar_service as sip


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_portfolio(client: AsyncClient, headers: dict[str, str]) -> int:
    resp = await client.post(
        "/api/v1/portfolios/",
        json={"name": "ChartCorrectness", "currency": "INR"},
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _add_holding(
    db: AsyncSession,
    pid: int,
    symbol: str,
    exchange: str = "NSE",
    quantity: float = 10.0,
) -> Holding:
    """Insert a holding directly.

    The create endpoint fetches a live quote; these tests are about maths, so
    they go straight to the ORM (and stay socket-free).
    """
    holding = Holding(
        portfolio_id=pid,
        stock_symbol=symbol,
        stock_name=symbol.title(),
        exchange=exchange,
        currency="INR" if exchange in ("NSE", "BSE") else "EUR",
        cumulative_quantity=quantity,
        average_price=100.0,
    )
    db.add(holding)
    await db.commit()
    return holding


def _bars(dates: list[date], closes: list[float]) -> list[dict]:
    """Build a fetch_historical_data-shaped OHLCV list."""
    return [
        {
            "date": d,
            "open": c,
            "high": c,
            "low": c,
            "close": c,
            "volume": 1000,
        }
        for d, c in zip(dates, closes, strict=True)
    ]


def _weekdays(start: date, count: int) -> list[date]:
    out: list[date] = []
    d = start
    while len(out) < count:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


# ===========================================================================
# 1. Drawdown: cross-exchange holidays must not fabricate cliffs
# ===========================================================================

async def test_drawdown_ignores_cross_exchange_holidays(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    """NSE and XETRA holidays don't line up. Summing only the rows that happen
    to exist on a date silently drops a holding, which showed up as a ~-96 %
    drawdown cliff. Prices here are FLAT, so the only honest drawdown is 0."""
    pid = await _make_portfolio(client, auth_headers)
    await _add_holding(db, pid, "RELIANCE", "NSE", quantity=100)
    await _add_holding(db, pid, "SAP", "XETRA", quantity=50)

    axis = _weekdays(date(2026, 1, 5), 30)
    # NSE trades on every date except 3 of them; XETRA trades on every date
    # except 4 different ones. Neither calendar covers the full axis.
    nse_dates = [d for i, d in enumerate(axis) if i not in (4, 11, 19)]
    xetra_dates = [d for i, d in enumerate(axis) if i not in (2, 7, 15, 23)]

    histories = {
        "RELIANCE": _bars(nse_dates, [1000.0] * len(nse_dates)),
        "SAP": _bars(xetra_dates, [200.0] * len(xetra_dates)),
    }

    async def _fake(symbol, exchange, days=30, **kw):
        return histories[symbol]

    with patch(
        "app.api.v1.analytics.fetch_historical_data",
        new_callable=AsyncMock,
        side_effect=_fake,
    ):
        resp = await client.get(
            f"/api/v1/analytics/drawdown/{pid}?days=365", headers=auth_headers
        )

    assert resp.status_code == 200
    series = resp.json()["drawdown"]
    # Every date in the union is charted, not just the fully-covered ones.
    assert len(series) == len(axis)
    worst = min(p["drawdown"] for p in series)
    # Flat prices -> zero drawdown. The old positional sum produced roughly
    # -83 % here (whole holdings vanishing on the other market's holidays).
    assert worst == pytest.approx(0.0, abs=0.01)


async def test_drawdown_reports_a_real_dip_accurately(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    """A genuine price fall is still reported — at its true magnitude."""
    pid = await _make_portfolio(client, auth_headers)
    await _add_holding(db, pid, "RELIANCE", "NSE", quantity=100)
    await _add_holding(db, pid, "SAP", "XETRA", quantity=50)

    axis = _weekdays(date(2026, 1, 5), 20)
    nse_dates = [d for i, d in enumerate(axis) if i != 6]
    xetra_dates = [d for i, d in enumerate(axis) if i != 3]

    # Peak basket value = 100*1000 + 50*200 = 110_000.
    # On axis[10] SAP halves -> 100*1000 + 50*100 = 105_000 -> -4.55 %.
    sap_closes = [100.0 if d == axis[10] else 200.0 for d in xetra_dates]
    histories = {
        "RELIANCE": _bars(nse_dates, [1000.0] * len(nse_dates)),
        "SAP": _bars(xetra_dates, sap_closes),
    }

    async def _fake(symbol, exchange, days=30, **kw):
        return histories[symbol]

    with patch(
        "app.api.v1.analytics.fetch_historical_data",
        new_callable=AsyncMock,
        side_effect=_fake,
    ):
        resp = await client.get(
            f"/api/v1/analytics/drawdown/{pid}?days=365", headers=auth_headers
        )

    series = resp.json()["drawdown"]
    worst = min(p["drawdown"] for p in series)
    assert worst == pytest.approx(-4.55, abs=0.05)


async def test_drawdown_single_holding_unaffected(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    """A one-holding portfolio must behave exactly as before the alignment fix."""
    pid = await _make_portfolio(client, auth_headers)
    await _add_holding(db, pid, "RELIANCE", "NSE", quantity=10)

    axis = _weekdays(date(2026, 1, 5), 10)
    closes = [100.0, 110.0, 120.0, 90.0, 95.0, 100.0, 105.0, 108.0, 111.0, 115.0]

    async def _fake(symbol, exchange, days=30, **kw):
        return _bars(axis, closes)

    with patch(
        "app.api.v1.analytics.fetch_historical_data",
        new_callable=AsyncMock,
        side_effect=_fake,
    ):
        resp = await client.get(
            f"/api/v1/analytics/drawdown/{pid}?days=365", headers=auth_headers
        )

    series = resp.json()["drawdown"]
    assert len(series) == len(axis)
    # Peak 120 -> trough 90 = -25 %
    assert min(p["drawdown"] for p in series) == pytest.approx(-25.0, abs=0.01)


# ===========================================================================
# 3. Correlation must align by DATE, not by list position
# ===========================================================================

# Fixed pseudo-random daily returns with essentially no lag-2 autocorrelation,
# so positional (lag-shifted) pairing and date-aligned pairing disagree loudly.
_RETURNS = [
    0.012, -0.008, 0.021, -0.015, 0.004, 0.018, -0.022, 0.009, -0.003, 0.014,
    -0.019, 0.006, 0.011, -0.007, 0.023, -0.012, 0.002, 0.016, -0.017,
]


def _price_path(start: float = 100.0) -> list[float]:
    prices = [start]
    for r in _RETURNS:
        prices.append(prices[-1] * (1 + r))
    return prices


async def test_correlation_is_date_aligned_not_positional(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    """Two symbols with IDENTICAL prices on their shared dates are perfectly
    correlated (1.0). The old code truncated both series to a common length
    from the END, pairing symbol A's day *i* with symbol B's day *i+2*, which
    collapses the measured correlation toward noise."""
    pid = await _make_portfolio(client, auth_headers)
    await _add_holding(db, pid, "RELIANCE", "NSE")
    await _add_holding(db, pid, "SAP", "XETRA")

    axis = _weekdays(date(2026, 1, 5), 20)
    prices = _price_path()

    # SAP's history starts two sessions later; on every shared date the two
    # closes are proportional, so their daily returns are identical.
    a_bars = _bars(axis, prices)
    b_bars = _bars(axis[2:], [p * 3 for p in prices[2:]])

    histories = {"RELIANCE": a_bars, "SAP": b_bars}

    async def _fake(symbol, exchange, days=90, **kw):
        return histories[symbol]

    with patch(
        "app.api.v1.analytics.fetch_historical_data",
        new_callable=AsyncMock,
        side_effect=_fake,
    ):
        resp = await client.get(
            f"/api/v1/analytics/correlation/{pid}?days=90", headers=auth_headers
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["symbols"] == ["RELIANCE", "SAP"]
    matrix = data["matrix"]

    # Hand-computed, date-aligned: identical returns on every shared date.
    a_ret = pd.Series(
        {b["date"]: b["close"] for b in a_bars}
    ).sort_index().pct_change().dropna()
    b_ret = pd.Series(
        {b["date"]: b["close"] for b in b_bars}
    ).sort_index().pct_change().dropna()
    aligned = pd.DataFrame({"a": a_ret, "b": b_ret}).dropna()
    expected = float(aligned["a"].corr(aligned["b"]))
    assert expected == pytest.approx(1.0, abs=1e-9)
    assert matrix[0][1] == pytest.approx(round(expected, 3), abs=1e-9)

    # And it is emphatically NOT the positional value the old code produced.
    n = min(len(a_ret), len(b_ret))
    positional = float(
        pd.Series(a_ret.to_numpy()[:n]).corr(pd.Series(b_ret.to_numpy()[:n]))
    )
    assert abs(positional) < 0.5
    assert matrix[0][1] != pytest.approx(round(positional, 3), abs=1e-3)

    # Diagonal and symmetry sanity.
    assert matrix[0][0] == pytest.approx(1.0)
    assert matrix[1][1] == pytest.approx(1.0)
    assert matrix[0][1] == pytest.approx(matrix[1][0])


# ===========================================================================
# 4. Benchmark comparison must include the latest session
# ===========================================================================

def _recording_ticker(recorded: dict, dates: list[date], closes: list[float]):
    df = pd.DataFrame(
        {"Close": closes}, index=pd.to_datetime([d.isoformat() for d in dates])
    )

    class _FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, start=None, end=None):
            recorded["start"] = start
            recorded["end"] = end
            # yfinance's `end` is EXCLUSIVE — model that faithfully.
            cutoff = date.fromisoformat(end)
            mask = [d < cutoff for d in dates]
            return df[mask]

    return _FakeTicker


async def test_benchmark_window_end_is_padded_to_include_today(monkeypatch):
    """`end` is exclusive in yfinance, so passing today dropped today's bar —
    and the clipped benchmark window then dropped today's portfolio value too."""
    today = date.today()
    dates = [today - timedelta(days=i) for i in range(9, -1, -1)]  # includes today
    closes = [100.0 + i for i in range(len(dates))]
    recorded: dict = {}
    monkeypatch.setattr(
        benchmark_service.yf, "Ticker", _recording_ticker(recorded, dates, closes)
    )

    pf = [{"date": d.isoformat(), "value": 1000.0 + 10 * i} for i, d in enumerate(dates)]
    result = await benchmark_service.compare_with_benchmark(
        pf, benchmark_name="NIFTY50", days=30
    )

    assert result is not None
    # The requested end must be strictly after today.
    assert date.fromisoformat(recorded["end"]) == today + timedelta(days=1)
    # ...so today's session survives into the chart.
    assert result.data_points[-1]["date"] == today.isoformat()
    assert result.data_points[-1]["portfolio_value"] is not None
    assert result.insufficient_history is False


# ===========================================================================
# 5. Stock comparison delegates to the shared fetcher (padded + repaired bar)
# ===========================================================================

async def test_compare_stocks_history_includes_latest_session(monkeypatch):
    """History now comes from market_data_service.fetch_historical_data, which
    is period-based (no exclusive-`end` clipping) and repairs the pending
    session's bar instead of dropping it."""
    today = date.today()
    bars = [
        {"date": today - timedelta(days=2), "open": 1.0, "high": 1.0,
         "low": 1.0, "close": 100.0, "volume": 10},
        {"date": today - timedelta(days=1), "open": 1.0, "high": 1.0,
         "low": 1.0, "close": 101.0, "volume": 10},
        {"date": today, "open": 1.0, "high": 1.0,
         "low": 1.0, "close": 102.0, "volume": 10},
    ]
    seen: dict = {}

    async def _fake_hist(symbol, exchange="NSE", days=30, quote=None):
        seen["args"] = (symbol, exchange, days)
        seen["quote"] = quote
        return bars

    monkeypatch.setattr(
        comparison_service, "_sync_fetch_stock_info",
        lambda yf_symbol: {
            "currentPrice": 102.0, "previousClose": 101.0, "shortName": "Acme",
        },
    )
    monkeypatch.setattr(mds, "fetch_historical_data", _fake_hist)

    result = await comparison_service.compare_stocks(["TCS"], ["NSE"], days=30)

    assert seen["args"] == ("TCS", "NSE", 30)
    # The live quote is handed through so the shared fetcher can repair the
    # pending bar without a second round-trip.
    assert seen["quote"]["current_price"] == 102.0
    history = result.price_history["TCS"]
    assert [h["date"] for h in history][-1] == today.isoformat()
    assert history[-1]["close"] == 102.0
    assert result.stocks[0].day_change_pct == pytest.approx(0.99, abs=0.01)


async def test_compare_stocks_degrades_when_history_fetch_fails(monkeypatch):
    async def _boom(*a, **kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(
        comparison_service, "_sync_fetch_stock_info",
        lambda yf_symbol: {"currentPrice": 10.0, "previousClose": 10.0},
    )
    monkeypatch.setattr(mds, "fetch_historical_data", _boom)

    result = await comparison_service.compare_stocks(["TCS"], ["NSE"], days=30)
    assert result.price_history["TCS"] == []
    assert result.stocks[0].current_price == 10.0


# ===========================================================================
# 7. Performance chart: a later-listed holding must not fabricate a jump
# ===========================================================================

async def test_performance_series_has_no_fabricated_jump(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    """Holding B's price history starts mid-window. Forward-filling only after
    a symbol's first bar made B contribute 0 until then, so the chart showed a
    fabricated +500 % day. The basket is constant, so the series must be flat."""
    pid = await _make_portfolio(client, auth_headers)
    await _add_holding(db, pid, "AAA", "NSE", quantity=10)
    await _add_holding(db, pid, "BBB", "NSE", quantity=10)

    today = date.today()
    for i in range(20, 0, -1):
        db.add(
            PriceHistory(
                stock_symbol="AAA", exchange="NSE", date=today - timedelta(days=i),
                open=100.0, high=100.0, low=100.0, close=100.0, volume=1,
            )
        )
    for i in range(3, 0, -1):  # BBB only priced for the last 3 days
        db.add(
            PriceHistory(
                stock_symbol="BBB", exchange="NSE", date=today - timedelta(days=i),
                open=500.0, high=500.0, low=500.0, close=500.0, volume=1,
            )
        )
    await db.commit()

    resp = await client.get(
        f"/api/v1/charts/portfolio/performance/{pid}?days=30", headers=auth_headers
    )
    assert resp.status_code == 200
    series = resp.json()["data"]
    assert len(series) == 20

    values = [p["total_value"] for p in series]
    assert all(v > 0 for v in values)
    # Both holdings are valued on every date -> perfectly flat, no step.
    assert min(values) == pytest.approx(max(values))
    # Explicitly: the day BBB's first bar lands is not a jump.
    ratios = [values[i] / values[i - 1] for i in range(1, len(values))]
    assert max(ratios) < 1.01


# ===========================================================================
# 8. Freshness must be weekend-aware
# ===========================================================================

FRIDAY_CLOSE_UTC = datetime(2026, 8, 28, 22, 50, tzinfo=UTC)  # Fri 2026-08-28


@pytest.mark.parametrize(
    "now_utc, label",
    [
        (datetime(2026, 8, 29, 1, 26, tzinfo=UTC), "Saturday"),
        (datetime(2026, 8, 30, 1, 26, tzinfo=UTC), "Sunday"),
        (datetime(2026, 8, 30, 20, 0, tzinfo=UTC), "Sunday evening"),
        (datetime(2026, 8, 31, 1, 26, tzinfo=UTC), "Monday pre-open"),
    ],
)
async def test_friday_close_is_not_stale_over_the_weekend(now_utc, label):
    """Friday's close is the newest NSE data that exists until Monday's open,
    so a flat 24-hour age rule reported every holding stale all weekend."""
    assert (
        freshness_service._is_stale(FRIDAY_CLOSE_UTC, "NSE", now_utc) is False
    ), label


async def test_xetra_friday_close_is_not_stale_on_sunday():
    friday_evening = datetime(2026, 8, 28, 16, 30, tzinfo=UTC)  # 18:30 CET
    now = datetime(2026, 8, 30, 1, 26, tzinfo=UTC)
    assert freshness_service._is_stale(friday_evening, "XETRA", now) is False


async def test_genuinely_old_data_is_still_stale():
    """A price from Wednesday is stale once Friday's session has closed."""
    wednesday = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    friday_evening = datetime(2026, 8, 28, 20, 0, tzinfo=UTC)
    assert freshness_service._is_stale(wednesday, "NSE", friday_evening) is True


async def test_market_hours_rule_unchanged():
    """Inside market hours the 30-minute rule still applies."""
    # Mon 2026-08-31 05:00 UTC = 10:30 IST (NSE open).
    now = datetime(2026, 8, 31, 5, 0, tzinfo=UTC)
    assert freshness_service._is_market_hours("NSE", now) is True
    fresh = now - timedelta(minutes=10)
    stale = now - timedelta(minutes=45)
    assert freshness_service._is_stale(fresh, "NSE", now) is False
    assert freshness_service._is_stale(stale, "NSE", now) is True


async def test_missing_timestamp_is_stale():
    now = datetime(2026, 8, 30, 1, 26, tzinfo=UTC)
    assert freshness_service._is_stale(None, "NSE", now) is True


async def test_last_session_close_skips_the_weekend():
    sunday = datetime(2026, 8, 30, 1, 26, tzinfo=UTC)
    close = freshness_service.last_session_close("NSE", sunday)
    # Friday 2026-08-28 15:30 IST == 10:00 UTC
    assert close == datetime(2026, 8, 28, 10, 0, tzinfo=UTC)


# ===========================================================================
# 9. Monthly SIP projections must keep their anchor day-of-month
# ===========================================================================

def test_add_months_preserves_and_clamps_the_anchor_day():
    anchor = date(2026, 1, 31)
    assert sip.add_months(anchor, 1) == date(2026, 2, 28)  # clamped
    # Measured from the ORIGINAL anchor, so the clamp doesn't stick.
    assert sip.add_months(anchor, 2) == date(2026, 3, 31)
    assert sip.add_months(date(2026, 1, 15), 12) == date(2027, 1, 15)


@pytest.mark.parametrize(
    "month, year",
    [(3, 2026), (6, 2026), (9, 2026), (12, 2026), (1, 2027)],
)
def test_monthly_sip_projection_keeps_anchor_day(month, year):
    """Stepping by a flat 30 days drifted a 15th-of-the-month SIP to the 16th,
    then the 14th, 12th, 11th... over the course of a year."""
    from calendar import monthrange

    anchor = date(2026, 1, 15)
    occurrences = sip._project_occurrences(
        anchor=anchor,
        month_start=date(year, month, 1),
        month_end=date(year, month, monthrange(year, month)[1]),
        step_months=1,
        interval_days=30,
    )
    assert occurrences == [date(year, month, 15)]


def test_day_based_cadences_still_step_by_interval():
    """Weekly / ad-hoc SIPs really are day-based — don't convert those."""
    occurrences = sip._project_occurrences(
        anchor=date(2026, 3, 2),
        month_start=date(2026, 3, 1),
        month_end=date(2026, 3, 31),
        step_months=None,
        interval_days=7,
    )
    assert occurrences == [
        date(2026, 3, 2), date(2026, 3, 9), date(2026, 3, 16),
        date(2026, 3, 23), date(2026, 3, 30),
    ]


async def test_calendar_events_project_monthly_sip_on_anchor_day(
    db: AsyncSession, monkeypatch
):
    """End-to-end through get_calendar_events: a monthly SIP anchored on the
    15th lands on the 15th eleven months later, not the 11th."""
    async def _fake_recurring(portfolio_id, session):
        return [
            {
                "stock_symbol": "HDFCBANK",
                "stock_name": "HDFC Bank",
                "exchange": "NSE",
                "frequency": "monthly",
                "avg_interval_days": 30.4,
                "avg_amount": 5000.0,
                "avg_quantity": 3.0,
                "next_expected_date": "2026-01-15",
            }
        ]

    monkeypatch.setattr(sip, "detect_recurring", _fake_recurring)

    events = await sip.get_calendar_events(
        user_id=1, portfolio_id=1, month=12, year=2026, db=db
    )
    sip_events = [e for e in events if e["type"] == "SIP"]
    assert [e["date"] for e in sip_events] == ["2026-12-15"]


# ===========================================================================
# 2. Benchmark returns fall back to a live fetch when the DB has no index rows
# ===========================================================================

@pytest.mark.live_fallback
async def test_benchmark_returns_fall_back_to_live_fetch(db: AsyncSession, monkeypatch):
    """PriceHistory is only ever written for HOLDINGS, so `^NSEI` rows never
    exist and beta / alpha / information ratio were permanently None."""
    from app.ml import risk_calculator

    cutoff = date.today() - timedelta(days=380)
    dates = _weekdays(cutoff + timedelta(days=5), 120)
    prices = [100.0 * (1.001 ** i) for i in range(len(dates))]
    calls: list[tuple] = []

    async def _fake_hist(symbol, exchange="NSE", days=30, quote=None):
        calls.append((symbol, exchange, days))
        return _bars(dates, prices)

    monkeypatch.setattr(mds, "fetch_historical_data", _fake_hist)

    series = await risk_calculator._fetch_benchmark_returns(db, "^NSEI", cutoff)

    assert calls, "no live fallback was attempted"
    # Index tickers take no exchange suffix.
    assert calls[0][0] == "^NSEI"
    assert calls[0][1] == ""
    assert len(series) == len(dates) - 1
    assert series.index[0] == dates[1]


async def test_benchmark_live_fallback_degrades_without_raising(
    db: AsyncSession, monkeypatch
):
    from app.ml import risk_calculator

    async def _boom(*a, **kw):
        raise RuntimeError("provider down")

    monkeypatch.setattr(mds, "fetch_historical_data", _boom)
    series = await risk_calculator._fetch_benchmark_returns(
        db, "^NSEI", date.today() - timedelta(days=380)
    )
    assert len(series) == 0


async def test_benchmark_prefers_stored_rows_over_a_live_fetch(
    db: AsyncSession, monkeypatch
):
    """When the DB *does* hold enough benchmark rows, no network call is made."""
    from app.ml import risk_calculator

    cutoff = date.today() - timedelta(days=380)
    for i, d in enumerate(_weekdays(cutoff + timedelta(days=5), 60)):
        db.add(
            PriceHistory(
                stock_symbol="^NSEI", exchange="INDEX", date=d,
                open=100.0 + i, high=100.0 + i, low=100.0 + i,
                close=100.0 + i, volume=0,
            )
        )
    await db.commit()

    called = False

    async def _fake_hist(*a, **kw):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(mds, "fetch_historical_data", _fake_hist)
    series = await risk_calculator._fetch_benchmark_returns(db, "^NSEI", cutoff)

    assert called is False
    assert len(series) == 59


# ===========================================================================
# 6. Indicators fall back to a live fetch when stored history is too thin
# ===========================================================================

@pytest.mark.live_fallback
async def test_indicators_fall_back_to_live_history(db: AsyncSession, monkeypatch):
    """The refresh only back-fills ~24 trading bars, so the default
    ``days=90`` request returned "Insufficient price history" for weeks."""
    from app.ml import technical_indicators

    today = date.today()
    for i in range(23, 0, -1):  # 23 stored bars — below the 30-bar floor
        db.add(
            PriceHistory(
                stock_symbol="RELIANCE", exchange="NSE",
                date=today - timedelta(days=i),
                open=100.0, high=101.0, low=99.0, close=100.0 + i, volume=10,
            )
        )
    await db.commit()

    dates = _weekdays(today - timedelta(days=200), 150)
    prices = [100.0 + (i % 17) for i in range(len(dates))]
    seen: dict = {}

    async def _fake_hist(symbol, exchange="NSE", days=30, quote=None):
        seen["days"] = days
        return _bars(dates, prices)

    monkeypatch.setattr(mds, "fetch_historical_data", _fake_hist)

    result = await technical_indicators.get_all_indicators(
        "RELIANCE", "NSE", db, days=90
    )

    assert "error" not in result
    assert len(result["dates"]) == 90
    # Enough warm-up was requested for sma_50 to actually resolve.
    assert seen["days"] >= 150
    assert result["sma"]["sma_50"][-1] is not None
    assert result["rsi"][-1] is not None


async def test_indicators_still_report_insufficient_when_live_fetch_fails(
    db: AsyncSession, monkeypatch
):
    from app.ml import technical_indicators

    async def _boom(*a, **kw):
        raise RuntimeError("provider down")

    monkeypatch.setattr(mds, "fetch_historical_data", _boom)
    result = await technical_indicators.get_all_indicators(
        "NOTHING", "NSE", db, days=90
    )
    assert result["error"] == "Insufficient price history"
    assert result["data_points"] == 0


async def test_indicators_prefer_stored_history_when_sufficient(
    db: AsyncSession, monkeypatch
):
    """Enough stored bars -> no live fetch."""
    from app.ml import technical_indicators

    today = date.today()
    for i, d in enumerate(_weekdays(today - timedelta(days=120), 80)):
        db.add(
            PriceHistory(
                stock_symbol="TCS", exchange="NSE", date=d,
                open=100.0, high=101.0, low=99.0,
                close=100.0 + (i % 11), volume=10,
            )
        )
    await db.commit()

    called = False

    async def _fake_hist(*a, **kw):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(mds, "fetch_historical_data", _fake_hist)
    result = await technical_indicators.get_all_indicators("TCS", "NSE", db, days=90)

    assert called is False
    assert "error" not in result
