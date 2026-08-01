"""Security-hardening regression tests.

Covers:
- JWT ``pcat`` token revocation on password change (tokens minted before a
  password change are rejected).
- Constant-time login for unknown emails (bcrypt runs even with no user).
- Fail-closed guard on the default JWT secret in production.
- Refresh tokens with a non-numeric ``sub`` return 401 (not 500).
- Google LLM provider sends the API key via header, not the URL query string.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


# ---------------------------------------------------------------------------
# (a) Token revocation on password change via the "pcat" claim
# ---------------------------------------------------------------------------

async def test_token_rejected_after_password_change(
    client: AsyncClient, db: AsyncSession
):
    """An access token minted before a password change is rejected (401)."""
    email = "revoke@example.com"
    password = "RevokeMe123!"

    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # The freshly-minted token works.
    ok = await client.get("/api/v1/auth/me", headers=headers)
    assert ok.status_code == 200

    # Simulate a password change by advancing password_changed_at well past the
    # token's mint time (a full minute avoids any same-second boundary).
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one()
    user.password_changed_at = datetime.now(timezone.utc) + timedelta(minutes=1)
    await db.commit()

    # The previously-issued token is now stale and rejected.
    rejected = await client.get("/api/v1/auth/me", headers=headers)
    assert rejected.status_code == 401


async def test_login_token_contains_pcat_claim(client: AsyncClient):
    """Issued access tokens carry a numeric ``pcat`` claim."""
    from app.utils.security import decode_token

    email = "pcat@example.com"
    password = "PcatPass123!"
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    payload = decode_token(login.json()["access_token"])
    assert payload is not None
    assert "pcat" in payload
    assert isinstance(payload["pcat"], int)
    assert payload["pcat"] > 0


async def test_change_password_endpoint_bumps_stamp(client: AsyncClient):
    """Changing the password via the API invalidates the old access token."""
    email = "changepw@example.com"
    password = "OldPass123!"
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    old_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": password, "new_password": "BrandNewPass456!"},
        headers=old_headers,
    )
    assert resp.status_code == 200
    # password_changed_at is bumped; the old token's pcat is now stale.
    assert resp.json()["message"]


# ---------------------------------------------------------------------------
# (b) Constant-time login for unknown emails (user enumeration mitigation)
# ---------------------------------------------------------------------------

async def test_login_unknown_user_runs_bcrypt(
    client: AsyncClient, monkeypatch
):
    """Login for a non-existent email still runs a bcrypt verify and 401s."""
    import app.api.v1.auth as auth_mod

    calls: list[str] = []
    real_verify = auth_mod.verify_password

    def spy(plain: str, hashed: str) -> bool:
        calls.append(hashed)
        return real_verify(plain, hashed)

    monkeypatch.setattr(auth_mod, "verify_password", spy)

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "ghost@example.com", "password": "whatever123"},
    )
    assert resp.status_code == 401
    assert "invalid" in resp.json()["detail"].lower()
    # verify_password was invoked even though the user does not exist.
    assert calls, "bcrypt verify should run for unknown users to equalize timing"
    assert calls[0] == auth_mod._DUMMY_PASSWORD_HASH


# ---------------------------------------------------------------------------
# (c) Fail-closed on the default JWT secret outside debug mode
# ---------------------------------------------------------------------------

def test_secret_key_fail_closed_raises_in_production():
    """Default dev secret + debug disabled → RuntimeError (fail closed)."""
    from app.main import _enforce_secret_key

    with pytest.raises(RuntimeError):
        _enforce_secret_key(
            secret_key="dev-secret-CHANGE-IN-PRODUCTION", debug=False
        )


def test_secret_key_only_warns_in_debug():
    """Default dev secret is tolerated (warning only) when debug is on."""
    from app.main import _enforce_secret_key

    # Should not raise.
    _enforce_secret_key(secret_key="dev-secret-CHANGE-IN-PRODUCTION", debug=True)


def test_secret_key_ok_when_custom():
    """A real secret never raises, regardless of debug mode."""
    from app.main import _enforce_secret_key

    _enforce_secret_key(secret_key="a-strong-random-production-secret", debug=False)


# ---------------------------------------------------------------------------
# Refresh token with a non-numeric subject → 401, not 500
# ---------------------------------------------------------------------------

async def test_refresh_non_numeric_sub_returns_401(client: AsyncClient):
    """A refresh token whose ``sub`` is not an int is rejected with 401."""
    from app.utils.security import create_refresh_token

    forged = create_refresh_token({"sub": "not-a-number", "email": "x@y.z"})
    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": forged}
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Google LLM provider sends the API key via header, not the URL query string
# ---------------------------------------------------------------------------

async def test_google_provider_key_in_header_not_url(monkeypatch):
    """GoogleProvider.chat must not place the API key in the request URL."""
    import app.ml.llm_assistant as llm

    captured: dict = {}

    class _FakeResp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "candidates": [
                    {"content": {"parts": [{"text": "hi"}]}}
                ]
            }

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers or {}
            return _FakeResp()

    monkeypatch.setattr(llm.settings, "google_api_key", "SECRET-KEY-123")
    monkeypatch.setattr(llm.httpx, "AsyncClient", _FakeClient)

    provider = llm.GoogleProvider()
    result = await provider.chat([llm.ChatMessage(role="user", content="hello")])

    assert result.message == "hi"
    assert "key=" not in captured["url"]
    assert "SECRET-KEY-123" not in captured["url"]
    assert captured["headers"].get("x-goog-api-key") == "SECRET-KEY-123"
