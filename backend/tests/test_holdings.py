"""Tests for holdings + transactions endpoints.

Covers creating holdings, buy/sell transactions, cumulative calculation,
sell-more-than-held validation, range-level patching, and action_needed zones.
"""

from __future__ import annotations

from datetime import date

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_portfolio(client: AsyncClient, headers: dict[str, str]) -> int:
    """Create a portfolio and return its ID."""
    resp = await client.post(
        "/api/v1/portfolios/",
        json={"name": "Test Portfolio", "currency": "INR"},
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _create_holding(
    client: AsyncClient,
    headers: dict[str, str],
    portfolio_id: int,
    symbol: str = "RELIANCE.NS",
    name: str = "Reliance Industries",
    exchange: str = "NSE",
    quantity: float = 0.0,
    avg_price: float = 0.0,
) -> dict:
    """Create a holding and return its JSON response."""
    resp = await client.post(
        "/api/v1/holdings/",
        json={
            "portfolio_id": portfolio_id,
            "stock_symbol": symbol,
            "stock_name": name,
            "exchange": exchange,
            "cumulative_quantity": quantity,
            "average_price": avg_price,
        },
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()


async def _create_transaction(
    client: AsyncClient,
    headers: dict[str, str],
    holding_id: int,
    tx_type: str = "BUY",
    quantity: float = 10.0,
    price: float = 100.0,
    tx_date: str = "2025-01-15",
) -> dict:
    """Create a transaction and return its JSON response."""
    resp = await client.post(
        "/api/v1/transactions/",
        json={
            "holding_id": holding_id,
            "transaction_type": tx_type,
            "date": tx_date,
            "quantity": quantity,
            "price": price,
        },
        headers=headers,
    )
    return resp.json() if resp.status_code == 201 else resp.json()


# ---------------------------------------------------------------------------
# Holdings CRUD
# ---------------------------------------------------------------------------

async def test_create_holding(client: AsyncClient, auth_headers: dict[str, str]):
    """Creating a holding returns 201 with the holding data."""
    pid = await _create_portfolio(client, auth_headers)
    holding = await _create_holding(client, auth_headers, pid, symbol="TCS.NS", name="TCS Ltd")

    assert holding["stock_symbol"] == "TCS.NS"
    assert holding["stock_name"] == "TCS Ltd"
    assert holding["exchange"] == "NSE"
    assert holding["cumulative_quantity"] == 0.0
    assert holding["action_needed"] == "N"


# ---------------------------------------------------------------------------
# Transactions — BUY
# ---------------------------------------------------------------------------

async def test_create_buy_transaction(client: AsyncClient, auth_headers: dict[str, str]):
    """A BUY transaction is created successfully and linked to the holding."""
    pid = await _create_portfolio(client, auth_headers)
    holding = await _create_holding(client, auth_headers, pid)

    resp = await client.post(
        "/api/v1/transactions/",
        json={
            "holding_id": holding["id"],
            "transaction_type": "BUY",
            "date": "2025-01-10",
            "quantity": 10,
            "price": 2500.0,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    tx = resp.json()
    assert tx["transaction_type"] == "BUY"
    assert tx["quantity"] == 10.0
    assert tx["price"] == 2500.0
    assert tx["holding_id"] == holding["id"]


# ---------------------------------------------------------------------------
# Cumulative calculation
# ---------------------------------------------------------------------------

async def test_cumulative_after_transactions(client: AsyncClient, auth_headers: dict[str, str]):
    """After multiple BUY transactions, cumulative_quantity and average_price are correct."""
    pid = await _create_portfolio(client, auth_headers)
    holding = await _create_holding(client, auth_headers, pid, symbol="INFY.NS", name="Infosys")

    # BUY 10 @ 1500
    await client.post(
        "/api/v1/transactions/",
        json={
            "holding_id": holding["id"],
            "transaction_type": "BUY",
            "date": "2025-01-10",
            "quantity": 10,
            "price": 1500.0,
        },
        headers=auth_headers,
    )

    # BUY 20 @ 1600
    await client.post(
        "/api/v1/transactions/",
        json={
            "holding_id": holding["id"],
            "transaction_type": "BUY",
            "date": "2025-01-15",
            "quantity": 20,
            "price": 1600.0,
        },
        headers=auth_headers,
    )

    # Check the holding's cumulative values
    resp = await client.get(f"/api/v1/holdings/{holding['id']}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["cumulative_quantity"] == 30.0
    # Weighted avg: (10*1500 + 20*1600) / 30 = 47000/30 ~ 1566.6667
    expected_avg = round((10 * 1500 + 20 * 1600) / 30, 4)
    assert abs(data["average_price"] - expected_avg) < 0.01


# ---------------------------------------------------------------------------
# Transactions — SELL
# ---------------------------------------------------------------------------

async def test_sell_transaction_reduces_quantity(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """A SELL transaction reduces cumulative_quantity correctly."""
    pid = await _create_portfolio(client, auth_headers)
    holding = await _create_holding(client, auth_headers, pid)

    # BUY 20 @ 500
    await client.post(
        "/api/v1/transactions/",
        json={
            "holding_id": holding["id"],
            "transaction_type": "BUY",
            "date": "2025-01-01",
            "quantity": 20,
            "price": 500.0,
        },
        headers=auth_headers,
    )

    # SELL 5 @ 600
    resp = await client.post(
        "/api/v1/transactions/",
        json={
            "holding_id": holding["id"],
            "transaction_type": "SELL",
            "date": "2025-02-01",
            "quantity": 5,
            "price": 600.0,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201

    # Check holding
    h_resp = await client.get(f"/api/v1/holdings/{holding['id']}", headers=auth_headers)
    data = h_resp.json()
    assert data["cumulative_quantity"] == 15.0
    # Average price stays the same after a SELL (weighted average of BUY costs)
    assert abs(data["average_price"] - 500.0) < 0.01


async def test_sell_more_than_held_fails(client: AsyncClient, auth_headers: dict[str, str]):
    """Selling more shares than currently held returns 400 Bad Request."""
    pid = await _create_portfolio(client, auth_headers)
    holding = await _create_holding(client, auth_headers, pid)

    # BUY 5 @ 100
    await client.post(
        "/api/v1/transactions/",
        json={
            "holding_id": holding["id"],
            "transaction_type": "BUY",
            "date": "2025-01-01",
            "quantity": 5,
            "price": 100.0,
        },
        headers=auth_headers,
    )

    # Try to SELL 10 (only 5 held)
    resp = await client.post(
        "/api/v1/transactions/",
        json={
            "holding_id": holding["id"],
            "transaction_type": "SELL",
            "date": "2025-02-01",
            "quantity": 10,
            "price": 120.0,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "cannot sell" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Patch holding range levels
# ---------------------------------------------------------------------------

async def test_patch_holding_range_levels(client: AsyncClient, auth_headers: dict[str, str]):
    """Patching range levels updates the holding and recalculates action_needed."""
    pid = await _create_portfolio(client, auth_headers)
    holding = await _create_holding(client, auth_headers, pid)

    resp = await client.patch(
        f"/api/v1/holdings/{holding['id']}",
        json={
            "lower_mid_range_1": 900.0,
            "lower_mid_range_2": 800.0,
            "upper_mid_range_1": 1100.0,
            "upper_mid_range_2": 1200.0,
            "base_level": 700.0,
            "top_level": 1300.0,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["lower_mid_range_1"] == 900.0
    assert data["lower_mid_range_2"] == 800.0
    assert data["upper_mid_range_1"] == 1100.0
    assert data["upper_mid_range_2"] == 1200.0
    # No current_price set, so action_needed should be "N"
    assert data["action_needed"] == "N"


# ---------------------------------------------------------------------------
# action_needed calculations via PATCH (simulating price + ranges)
# ---------------------------------------------------------------------------
# Note: action_needed is recalculated on PATCH from current_price and range
# levels.  Since current_price is not set via the PATCH endpoint directly
# (it's set by the market data service), these tests verify the logic
# through the alert_service unit tests in test_alert_service.py.
# Here we just verify the API-level integration for the no-price case.

async def test_action_needed_no_ranges(client: AsyncClient, auth_headers: dict[str, str]):
    """A holding with no range levels defined has action_needed = 'N'."""
    pid = await _create_portfolio(client, auth_headers)
    holding = await _create_holding(client, auth_headers, pid)

    assert holding["action_needed"] == "N"
    assert holding["lower_mid_range_1"] is None
    assert holding["upper_mid_range_1"] is None
