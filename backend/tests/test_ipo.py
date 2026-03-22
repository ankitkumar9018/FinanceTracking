"""Tests for IPO endpoint and IPO service."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.services.ipo_service import _classify_status, _parse_date, _safe_float, get_ipos


# ---------------------------------------------------------------------------
# Sample data for mocking
# ---------------------------------------------------------------------------

SAMPLE_API_RESPONSE = [
    {
        "name": "Acme Corp IPO",
        "symbol": "ACME",
        "exchange": "NSE",
        "open_date": "2026-04-01",
        "close_date": "2026-04-05",
        "listing_date": None,
        "price_band": "100-120",
        "lot_size": "125",
        "issue_price": None,
        "listing_price": None,
        "current_price": None,
        "subscription_times": None,
    },
    {
        "name": "Beta Ltd IPO",
        "symbol": "BETA",
        "exchange": "NSE",
        "open_date": "2025-01-01",
        "close_date": "2025-01-05",
        "listing_date": "2025-01-15",
        "price_band": "200-250",
        "lot_size": "60",
        "issue_price": "250",
        "listing_price": "300",
        "current_price": "320",
        "subscription_times": "15.2",
    },
]


# ===========================================================================
# API endpoint tests
# ===========================================================================


@pytest.mark.asyncio
async def test_ipo_list_returns_200(client: AsyncClient, auth_headers: dict[str, str]):
    """Basic call to IPO endpoint returns 200 with ipos and count keys."""
    with patch(
        "app.services.ipo_service._fetch_from_investorgain",
        new_callable=AsyncMock,
        return_value=[],
    ):
        resp = await client.get(
            "/api/v1/ipo?exchange=NSE",
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "ipos" in data
    assert "count" in data
    assert isinstance(data["ipos"], list)
    assert data["count"] == len(data["ipos"])


@pytest.mark.asyncio
async def test_ipo_list_with_status_filter(client: AsyncClient, auth_headers: dict[str, str]):
    """Status filter parameter is accepted."""
    with patch(
        "app.services.ipo_service._fetch_from_investorgain",
        new_callable=AsyncMock,
        return_value=[],
    ):
        resp = await client.get(
            "/api/v1/ipo?status=upcoming&exchange=NSE",
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "ipos" in data


@pytest.mark.asyncio
async def test_ipo_unauthenticated(client: AsyncClient):
    """Missing auth returns 401."""
    resp = await client.get("/api/v1/ipo?exchange=NSE")
    assert resp.status_code == 401


# ===========================================================================
# IPO service unit tests
# ===========================================================================


@pytest.mark.asyncio
async def test_get_ipos_parses_upstream_data():
    """get_ipos correctly parses and classifies upstream API data."""
    # Clear the module-level cache so our mock is used
    from app.services import ipo_service
    ipo_service._cache.clear()

    with patch(
        "app.services.ipo_service._fetch_from_investorgain",
        new_callable=AsyncMock,
        return_value=SAMPLE_API_RESPONSE,
    ):
        ipos = await get_ipos(status=None, exchange="NSE")

    assert len(ipos) == 2
    names = [ipo["name"] for ipo in ipos]
    assert "Acme Corp IPO" in names
    assert "Beta Ltd IPO" in names

    # Clean up cache for other tests
    ipo_service._cache.clear()


@pytest.mark.asyncio
async def test_get_ipos_status_filter():
    """Status filter limits returned IPOs."""
    from app.services import ipo_service
    ipo_service._cache.clear()

    with patch(
        "app.services.ipo_service._fetch_from_investorgain",
        new_callable=AsyncMock,
        return_value=SAMPLE_API_RESPONSE,
    ):
        ipos = await get_ipos(status="upcoming", exchange="NSE")

    # Only Acme should be upcoming (open_date in the future)
    for ipo in ipos:
        assert ipo["status"] == "upcoming"

    ipo_service._cache.clear()


def test_classify_status_upcoming():
    """Future open date classifies as upcoming."""
    result = _classify_status("2027-01-01", "2027-01-05", None)
    assert result == "upcoming"


def test_classify_status_listed():
    """Past listing date classifies as listed."""
    result = _classify_status("2020-01-01", "2020-01-05", "2020-01-15")
    assert result == "listed"


def test_parse_date_formats():
    """_parse_date handles multiple date formats."""
    assert _parse_date("2025-06-15") == "2025-06-15"
    assert _parse_date("15-06-2025") == "2025-06-15"
    assert _parse_date("15/06/2025") == "2025-06-15"
    assert _parse_date(None) is None
    assert _parse_date("N/A") is None
    assert _parse_date("") is None


def test_safe_float():
    """_safe_float handles various inputs."""
    assert _safe_float("123.45") == 123.45
    assert _safe_float("1,234.56") == 1234.56
    assert _safe_float("₹500") == 500.0
    assert _safe_float(None) is None
    assert _safe_float("abc") is None
    assert _safe_float(0) is None  # 0 is not > 0
