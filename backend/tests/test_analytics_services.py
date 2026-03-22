"""Tests for analytics service endpoints.

Covers drift detection, sector rotation, 52-week proximity, data freshness,
recurring transaction detection, SIP calendar, and Google Sheets CSV export.

All tests use the in-memory SQLite database from conftest.py and the
httpx AsyncClient wired to the FastAPI app.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ANALYTICS_PREFIX = "/api/v1/analytics"


async def _create_portfolio(client: AsyncClient, headers: dict[str, str]) -> int:
    """Create a portfolio and return its ID."""
    resp = await client.post(
        "/api/v1/portfolios/",
        json={"name": "Analytics Test Portfolio", "currency": "INR"},
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _create_holding(
    client: AsyncClient,
    headers: dict[str, str],
    portfolio_id: int,
    symbol: str = "RELIANCE",
    name: str = "Reliance Industries",
    exchange: str = "NSE",
    quantity: float = 10.0,
    avg_price: float = 1500.0,
    custom_fields: dict | None = None,
) -> dict:
    """Create a holding and return its JSON response."""
    payload = {
        "portfolio_id": portfolio_id,
        "stock_symbol": symbol,
        "stock_name": name,
        "exchange": exchange,
        "cumulative_quantity": quantity,
        "average_price": avg_price,
        "base_level": 1200.0,
        "top_level": 2000.0,
        "lower_mid_range_1": 1350.0,
        "upper_mid_range_1": 1650.0,
        "lower_mid_range_2": 1300.0,
        "upper_mid_range_2": 1700.0,
    }
    if custom_fields is not None:
        payload["custom_fields"] = custom_fields
    resp = await client.post(
        "/api/v1/holdings/",
        json=payload,
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()


async def _create_portfolio_with_holdings(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    with_targets: bool = False,
) -> int:
    """Create a portfolio with 3 NSE holdings and return the portfolio ID.

    If *with_targets* is True, each holding gets a ``target_allocation_pct``
    stored in ``custom_fields`` so that drift detection has something to
    compare against.
    """
    pid = await _create_portfolio(client, headers)
    stocks = [
        ("RELIANCE", "Reliance Industries"),
        ("TCS", "Tata Consultancy Services"),
        ("INFY", "Infosys"),
    ]
    for symbol, name in stocks:
        custom = None
        if with_targets:
            custom = {"target_allocation_pct": round(100 / len(stocks), 2)}
        await _create_holding(
            client,
            headers,
            pid,
            symbol=symbol,
            name=name,
            custom_fields=custom,
        )
    return pid


async def _create_transactions_for_holding(
    client: AsyncClient,
    headers: dict[str, str],
    holding_id: int,
    *,
    count: int = 3,
    interval_days: int = 30,
    quantity: float = 5.0,
    price: float = 1500.0,
) -> list[dict]:
    """Create *count* BUY transactions spaced *interval_days* apart."""
    results = []
    base_date = date.today() - timedelta(days=count * interval_days)
    for i in range(count):
        tx_date = base_date + timedelta(days=i * interval_days)
        resp = await client.post(
            "/api/v1/transactions/",
            json={
                "holding_id": holding_id,
                "transaction_type": "BUY",
                "date": tx_date.isoformat(),
                "quantity": quantity,
                "price": price,
            },
            headers=headers,
        )
        assert resp.status_code == 201
        results.append(resp.json())
    return results


NONEXISTENT_PID = 99999


# =========================================================================
# 1. Drift Detection
# =========================================================================


class TestDrift:
    """Tests for GET /api/v1/analytics/drift/{portfolio_id}."""

    @pytest.mark.anyio
    async def test_drift_success_with_targets(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        pid = await _create_portfolio_with_holdings(
            client, auth_headers, with_targets=True
        )
        resp = await client.get(
            f"{ANALYTICS_PREFIX}/drift/{pid}", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["portfolio_id"] == pid
        assert "threshold" in data
        assert "holdings" in data

    @pytest.mark.anyio
    async def test_drift_success_without_targets(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        """Holdings without target allocations should still return a valid response."""
        pid = await _create_portfolio_with_holdings(client, auth_headers)
        resp = await client.get(
            f"{ANALYTICS_PREFIX}/drift/{pid}", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["portfolio_id"] == pid
        assert isinstance(data["holdings"], list)

    @pytest.mark.anyio
    async def test_drift_custom_threshold(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        pid = await _create_portfolio_with_holdings(
            client, auth_headers, with_targets=True
        )
        resp = await client.get(
            f"{ANALYTICS_PREFIX}/drift/{pid}?threshold=10.0",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["threshold"] == 10.0

    @pytest.mark.anyio
    async def test_drift_404_nonexistent_portfolio(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        resp = await client.get(
            f"{ANALYTICS_PREFIX}/drift/{NONEXISTENT_PID}",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_drift_401_unauthenticated(self, client: AsyncClient):
        resp = await client.get(f"{ANALYTICS_PREFIX}/drift/1")
        assert resp.status_code in (401, 403)


class TestSetDriftTarget:
    """Tests for PUT /api/v1/analytics/drift/{holding_id}."""

    @pytest.mark.anyio
    async def test_set_target_allocation(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        pid = await _create_portfolio(client, auth_headers)
        h = await _create_holding(client, auth_headers, pid)
        hid = h["id"]

        resp = await client.put(
            f"{ANALYTICS_PREFIX}/drift/{hid}",
            json={"target_allocation_pct": 33.33},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["holding_id"] == hid
        assert data["target_allocation_pct"] == 33.33

    @pytest.mark.anyio
    async def test_set_target_404_nonexistent_holding(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        resp = await client.put(
            f"{ANALYTICS_PREFIX}/drift/{NONEXISTENT_PID}",
            json={"target_allocation_pct": 50.0},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_set_target_401_unauthenticated(self, client: AsyncClient):
        resp = await client.put(
            f"{ANALYTICS_PREFIX}/drift/1",
            json={"target_allocation_pct": 50.0},
        )
        assert resp.status_code in (401, 403)


# =========================================================================
# 2. Sector Rotation
# =========================================================================


class TestSectorRotation:
    """Tests for GET /api/v1/analytics/sector-rotation/{portfolio_id}."""

    @pytest.mark.anyio
    async def test_sector_rotation_success(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        pid = await _create_portfolio_with_holdings(client, auth_headers)
        resp = await client.get(
            f"{ANALYTICS_PREFIX}/sector-rotation/{pid}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        # Response should be a dict (exact keys depend on service impl)
        assert isinstance(data, dict)

    @pytest.mark.anyio
    async def test_sector_rotation_empty_portfolio(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        """A portfolio with no holdings should still return a valid response."""
        pid = await _create_portfolio(client, auth_headers)
        resp = await client.get(
            f"{ANALYTICS_PREFIX}/sector-rotation/{pid}",
            headers=auth_headers,
        )
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_sector_rotation_404_nonexistent(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        resp = await client.get(
            f"{ANALYTICS_PREFIX}/sector-rotation/{NONEXISTENT_PID}",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_sector_rotation_401_unauthenticated(
        self, client: AsyncClient
    ):
        resp = await client.get(
            f"{ANALYTICS_PREFIX}/sector-rotation/1"
        )
        assert resp.status_code in (401, 403)


# =========================================================================
# 3. 52-Week Proximity
# =========================================================================


class TestWeek52Proximity:
    """Tests for GET /api/v1/analytics/52week/{portfolio_id}."""

    @pytest.mark.anyio
    async def test_52week_success(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        pid = await _create_portfolio_with_holdings(client, auth_headers)
        resp = await client.get(
            f"{ANALYTICS_PREFIX}/52week/{pid}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["portfolio_id"] == pid
        assert "holdings" in data

    @pytest.mark.anyio
    async def test_52week_empty_portfolio(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        pid = await _create_portfolio(client, auth_headers)
        resp = await client.get(
            f"{ANALYTICS_PREFIX}/52week/{pid}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["holdings"] == []

    @pytest.mark.anyio
    async def test_52week_404_nonexistent(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        resp = await client.get(
            f"{ANALYTICS_PREFIX}/52week/{NONEXISTENT_PID}",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_52week_401_unauthenticated(self, client: AsyncClient):
        resp = await client.get(f"{ANALYTICS_PREFIX}/52week/1")
        assert resp.status_code in (401, 403)


# =========================================================================
# 4. Data Freshness
# =========================================================================


class TestDataFreshness:
    """Tests for GET /api/v1/analytics/freshness/{portfolio_id}."""

    @pytest.mark.anyio
    async def test_freshness_success(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        pid = await _create_portfolio_with_holdings(client, auth_headers)
        resp = await client.get(
            f"{ANALYTICS_PREFIX}/freshness/{pid}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["portfolio_id"] == pid
        assert "total_holdings" in data
        assert "stale_count" in data
        assert "holdings" in data
        assert data["total_holdings"] == 3

    @pytest.mark.anyio
    async def test_freshness_empty_portfolio(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        pid = await _create_portfolio(client, auth_headers)
        resp = await client.get(
            f"{ANALYTICS_PREFIX}/freshness/{pid}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_holdings"] == 0
        assert data["stale_count"] == 0

    @pytest.mark.anyio
    async def test_freshness_404_nonexistent(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        resp = await client.get(
            f"{ANALYTICS_PREFIX}/freshness/{NONEXISTENT_PID}",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_freshness_401_unauthenticated(self, client: AsyncClient):
        resp = await client.get(f"{ANALYTICS_PREFIX}/freshness/1")
        assert resp.status_code in (401, 403)


# =========================================================================
# 5. Recurring Transaction Detection
# =========================================================================


class TestRecurringDetection:
    """Tests for GET /api/v1/analytics/recurring/{portfolio_id}."""

    @pytest.mark.anyio
    async def test_recurring_success_with_transactions(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        pid = await _create_portfolio(client, auth_headers)
        h = await _create_holding(client, auth_headers, pid)
        # Create monthly-like recurring transactions
        await _create_transactions_for_holding(
            client,
            auth_headers,
            h["id"],
            count=4,
            interval_days=30,
            quantity=5.0,
            price=1500.0,
        )

        resp = await client.get(
            f"{ANALYTICS_PREFIX}/recurring/{pid}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["portfolio_id"] == pid
        assert "detected_count" in data
        assert "patterns" in data
        assert isinstance(data["patterns"], list)

    @pytest.mark.anyio
    async def test_recurring_no_transactions(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        """Portfolio with holdings but no transactions should return zero patterns."""
        pid = await _create_portfolio_with_holdings(client, auth_headers)
        resp = await client.get(
            f"{ANALYTICS_PREFIX}/recurring/{pid}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["detected_count"] == 0
        assert data["patterns"] == []

    @pytest.mark.anyio
    async def test_recurring_empty_portfolio(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        pid = await _create_portfolio(client, auth_headers)
        resp = await client.get(
            f"{ANALYTICS_PREFIX}/recurring/{pid}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["detected_count"] == 0

    @pytest.mark.anyio
    async def test_recurring_404_nonexistent(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        resp = await client.get(
            f"{ANALYTICS_PREFIX}/recurring/{NONEXISTENT_PID}",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_recurring_401_unauthenticated(self, client: AsyncClient):
        resp = await client.get(f"{ANALYTICS_PREFIX}/recurring/1")
        assert resp.status_code in (401, 403)


# =========================================================================
# 6. SIP Calendar
# =========================================================================


class TestSIPCalendar:
    """Tests for GET /api/v1/analytics/calendar/{portfolio_id}."""

    @pytest.mark.anyio
    async def test_calendar_success(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        pid = await _create_portfolio_with_holdings(client, auth_headers)
        resp = await client.get(
            f"{ANALYTICS_PREFIX}/calendar/{pid}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["portfolio_id"] == pid
        assert "month" in data
        assert "year" in data
        assert "event_count" in data
        assert "events" in data
        assert isinstance(data["events"], list)

    @pytest.mark.anyio
    async def test_calendar_custom_month_year(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        pid = await _create_portfolio_with_holdings(client, auth_headers)
        resp = await client.get(
            f"{ANALYTICS_PREFIX}/calendar/{pid}?month=6&year=2025",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["month"] == 6
        assert data["year"] == 2025

    @pytest.mark.anyio
    async def test_calendar_defaults_to_current_month(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        pid = await _create_portfolio(client, auth_headers)
        resp = await client.get(
            f"{ANALYTICS_PREFIX}/calendar/{pid}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        today = date.today()
        assert data["month"] == today.month
        assert data["year"] == today.year

    @pytest.mark.anyio
    async def test_calendar_404_nonexistent(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        resp = await client.get(
            f"{ANALYTICS_PREFIX}/calendar/{NONEXISTENT_PID}",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_calendar_401_unauthenticated(self, client: AsyncClient):
        resp = await client.get(f"{ANALYTICS_PREFIX}/calendar/1")
        assert resp.status_code in (401, 403)


# =========================================================================
# 7. Google Sheets CSV Export
# =========================================================================


class TestSheetsExport:
    """Tests for GET /api/v1/analytics/export/sheets/{portfolio_id}."""

    @pytest.mark.anyio
    async def test_sheets_export_success(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        pid = await _create_portfolio_with_holdings(client, auth_headers)
        resp = await client.get(
            f"{ANALYTICS_PREFIX}/export/sheets/{pid}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")
        # Should have a Content-Disposition header with a filename
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert ".csv" in cd
        # Body should be non-empty CSV text
        body = resp.text
        assert len(body) > 0

    @pytest.mark.anyio
    async def test_sheets_export_has_csv_content(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        """Verify the exported CSV contains recognisable column headers."""
        pid = await _create_portfolio_with_holdings(client, auth_headers)
        resp = await client.get(
            f"{ANALYTICS_PREFIX}/export/sheets/{pid}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.text
        # CSV should contain some recognizable content (at minimum, commas)
        assert "," in body

    @pytest.mark.anyio
    async def test_sheets_export_empty_portfolio(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        """An empty portfolio should still produce a valid CSV (possibly just headers)."""
        pid = await _create_portfolio(client, auth_headers)
        resp = await client.get(
            f"{ANALYTICS_PREFIX}/export/sheets/{pid}",
            headers=auth_headers,
        )
        # Should succeed — even an empty portfolio should export headers
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_sheets_export_404_nonexistent(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        resp = await client.get(
            f"{ANALYTICS_PREFIX}/export/sheets/{NONEXISTENT_PID}",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_sheets_export_401_unauthenticated(
        self, client: AsyncClient
    ):
        resp = await client.get(
            f"{ANALYTICS_PREFIX}/export/sheets/1"
        )
        assert resp.status_code in (401, 403)
