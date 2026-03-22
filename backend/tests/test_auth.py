"""Tests for authentication endpoints (POST /api/v1/auth/...)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

async def test_register_success(client: AsyncClient):
    """A new user can register and gets a 201 response with user details."""
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "newuser@example.com",
            "password": "StrongPass99!",
            "display_name": "New User",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "newuser@example.com"
    assert data["display_name"] == "New User"
    assert data["is_active"] is True
    assert "id" in data


async def test_register_duplicate_email(client: AsyncClient):
    """Registering with an already-used email returns 409 Conflict."""
    payload = {
        "email": "dup@example.com",
        "password": "Password123!",
        "display_name": "First",
    }
    resp1 = await client.post("/api/v1/auth/register", json=payload)
    assert resp1.status_code == 201

    resp2 = await client.post("/api/v1/auth/register", json=payload)
    assert resp2.status_code == 409
    assert "already registered" in resp2.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

async def test_login_valid_credentials(client: AsyncClient):
    """Logging in with correct credentials returns access and refresh tokens."""
    # Register first
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "login@example.com",
            "password": "ValidPass88!",
        },
    )

    resp = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "login@example.com",
            "password": "ValidPass88!",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


async def test_login_wrong_password(client: AsyncClient):
    """Logging in with an incorrect password returns 401."""
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "wrongpw@example.com",
            "password": "Correct123!",
        },
    )

    resp = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "wrongpw@example.com",
            "password": "WrongPassword!",
        },
    )
    assert resp.status_code == 401
    assert "invalid" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Token Refresh
# ---------------------------------------------------------------------------

async def test_token_refresh(client: AsyncClient):
    """A valid refresh token can be exchanged for new access + refresh tokens."""
    # Register and login
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "refresh@example.com",
            "password": "RefreshMe99!",
        },
    )
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "refresh@example.com",
            "password": "RefreshMe99!",
        },
    )
    refresh_token = login_resp.json()["refresh_token"]

    # Use the refresh token
    resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"

    # Verify the refreshed access token is usable for an authenticated request
    check_resp = await client.get(
        "/api/v1/portfolios/",
        headers={"Authorization": f"Bearer {data['access_token']}"},
    )
    assert check_resp.status_code == 200
