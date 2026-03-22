"""Tests for Net Worth endpoints — asset CRUD and summary."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


# ===========================================================================
# GET /api/v1/net-worth/ — total net worth summary
# ===========================================================================


@pytest.mark.asyncio
async def test_net_worth_summary(client: AsyncClient, auth_headers: dict[str, str]):
    """Total net worth endpoint returns 200 with expected structure."""
    with patch(
        "app.api.v1.net_worth.get_net_worth",
        new_callable=AsyncMock,
        return_value={
            "total_net_worth": 500000.0,
            "breakdown": [],
            "currency": "INR",
        },
    ):
        resp = await client.get("/api/v1/net-worth/", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_net_worth" in data
    assert "breakdown" in data
    assert "currency" in data


@pytest.mark.asyncio
async def test_net_worth_summary_unauthenticated(client: AsyncClient):
    """Missing auth returns 401."""
    resp = await client.get("/api/v1/net-worth/")
    assert resp.status_code == 401


# ===========================================================================
# POST /api/v1/net-worth/assets — add a non-stock asset
# ===========================================================================


@pytest.mark.asyncio
async def test_add_asset_crypto(client: AsyncClient, auth_headers: dict[str, str]):
    """Adding a crypto asset returns 201 with asset details."""
    resp = await client.post(
        "/api/v1/net-worth/assets",
        json={
            "asset_type": "CRYPTO",
            "name": "Bitcoin",
            "symbol": "BTC-USD",
            "quantity": 0.5,
            "purchase_price": 3000000.0,
            "current_value": 3500000.0,
            "currency": "INR",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["asset_type"] == "CRYPTO"
    assert data["name"] == "Bitcoin"
    assert data["symbol"] == "BTC-USD"
    assert data["quantity"] == 0.5
    assert "id" in data


@pytest.mark.asyncio
async def test_add_asset_gold(client: AsyncClient, auth_headers: dict[str, str]):
    """Adding a gold asset returns 201."""
    resp = await client.post(
        "/api/v1/net-worth/assets",
        json={
            "asset_type": "GOLD",
            "name": "Gold Coins",
            "quantity": 10,
            "purchase_price": 50000.0,
            "current_value": 65000.0,
            "currency": "INR",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["asset_type"] == "GOLD"


@pytest.mark.asyncio
async def test_add_asset_fixed_deposit(client: AsyncClient, auth_headers: dict[str, str]):
    """Adding a fixed deposit with interest rate and maturity date."""
    resp = await client.post(
        "/api/v1/net-worth/assets",
        json={
            "asset_type": "FIXED_DEPOSIT",
            "name": "SBI FD",
            "quantity": 1,
            "purchase_price": 500000.0,
            "current_value": 500000.0,
            "currency": "INR",
            "interest_rate": 7.5,
            "maturity_date": "2027-06-15",
            "notes": "Auto-renewal enabled",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["interest_rate"] == 7.5
    assert data["maturity_date"] == "2027-06-15"
    assert data["notes"] == "Auto-renewal enabled"


@pytest.mark.asyncio
async def test_add_asset_stock_rejected(client: AsyncClient, auth_headers: dict[str, str]):
    """Adding asset_type=STOCK is rejected with 400."""
    resp = await client.post(
        "/api/v1/net-worth/assets",
        json={
            "asset_type": "STOCK",
            "name": "Reliance",
            "quantity": 10,
            "purchase_price": 25000.0,
            "current_value": 28000.0,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "Stock assets are tracked via portfolio holdings" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_add_asset_unauthenticated(client: AsyncClient):
    """Missing auth returns 401."""
    resp = await client.post(
        "/api/v1/net-worth/assets",
        json={
            "asset_type": "CRYPTO",
            "name": "Bitcoin",
            "quantity": 1,
            "purchase_price": 100000.0,
            "current_value": 120000.0,
        },
    )
    assert resp.status_code == 401


# ===========================================================================
# DELETE /api/v1/net-worth/assets/{asset_id} — remove an asset
# ===========================================================================


@pytest.mark.asyncio
async def test_delete_asset(client: AsyncClient, auth_headers: dict[str, str]):
    """Create then delete an asset returns 204."""
    # Create
    create_resp = await client.post(
        "/api/v1/net-worth/assets",
        json={
            "asset_type": "BOND",
            "name": "Govt Bond",
            "quantity": 5,
            "purchase_price": 100000.0,
            "current_value": 102000.0,
            "currency": "INR",
        },
        headers=auth_headers,
    )
    assert create_resp.status_code == 201
    asset_id = create_resp.json()["id"]

    # Delete
    del_resp = await client.delete(
        f"/api/v1/net-worth/assets/{asset_id}",
        headers=auth_headers,
    )
    assert del_resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_nonexistent_asset(client: AsyncClient, auth_headers: dict[str, str]):
    """Deleting a non-existent asset returns 404."""
    resp = await client.delete(
        "/api/v1/net-worth/assets/99999",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_asset_unauthenticated(client: AsyncClient):
    """Missing auth returns 401."""
    resp = await client.delete("/api/v1/net-worth/assets/1")
    assert resp.status_code == 401
