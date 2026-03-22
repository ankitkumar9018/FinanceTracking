"""Tests for ESG scoring endpoints."""

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


# ===========================================================================
# GET /api/v1/esg/stock/{symbol} — single stock ESG
# ===========================================================================


@pytest.mark.asyncio
async def test_stock_esg_success(client: AsyncClient, auth_headers: dict[str, str]):
    """Stock ESG endpoint returns 200 with score fields."""
    mock_scores = [
        {
            "symbol": "RELIANCE",
            "total_esg": 32.5,
            "environment_score": 10.0,
            "social_score": 12.0,
            "governance_score": 10.5,
            "esg_available": True,
        }
    ]
    with patch(
        "app.api.v1.esg.get_esg_scores",
        new_callable=AsyncMock,
        return_value=mock_scores,
    ):
        resp = await client.get(
            "/api/v1/esg/stock/RELIANCE?exchange=NSE",
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "RELIANCE"
    assert data["esg_available"] is True
    assert "total_esg" in data
    assert "environment_score" in data
    assert "social_score" in data
    assert "governance_score" in data


@pytest.mark.asyncio
async def test_stock_esg_unavailable(client: AsyncClient, auth_headers: dict[str, str]):
    """Stock with no ESG data returns null scores."""
    with patch(
        "app.api.v1.esg.get_esg_scores",
        new_callable=AsyncMock,
        return_value=[],
    ):
        resp = await client.get(
            "/api/v1/esg/stock/SMALLCAP?exchange=NSE",
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["esg_available"] is False
    assert data["total_esg"] is None


@pytest.mark.asyncio
async def test_stock_esg_unauthenticated(client: AsyncClient):
    """Missing auth returns 401."""
    resp = await client.get("/api/v1/esg/stock/RELIANCE?exchange=NSE")
    assert resp.status_code == 401


# ===========================================================================
# GET /api/v1/esg/{portfolio_id} — portfolio ESG dashboard
# ===========================================================================


@pytest.mark.asyncio
async def test_portfolio_esg_success(client: AsyncClient, auth_headers: dict[str, str]):
    """Portfolio ESG endpoint returns 200 with weighted scores."""
    pid = await _setup(client, auth_headers)

    mock_result = {
        "portfolio_id": pid,
        "portfolio_name": "Test",
        "weighted_total_esg": 28.5,
        "weighted_environment": 9.0,
        "weighted_social": 10.5,
        "weighted_governance": 9.0,
        "holdings_with_esg": 1,
        "holdings_without_esg": 0,
        "stock_scores": [
            {
                "symbol": "RELIANCE",
                "total_esg": 28.5,
                "environment_score": 9.0,
                "social_score": 10.5,
                "governance_score": 9.0,
                "esg_available": True,
            }
        ],
    }
    with patch(
        "app.api.v1.esg.get_portfolio_esg",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        resp = await client.get(
            f"/api/v1/esg/{pid}",
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["portfolio_id"] == pid
    assert "weighted_total_esg" in data
    assert "stock_scores" in data
    assert isinstance(data["stock_scores"], list)


@pytest.mark.asyncio
async def test_portfolio_esg_not_found(client: AsyncClient, auth_headers: dict[str, str]):
    """Non-existent portfolio returns 404."""
    resp = await client.get(
        "/api/v1/esg/99999",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_portfolio_esg_unauthenticated(client: AsyncClient):
    """Missing auth returns 401."""
    resp = await client.get("/api/v1/esg/1")
    assert resp.status_code == 401
