"""Tests for What-If simulator endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Mock simulate result
# ---------------------------------------------------------------------------

MOCK_SIMULATE_RESULT = {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "invest_amount": 100000.0,
    "start_date": "2025-01-01",
    "end_date": "2026-01-01",
    "buy_price": 2500.0,
    "end_price": 2800.0,
    "shares_bought": 40.0,
    "current_value": 112000.0,
    "absolute_return": 12000.0,
    "percentage_return": 12.0,
    "annualized_return": 12.0,
    "holding_period_days": 365,
    "benchmark": None,
}


# ===========================================================================
# Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_simulate_success(client: AsyncClient, auth_headers: dict[str, str]):
    """Basic simulation request returns 200 with expected fields."""
    with patch(
        "app.api.v1.whatif.simulate",
        new_callable=AsyncMock,
        return_value=MOCK_SIMULATE_RESULT,
    ):
        resp = await client.post(
            "/api/v1/whatif/simulate",
            json={
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "invest_amount": 100000.0,
                "start_date": "2025-01-01",
            },
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "RELIANCE"
    assert data["invest_amount"] == 100000.0
    assert "percentage_return" in data
    assert "absolute_return" in data
    assert "shares_bought" in data
    assert "holding_period_days" in data


@pytest.mark.asyncio
async def test_simulate_with_benchmark(client: AsyncClient, auth_headers: dict[str, str]):
    """Simulation with benchmark comparison."""
    result_with_bench = {
        **MOCK_SIMULATE_RESULT,
        "benchmark": {
            "benchmark_name": "NIFTY50",
            "benchmark_start_price": 18000.0,
            "benchmark_end_price": 20000.0,
            "benchmark_return_pct": 11.11,
        },
    }
    with patch(
        "app.api.v1.whatif.simulate",
        new_callable=AsyncMock,
        return_value=result_with_bench,
    ):
        resp = await client.post(
            "/api/v1/whatif/simulate",
            json={
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "invest_amount": 100000.0,
                "start_date": "2025-01-01",
                "benchmark": "NIFTY50",
            },
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["benchmark"] is not None
    assert data["benchmark"]["benchmark_name"] == "NIFTY50"


@pytest.mark.asyncio
async def test_simulate_invalid_amount(client: AsyncClient, auth_headers: dict[str, str]):
    """Negative invest_amount should fail validation (422)."""
    resp = await client.post(
        "/api/v1/whatif/simulate",
        json={
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "invest_amount": -100.0,
            "start_date": "2025-01-01",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_simulate_missing_symbol(client: AsyncClient, auth_headers: dict[str, str]):
    """Missing required symbol field should fail validation (422)."""
    resp = await client.post(
        "/api/v1/whatif/simulate",
        json={
            "exchange": "NSE",
            "invest_amount": 100000.0,
            "start_date": "2025-01-01",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_simulate_value_error(client: AsyncClient, auth_headers: dict[str, str]):
    """Service raising ValueError returns 400."""
    with patch(
        "app.api.v1.whatif.simulate",
        new_callable=AsyncMock,
        side_effect=ValueError("No price data found for FAKE"),
    ):
        resp = await client.post(
            "/api/v1/whatif/simulate",
            json={
                "symbol": "FAKE",
                "exchange": "NSE",
                "invest_amount": 100000.0,
                "start_date": "2025-01-01",
            },
            headers=auth_headers,
        )
    assert resp.status_code == 400
    assert "No price data" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_simulate_unauthenticated(client: AsyncClient):
    """Missing auth returns 401."""
    resp = await client.post(
        "/api/v1/whatif/simulate",
        json={
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "invest_amount": 100000.0,
            "start_date": "2025-01-01",
        },
    )
    assert resp.status_code == 401
