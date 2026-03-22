"""Tests for portfolio CRUD endpoints (GET/POST/PUT/DELETE /api/v1/portfolios/...)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_portfolio(
    client: AsyncClient,
    headers: dict[str, str],
    name: str = "My Portfolio",
    currency: str = "INR",
) -> dict:
    """Create a portfolio and return its JSON response."""
    resp = await client.post(
        "/api/v1/portfolios/",
        json={"name": name, "currency": currency},
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

async def test_create_portfolio(client: AsyncClient, auth_headers: dict[str, str]):
    """Creating a portfolio returns 201 with the portfolio data."""
    data = await _create_portfolio(client, auth_headers, name="India Stocks", currency="INR")
    assert data["name"] == "India Stocks"
    assert data["currency"] == "INR"
    assert data["is_default"] is False
    assert "id" in data


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

async def test_list_portfolios(client: AsyncClient, auth_headers: dict[str, str]):
    """Listing portfolios returns all portfolios for the authenticated user."""
    await _create_portfolio(client, auth_headers, name="Portfolio A")
    await _create_portfolio(client, auth_headers, name="Portfolio B")

    resp = await client.get("/api/v1/portfolios/", headers=auth_headers)
    assert resp.status_code == 200
    portfolios = resp.json()
    assert len(portfolios) == 2
    names = {p["name"] for p in portfolios}
    assert "Portfolio A" in names
    assert "Portfolio B" in names


# ---------------------------------------------------------------------------
# Get by ID
# ---------------------------------------------------------------------------

async def test_get_portfolio_by_id(client: AsyncClient, auth_headers: dict[str, str]):
    """Fetching a specific portfolio by ID returns the correct data."""
    created = await _create_portfolio(client, auth_headers, name="Specific One")

    resp = await client.get(f"/api/v1/portfolios/{created['id']}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == created["id"]
    assert data["name"] == "Specific One"


# ---------------------------------------------------------------------------
# Summary (empty portfolio)
# ---------------------------------------------------------------------------

async def test_portfolio_summary_empty(client: AsyncClient, auth_headers: dict[str, str]):
    """Summary of an empty portfolio returns zero totals and no holdings."""
    created = await _create_portfolio(client, auth_headers, name="Empty")

    resp = await client.get(
        f"/api/v1/portfolios/{created['id']}/summary",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["portfolio_id"] == created["id"]
    assert data["portfolio_name"] == "Empty"
    assert data["total_invested"] == 0.0
    assert data["total_current_value"] == 0.0
    assert data["holdings"] == []


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

async def test_update_portfolio(client: AsyncClient, auth_headers: dict[str, str]):
    """Updating a portfolio changes its name and currency."""
    created = await _create_portfolio(client, auth_headers, name="Old Name", currency="INR")

    resp = await client.put(
        f"/api/v1/portfolios/{created['id']}",
        json={"name": "New Name", "currency": "EUR"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "New Name"
    assert data["currency"] == "EUR"


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

async def test_delete_portfolio(client: AsyncClient, auth_headers: dict[str, str]):
    """Deleting a portfolio returns 204 and it disappears from the list."""
    created = await _create_portfolio(client, auth_headers, name="To Delete")

    del_resp = await client.delete(
        f"/api/v1/portfolios/{created['id']}",
        headers=auth_headers,
    )
    assert del_resp.status_code == 204

    # Verify it no longer appears in the list
    list_resp = await client.get("/api/v1/portfolios/", headers=auth_headers)
    ids = [p["id"] for p in list_resp.json()]
    assert created["id"] not in ids
