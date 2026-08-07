"""Tests for the API route-layer consolidation.

Covers:
- the shared ownership helpers (``verify_portfolio_ownership`` /
  ``verify_holding_ownership`` in ``app.api.deps``) returning 404 for a
  foreign / missing portfolio via one representative route per family,
- the shared ``map_value_error`` mapper: create-validation errors on
  dividends / mutual-funds now 400 (previously miscoded as 404), while
  "not found" service errors stay 404,
- filter-param consistency: ``?portfolio_id=`` / ``?holding_id=`` filters on
  a foreign / missing resource are a 404, not a 200 with an empty list,
- the extracted portfolio stats service: /xirr and /benchmark still return
  the same response shapes,
- F&O list/create round-trip: serialisation unchanged after deduplication.

Reuses the shared conftest fixtures (``client``, ``auth_headers``, ``db``).
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.price_history import PriceHistory
from app.models.transaction import Transaction
from app.models.user import User
from app.utils.security import hash_password

SHARED_PORTFOLIO_404 = "Portfolio not found or does not belong to the current user"
SHARED_HOLDING_404 = "Holding not found or does not belong to the current user"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_other_user_portfolio_with_holding(
    db: AsyncSession,
) -> tuple[int, int, int]:
    """Create a second user with a portfolio + holding.

    Returns (user_id, portfolio_id, holding_id).
    """
    other = User(
        email="foreign-owner@example.com",
        password_hash=hash_password("SecurePass123!"),
        is_active=True,
    )
    db.add(other)
    await db.flush()
    portfolio = Portfolio(user_id=other.id, name="Foreign PF", currency="INR")
    db.add(portfolio)
    await db.flush()
    holding = Holding(
        portfolio_id=portfolio.id,
        stock_symbol="FOREIGN",
        stock_name="Foreign Stock",
        exchange="NSE",
        cumulative_quantity=5,
        average_price=100.0,
    )
    db.add(holding)
    await db.flush()
    await db.commit()
    return other.id, portfolio.id, holding.id


async def _create_portfolio(
    client: AsyncClient, headers: dict[str, str], name: str = "Own PF"
) -> int:
    resp = await client.post(
        "/api/v1/portfolios/",
        json={"name": name, "currency": "INR"},
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _create_holding(
    client: AsyncClient,
    headers: dict[str, str],
    portfolio_id: int,
    symbol: str = "RELIANCE",
    quantity: float = 10,
    avg_price: float = 100.0,
) -> int:
    resp = await client.post(
        "/api/v1/holdings/",
        json={
            "portfolio_id": portfolio_id,
            "stock_symbol": symbol,
            "stock_name": symbol,
            "exchange": "NSE",
            "cumulative_quantity": quantity,
            "average_price": avg_price,
        },
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()["id"]


# ===========================================================================
# 1. Shared ownership helper — 404 for foreign portfolio, one route per family
# ===========================================================================


async def test_portfolio_get_foreign_404_standardized_detail(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    """portfolio.py family: the 404 detail is the shared standardized text."""
    _, foreign_pid, _ = await _make_other_user_portfolio_with_holding(db)
    resp = await client.get(f"/api/v1/portfolios/{foreign_pid}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == SHARED_PORTFOLIO_404


async def test_charts_allocation_foreign_404(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    """charts.py family (previously an inline clone)."""
    _, foreign_pid, _ = await _make_other_user_portfolio_with_holding(db)
    resp = await client.get(
        f"/api/v1/charts/portfolio/allocation/{foreign_pid}", headers=auth_headers
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == SHARED_PORTFOLIO_404


async def test_tax_vorabpauschale_foreign_404(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    """tax.py family (previously an inline clone with a different text)."""
    _, foreign_pid, _ = await _make_other_user_portfolio_with_holding(db)
    resp = await client.get(
        f"/api/v1/tax/vorabpauschale/{foreign_pid}", headers=auth_headers
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == SHARED_PORTFOLIO_404


async def test_earnings_foreign_404(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    """earnings.py family."""
    _, foreign_pid, _ = await _make_other_user_portfolio_with_holding(db)
    resp = await client.get(f"/api/v1/earnings/{foreign_pid}", headers=auth_headers)
    assert resp.status_code == 404


async def test_analytics_drift_foreign_404(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    """analytics.py family."""
    _, foreign_pid, _ = await _make_other_user_portfolio_with_holding(db)
    resp = await client.get(
        f"/api/v1/analytics/drift/{foreign_pid}", headers=auth_headers
    )
    assert resp.status_code == 404


async def test_comparison_stop_loss_foreign_404(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    """comparison.py family."""
    _, foreign_pid, _ = await _make_other_user_portfolio_with_holding(db)
    resp = await client.get(
        f"/api/v1/comparison/stop-loss/{foreign_pid}", headers=auth_headers
    )
    assert resp.status_code == 404


async def test_import_export_report_foreign_404(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    """import_export.py family."""
    _, foreign_pid, _ = await _make_other_user_portfolio_with_holding(db)
    resp = await client.get(
        f"/api/v1/import-export/export/report/{foreign_pid}", headers=auth_headers
    )
    assert resp.status_code == 404


async def test_indicators_risk_foreign_404(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    """indicators.py family (hedge route previously used an inline clone)."""
    _, foreign_pid, _ = await _make_other_user_portfolio_with_holding(db)
    resp = await client.get(
        f"/api/v1/indicators/hedge/{foreign_pid}", headers=auth_headers
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == SHARED_PORTFOLIO_404


async def test_holding_get_foreign_404_standardized_detail(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    """holdings.py family: shared holding helper + standardized text."""
    _, _, foreign_hid = await _make_other_user_portfolio_with_holding(db)
    resp = await client.get(f"/api/v1/holdings/{foreign_hid}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == SHARED_HOLDING_404


async def test_tax_fund_type_foreign_holding_404(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    """tax.py fund-type route (previously an inline holding clone)."""
    _, _, foreign_hid = await _make_other_user_portfolio_with_holding(db)
    resp = await client.put(
        f"/api/v1/tax/fund-type/{foreign_hid}",
        json={"fund_type": "EQUITY_ETF"},
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == SHARED_HOLDING_404


async def test_alert_create_foreign_holding_404(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    """alerts.py create route (previously an inline holding clone)."""
    _, _, foreign_hid = await _make_other_user_portfolio_with_holding(db)
    resp = await client.post(
        "/api/v1/alerts/",
        json={
            "holding_id": foreign_hid,
            "condition": {"above": 100},
        },
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == SHARED_HOLDING_404


# ===========================================================================
# 2. Filter-param consistency: foreign/missing filter id -> 404, not 200 []
# ===========================================================================


async def test_holdings_list_foreign_portfolio_filter_404(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    _, foreign_pid, _ = await _make_other_user_portfolio_with_holding(db)
    resp = await client.get(
        f"/api/v1/holdings/?portfolio_id={foreign_pid}", headers=auth_headers
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == SHARED_PORTFOLIO_404


async def test_holdings_list_missing_portfolio_filter_404(
    client: AsyncClient, auth_headers: dict[str, str]
):
    resp = await client.get(
        "/api/v1/holdings/?portfolio_id=99999", headers=auth_headers
    )
    assert resp.status_code == 404


async def test_holdings_list_without_filter_still_200(
    client: AsyncClient, auth_headers: dict[str, str]
):
    pid = await _create_portfolio(client, auth_headers)
    await _create_holding(client, auth_headers, pid)
    resp = await client.get("/api/v1/holdings/", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_transactions_list_foreign_holding_filter_404(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    _, _, foreign_hid = await _make_other_user_portfolio_with_holding(db)
    resp = await client.get(
        f"/api/v1/transactions/?holding_id={foreign_hid}", headers=auth_headers
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == SHARED_HOLDING_404


async def test_transactions_list_own_holding_filter_200(
    client: AsyncClient, auth_headers: dict[str, str]
):
    pid = await _create_portfolio(client, auth_headers)
    hid = await _create_holding(client, auth_headers, pid)
    resp = await client.get(
        f"/api/v1/transactions/?holding_id={hid}", headers=auth_headers
    )
    assert resp.status_code == 200
    # Creating a holding records an initial BUY transaction.
    assert len(resp.json()) == 1


async def test_mutual_funds_list_foreign_portfolio_filter_404(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    _, foreign_pid, _ = await _make_other_user_portfolio_with_holding(db)
    resp = await client.get(
        f"/api/v1/mutual-funds/?portfolio_id={foreign_pid}", headers=auth_headers
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == SHARED_PORTFOLIO_404


# ===========================================================================
# 3. map_value_error: validation errors -> 400, "not found" errors -> 404
# ===========================================================================


async def test_dividend_create_validation_error_now_400(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """A service-level validation ValueError is a 400, no longer a 404."""
    with patch(
        "app.api.v1.dividends.create_dividend",
        new_callable=AsyncMock,
        side_effect=ValueError("total_amount must be positive"),
    ):
        resp = await client.post(
            "/api/v1/dividends/",
            json={
                "holding_id": 1,
                "ex_date": "2026-01-01",
                "amount_per_share": 1.0,
                "total_amount": 10.0,
            },
            headers=auth_headers,
        )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "total_amount must be positive"


async def test_dividend_create_missing_holding_still_404(
    client: AsyncClient, auth_headers: dict[str, str]
):
    resp = await client.post(
        "/api/v1/dividends/",
        json={
            "holding_id": 99999,
            "ex_date": "2026-01-01",
            "amount_per_share": 1.0,
            "total_amount": 10.0,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_mutual_fund_create_validation_error_now_400(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """A service-level validation ValueError is a 400, no longer a 404."""
    with patch(
        "app.api.v1.mutual_funds.create_mutual_fund",
        new_callable=AsyncMock,
        side_effect=ValueError("units must be positive"),
    ):
        resp = await client.post(
            "/api/v1/mutual-funds/",
            json={
                "portfolio_id": 1,
                "scheme_code": "123456",
                "scheme_name": "Test Fund",
                "units": 10.0,
                "nav": 25.0,
                "invested_amount": 250.0,
            },
            headers=auth_headers,
        )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "units must be positive"


async def test_mutual_fund_create_foreign_portfolio_still_404(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    _, foreign_pid, _ = await _make_other_user_portfolio_with_holding(db)
    resp = await client.post(
        "/api/v1/mutual-funds/",
        json={
            "portfolio_id": foreign_pid,
            "scheme_code": "123456",
            "scheme_name": "Test Fund",
            "units": 10.0,
            "nav": 25.0,
            "invested_amount": 250.0,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_goal_create_foreign_linked_portfolio_now_404(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    """The 'Linked portfolio not found...' error is a 404 under the mapper
    (previously miscoded as 400)."""
    _, foreign_pid, _ = await _make_other_user_portfolio_with_holding(db)
    resp = await client.post(
        "/api/v1/goals/",
        json={
            "name": "Borrowed goal",
            "target_amount": 100000,
            "category": "wealth",
            "linked_portfolio_id": foreign_pid,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_backtest_unknown_strategy_still_400(
    client: AsyncClient, auth_headers: dict[str, str]
):
    resp = await client.post(
        "/api/v1/backtest/",
        json={"symbol": "RELIANCE", "strategy_name": "no_such_strategy"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "Unknown strategy" in resp.json()["detail"]


# ===========================================================================
# 4. XIRR + benchmark routes: same response shapes via the stats service
# ===========================================================================


async def _seed_portfolio_with_history(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db: AsyncSession,
) -> int:
    """Portfolio + holding with a backdated BUY, current price and history."""
    pid = await _create_portfolio(client, auth_headers, name="Stats PF")
    hid = await _create_holding(
        client, auth_headers, pid, symbol="RELIANCE", quantity=10, avg_price=100.0
    )

    # Backdate the auto-created BUY and set a live price so XIRR converges.
    tx = (
        await db.execute(select(Transaction).where(Transaction.holding_id == hid))
    ).scalar_one()
    tx.date = date.today() - timedelta(days=365)
    holding = (
        await db.execute(select(Holding).where(Holding.id == hid))
    ).scalar_one()
    holding.current_price = 120.0

    # Price history inside the 90-day benchmark window, plus a decoy symbol
    # that is NOT in the portfolio (must not contribute to the series).
    for offset, close in ((10, 110.0), (5, 115.0), (1, 120.0)):
        db.add(
            PriceHistory(
                stock_symbol="RELIANCE",
                exchange="NSE",
                date=date.today() - timedelta(days=offset),
                open=close,
                high=close,
                low=close,
                close=close,
                volume=1000,
            )
        )
    db.add(
        PriceHistory(
            stock_symbol="DECOY",
            exchange="NSE",
            date=date.today() - timedelta(days=5),
            open=999.0,
            high=999.0,
            low=999.0,
            close=999.0,
            volume=1000,
        )
    )
    await db.commit()
    return pid


async def test_xirr_route_shape_unchanged(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    pid = await _seed_portfolio_with_history(client, auth_headers, db)

    resp = await client.get(f"/api/v1/portfolios/{pid}/xirr", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {
        "portfolio_id",
        "xirr",
        "xirr_decimal",
        "total_current_value",
        "num_cash_flows",
        "used_stale_prices",
        "status",
    }
    assert body["portfolio_id"] == pid
    # One BUY a year ago + terminal value today -> a real, positive XIRR.
    assert body["num_cash_flows"] == 2
    assert body["total_current_value"] == 1200.0
    assert body["used_stale_prices"] is False
    assert body["status"] == "calculated"
    assert body["xirr"] is not None and body["xirr"] > 0


async def test_xirr_route_empty_portfolio_404(
    client: AsyncClient, auth_headers: dict[str, str]
):
    pid = await _create_portfolio(client, auth_headers, name="Empty PF")
    resp = await client.get(f"/api/v1/portfolios/{pid}/xirr", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "No holdings found in this portfolio"


async def test_benchmark_route_shape_unchanged(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    pid = await _seed_portfolio_with_history(client, auth_headers, db)

    fake_comparison = SimpleNamespace(
        benchmark_name="NIFTY50",
        benchmark_symbol="^NSEI",
        portfolio_return_pct=9.09,
        benchmark_return_pct=3.0,
        alpha=6.09,
        insufficient_history=False,
        period_days=90,
        data_points=3,
    )
    with patch(
        "app.api.v1.portfolio.compare_with_benchmark",
        new_callable=AsyncMock,
        return_value=fake_comparison,
    ) as mock_cmp:
        resp = await client.get(
            f"/api/v1/portfolios/{pid}/benchmark?benchmark=NIFTY50&days=90",
            headers=auth_headers,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {
        "portfolio_id",
        "benchmark_name",
        "benchmark_symbol",
        "portfolio_return_pct",
        "benchmark_return_pct",
        "alpha",
        "insufficient_history",
        "period_days",
        "data_points",
    }
    assert body["portfolio_id"] == pid
    assert body["benchmark_name"] == "NIFTY50"

    # The stats service passed a dated series built ONLY from the portfolio's
    # (symbol, exchange) pairs — the decoy symbol must not contribute.
    series = mock_cmp.call_args.kwargs["portfolio_daily_values"]
    assert [point["value"] for point in series] == [1100.0, 1150.0, 1200.0]
    assert series == sorted(series, key=lambda p: p["date"])


async def test_benchmark_route_empty_portfolio_404(
    client: AsyncClient, auth_headers: dict[str, str]
):
    pid = await _create_portfolio(client, auth_headers, name="Empty PF 2")
    resp = await client.get(
        f"/api/v1/portfolios/{pid}/benchmark", headers=auth_headers
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "No holdings found in this portfolio"


# ===========================================================================
# 5. F&O list/create round-trip unchanged
# ===========================================================================

_FNO_KEYS = {
    "id",
    "portfolio_id",
    "symbol",
    "exchange",
    "instrument_type",
    "strike_price",
    "expiry_date",
    "lot_size",
    "quantity",
    "entry_price",
    "exit_price",
    "current_price",
    "side",
    "status",
    "notes",
    "created_at",
    "updated_at",
    "unrealized_pnl",
}


async def test_fno_create_and_list_round_trip(
    client: AsyncClient, auth_headers: dict[str, str]
):
    pid = await _create_portfolio(client, auth_headers, name="FnO PF")

    create_resp = await client.post(
        "/api/v1/fno/positions",
        json={
            "portfolio_id": pid,
            "symbol": "NIFTY",
            "exchange": "NSE",
            "instrument_type": "FUT",
            "expiry_date": (date.today() + timedelta(days=30)).isoformat(),
            "lot_size": 50,
            "quantity": 2,
            "entry_price": 22000.0,
            "side": "BUY",
            "notes": "test",
        },
        headers=auth_headers,
    )
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert set(created.keys()) == _FNO_KEYS
    assert created["portfolio_id"] == pid
    assert created["symbol"] == "NIFTY"
    assert created["strike_price"] is None
    assert created["exit_price"] is None
    assert created["current_price"] is None
    assert created["unrealized_pnl"] is None
    assert created["status"] == "OPEN"

    list_resp = await client.get(
        f"/api/v1/fno/positions/{pid}", headers=auth_headers
    )
    assert list_resp.status_code == 200
    positions = list_resp.json()
    assert len(positions) == 1
    listed = positions[0]
    assert set(listed.keys()) == _FNO_KEYS
    assert listed["id"] == created["id"]
    assert listed["entry_price"] == 22000.0
    # No current price yet -> unrealized P&L stays null in the listing too.
    assert listed["unrealized_pnl"] is None


async def test_fno_list_foreign_portfolio_404(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    _, foreign_pid, _ = await _make_other_user_portfolio_with_holding(db)
    resp = await client.get(
        f"/api/v1/fno/positions/{foreign_pid}", headers=auth_headers
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == SHARED_PORTFOLIO_404
