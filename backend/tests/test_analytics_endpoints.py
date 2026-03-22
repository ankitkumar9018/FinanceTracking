"""Tests for analytics correlation, monthly-returns, and drawdown endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Helper — create portfolio with a holding
# ---------------------------------------------------------------------------

async def _setup(client: AsyncClient, headers: dict[str, str]) -> int:
    resp = await client.post(
        "/api/v1/portfolios/",
        json={"name": "Test", "currency": "INR"},
        headers=headers,
    )
    assert resp.status_code == 201
    pid = resp.json()["id"]
    await client.post(
        "/api/v1/holdings/",
        json={
            "portfolio_id": pid,
            "stock_symbol": "RELIANCE",
            "exchange": "NSE",
            "quantity": 10,
            "avg_price": 2500.0,
            "base_level": 2000.0,
            "top_level": 3000.0,
            "lower_mid_range_1": 2200.0,
            "upper_mid_range_1": 2800.0,
            "lower_mid_range_2": 2100.0,
            "upper_mid_range_2": 2900.0,
        },
        headers=headers,
    )
    return pid


async def _setup_multi(client: AsyncClient, headers: dict[str, str]) -> int:
    """Create a portfolio with two holdings (needed for correlation)."""
    resp = await client.post(
        "/api/v1/portfolios/",
        json={"name": "MultiHolding", "currency": "INR"},
        headers=headers,
    )
    assert resp.status_code == 201
    pid = resp.json()["id"]
    for sym in ("RELIANCE", "TCS"):
        await client.post(
            "/api/v1/holdings/",
            json={
                "portfolio_id": pid,
                "stock_symbol": sym,
                "exchange": "NSE",
                "quantity": 10,
                "avg_price": 2500.0,
                "base_level": 2000.0,
                "top_level": 3000.0,
                "lower_mid_range_1": 2200.0,
                "upper_mid_range_1": 2800.0,
                "lower_mid_range_2": 2100.0,
                "upper_mid_range_2": 2900.0,
            },
            headers=headers,
        )
    return pid


def _fake_history(n: int = 100) -> list[dict]:
    """Generate fake price history for mocking."""
    import random
    from datetime import date, timedelta

    base = date.today() - timedelta(days=n)
    price = 2500.0
    history = []
    for i in range(n):
        price += random.uniform(-20, 25)
        history.append({
            "date": (base + timedelta(days=i)).isoformat(),
            "open": round(price - 5, 2),
            "high": round(price + 10, 2),
            "low": round(price - 10, 2),
            "close": round(price, 2),
            "volume": 100000,
        })
    return history


# ===========================================================================
# Correlation endpoint
# ===========================================================================


@pytest.mark.asyncio
async def test_correlation_success(client: AsyncClient, auth_headers: dict[str, str]):
    """Correlation with 2+ holdings returns a matrix."""
    pid = await _setup_multi(client, auth_headers)

    with patch(
        "app.api.v1.analytics.fetch_historical_data",
        new_callable=AsyncMock,
        side_effect=lambda *a, **kw: _fake_history(100),
    ):
        resp = await client.get(
            f"/api/v1/analytics/correlation/{pid}?days=90",
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "symbols" in data
    assert "matrix" in data


@pytest.mark.asyncio
async def test_correlation_empty_portfolio(client: AsyncClient, auth_headers: dict[str, str]):
    """Correlation on empty portfolio returns empty result."""
    resp = await client.post(
        "/api/v1/portfolios/",
        json={"name": "Empty", "currency": "INR"},
        headers=auth_headers,
    )
    pid = resp.json()["id"]

    resp = await client.get(
        f"/api/v1/analytics/correlation/{pid}?days=90",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbols"] == []
    assert data["matrix"] == []


@pytest.mark.asyncio
async def test_correlation_not_found(client: AsyncClient, auth_headers: dict[str, str]):
    """Non-existent portfolio returns 404."""
    resp = await client.get(
        "/api/v1/analytics/correlation/99999?days=90",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_correlation_unauthenticated(client: AsyncClient):
    """Missing auth returns 401."""
    resp = await client.get("/api/v1/analytics/correlation/1?days=90")
    assert resp.status_code == 401


# ===========================================================================
# Monthly returns endpoint
# ===========================================================================


@pytest.mark.asyncio
async def test_monthly_returns_success(client: AsyncClient, auth_headers: dict[str, str]):
    """Monthly returns with holdings returns data."""
    pid = await _setup(client, auth_headers)

    with patch(
        "app.api.v1.analytics.fetch_historical_data",
        new_callable=AsyncMock,
        return_value=_fake_history(400),
    ):
        resp = await client.get(
            f"/api/v1/analytics/monthly-returns/{pid}",
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "returns" in data


@pytest.mark.asyncio
async def test_monthly_returns_empty_portfolio(client: AsyncClient, auth_headers: dict[str, str]):
    """Monthly returns on empty portfolio returns empty list."""
    resp = await client.post(
        "/api/v1/portfolios/",
        json={"name": "Empty", "currency": "INR"},
        headers=auth_headers,
    )
    pid = resp.json()["id"]

    resp = await client.get(
        f"/api/v1/analytics/monthly-returns/{pid}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["returns"] == []


@pytest.mark.asyncio
async def test_monthly_returns_not_found(client: AsyncClient, auth_headers: dict[str, str]):
    resp = await client.get(
        "/api/v1/analytics/monthly-returns/99999",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_monthly_returns_unauthenticated(client: AsyncClient):
    resp = await client.get("/api/v1/analytics/monthly-returns/1")
    assert resp.status_code == 401


# ===========================================================================
# Drawdown endpoint
# ===========================================================================


@pytest.mark.asyncio
async def test_drawdown_success(client: AsyncClient, auth_headers: dict[str, str]):
    """Drawdown with holdings returns series data."""
    pid = await _setup(client, auth_headers)

    with patch(
        "app.api.v1.analytics.fetch_historical_data",
        new_callable=AsyncMock,
        return_value=_fake_history(365),
    ):
        resp = await client.get(
            f"/api/v1/analytics/drawdown/{pid}?days=365",
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "drawdown" in data
    assert isinstance(data["drawdown"], list)
    # Each entry should have date and drawdown keys
    if data["drawdown"]:
        entry = data["drawdown"][0]
        assert "date" in entry
        assert "drawdown" in entry
        # Drawdown should be <= 0
        for entry in data["drawdown"]:
            assert entry["drawdown"] <= 0.0


@pytest.mark.asyncio
async def test_drawdown_empty_portfolio(client: AsyncClient, auth_headers: dict[str, str]):
    resp = await client.post(
        "/api/v1/portfolios/",
        json={"name": "Empty", "currency": "INR"},
        headers=auth_headers,
    )
    pid = resp.json()["id"]

    resp = await client.get(
        f"/api/v1/analytics/drawdown/{pid}?days=365",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["drawdown"] == []


@pytest.mark.asyncio
async def test_drawdown_not_found(client: AsyncClient, auth_headers: dict[str, str]):
    resp = await client.get(
        "/api/v1/analytics/drawdown/99999?days=365",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_drawdown_unauthenticated(client: AsyncClient):
    resp = await client.get("/api/v1/analytics/drawdown/1?days=365")
    assert resp.status_code == 401
