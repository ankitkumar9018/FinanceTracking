"""Security / correctness regressions for auth, settings and alert routes.

Covers:
- ``POST /auth/change-password`` hands back a working replacement token pair
  (it revokes the caller's own access *and* refresh tokens via ``pcat``).
- The new ``password_changed_at`` stamp round-trips through the DB without
  shifting the ``pcat`` claim, so the fresh token is not self-revoked.
- Every credential-verifying 2FA route is rate limited (backup-code
  regeneration used to be the one unthrottled TOTP check).
- ``POST /settings/test/telegram`` targets the *user's* chat id and never logs
  the bot token.
- ``GET /alerts/`` emits offset-aware timestamps (a naive one is parsed as
  local time by the browser and lands on the wrong day).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import ClassVar

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert
from app.models.user import User

# ---------------------------------------------------------------------------
# (1) change-password returns a usable replacement token pair
# ---------------------------------------------------------------------------


async def _register_and_login(
    client: AsyncClient, email: str, password: str
) -> dict:
    await client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200
    return login.json()


async def test_change_password_returns_working_token_pair(client: AsyncClient):
    """The response carries a fresh pair, and both halves actually work.

    Regression: the endpoint bumped ``password_changed_at`` (revoking the
    caller's own access and refresh tokens) but returned only a message, so the
    UI reported success and the user was silently bounced to the login screen on
    the next request.
    """
    email = "changepw-tokens@example.com"
    password = "OldPass123!"
    old = await _register_and_login(client, email, password)
    old_headers = {"Authorization": f"Bearer {old['access_token']}"}

    resp = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": password, "new_password": "BrandNewPass456!"},
        headers=old_headers,
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["message"] == "Password updated successfully"
    assert payload["token_type"] == "bearer"
    assert payload["access_token"] and payload["refresh_token"]
    assert payload["access_token"] != old["access_token"]

    # The new access token authenticates the very next request.
    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == email

    # The new refresh token is honoured too (it carries the new pcat).
    refreshed = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": payload["refresh_token"]}
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]


async def test_change_password_pcat_matches_stored_stamp(
    client: AsyncClient, db: AsyncSession
):
    """The minted ``pcat`` equals what ``validate_pcat`` recomputes from the row.

    ``password_changed_at`` is a naive-UTC column: an aware value written there
    comes back naive, and ``naive.timestamp()`` is interpreted in the *server's*
    local zone. Minting from the aware value therefore produced a ``pcat`` that
    disagreed with the reloaded row by the UTC offset — on a host west of UTC
    that difference rejects the freshly issued token immediately.
    """
    from app.api.deps import validate_pcat
    from app.utils.security import decode_token

    email = "changepw-pcat@example.com"
    password = "OldPass123!"
    tokens = await _register_and_login(client, email, password)

    resp = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": password, "new_password": "BrandNewPass456!"},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert resp.status_code == 200

    claims = decode_token(resp.json()["access_token"])
    assert claims is not None

    stored = (await db.execute(select(User).where(User.email == email))).scalar_one()
    assert stored.password_changed_at is not None
    assert claims["pcat"] == int(stored.password_changed_at.timestamp())
    assert validate_pcat(claims, stored) is True

    # And the pre-change token is still revoked.
    stale = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert stale.status_code == 401


# ---------------------------------------------------------------------------
# (2) every credential-verifying 2FA route is throttled
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "endpoint",
    [
        "regenerate_backup_codes",
        "setup_2fa",
        "verify_2fa",
        "disable_2fa",
        "change_password",
    ],
)
def test_credential_routes_are_rate_limited(endpoint: str):
    """Regression: /2fa/backup-codes/regenerate verified a 6-digit TOTP with no
    limiter at all, so a stolen access token could brute-force the second factor
    and burn the owner's recovery codes."""
    from app.utils.rate_limiter import limiter

    key = f"app.api.v1.auth.{endpoint}"
    limits = limiter._route_limits.get(key, [])
    assert limits, f"{endpoint} has no rate limit configured"
    assert any("10 per 1 minute" in str(limit.limit) for limit in limits)


async def test_regenerate_backup_codes_accepts_request_param(
    client: AsyncClient, auth_headers: dict
):
    """Adding ``request: Request`` for the limiter must not change the contract.

    (The limiter itself is disabled in the test suite, so this exercises the
    route body: 2FA off -> 400, not a 422 from the new parameter.)
    """
    resp = await client.post(
        "/api/v1/auth/2fa/backup-codes/regenerate",
        json={"code": "123456"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "2FA is not enabled"


async def test_2fa_setup_still_returns_secret(
    client: AsyncClient, auth_headers: dict
):
    """/2fa/setup keeps working after gaining a ``request`` parameter."""
    resp = await client.post("/api/v1/auth/2fa/setup", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["totp_secret"]) >= 16
    assert body["totp_uri"].startswith("otpauth://")


# ---------------------------------------------------------------------------
# (3) /settings/test/telegram — per-user chat id, and no token in the logs
# ---------------------------------------------------------------------------


class _StubResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            request = httpx.Request(
                "POST",
                "https://api.telegram.org/bot123456:SUPER-SECRET-TOKEN/sendMessage",
            )
            raise httpx.HTTPStatusError(
                f"Client error '{self.status_code}' for url '{request.url}'",
                request=request,
                response=httpx.Response(self.status_code, request=request),
            )


class _StubClient:
    """Minimal stand-in for httpx.AsyncClient that records the call."""

    calls: ClassVar[list[tuple[str, dict]]] = []
    status_code: ClassVar[int] = 200

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def post(self, url: str, json: dict | None = None, **kwargs):
        type(self).calls.append((url, json or {}))
        return _StubResponse(type(self).status_code)


@pytest.fixture
def stub_telegram(monkeypatch):
    """Patch httpx.AsyncClient and configure a bot token for the test."""
    import httpx

    from app.config import settings as app_settings

    _StubClient.calls = []
    _StubClient.status_code = 200
    monkeypatch.setattr(httpx, "AsyncClient", _StubClient)
    monkeypatch.setattr(app_settings, "telegram_bot_token", "123456:SUPER-SECRET-TOKEN")
    monkeypatch.setattr(app_settings, "telegram_chat_id", None)
    return _StubClient


async def test_test_telegram_uses_the_users_chat_id(
    client: AsyncClient, auth_headers: dict, stub_telegram
):
    """With only a per-user chat id set, the test message still goes out — to it.

    Regression: the endpoint gated on (and sent to) the global env chat id, so a
    user who configured their chat id on the same Settings page got
    "Telegram bot token or chat ID not configured" even though real alert
    delivery (notification_service.send_telegram) would have worked.
    """
    saved = await client.put(
        "/api/v1/settings/", json={"telegram_chat_id": "987654321"},
        headers=auth_headers,
    )
    assert saved.status_code == 200

    resp = await client.post("/api/v1/settings/test/telegram", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"status": "sent", "chat_id": "987654321"}

    assert len(stub_telegram.calls) == 1
    _url, payload = stub_telegram.calls[0]
    assert payload["chat_id"] == "987654321"


async def test_test_telegram_prefers_user_chat_over_global_env(
    client: AsyncClient, auth_headers: dict, stub_telegram, monkeypatch
):
    """A stray TELEGRAM_CHAT_ID env value must not hijack the user's test."""
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "telegram_chat_id", "111-global-chat")
    await client.put(
        "/api/v1/settings/", json={"telegram_chat_id": "222-user-chat"},
        headers=auth_headers,
    )

    resp = await client.post("/api/v1/settings/test/telegram", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["chat_id"] == "222-user-chat"
    assert stub_telegram.calls[0][1]["chat_id"] == "222-user-chat"


async def test_test_telegram_503_when_no_chat_id_anywhere(
    client: AsyncClient, auth_headers: dict, stub_telegram
):
    """No user chat id and no env chat id is still a 503, with nothing sent."""
    resp = await client.post("/api/v1/settings/test/telegram", headers=auth_headers)
    assert resp.status_code == 503
    assert stub_telegram.calls == []


async def test_test_telegram_failure_never_logs_the_bot_token(
    client: AsyncClient, auth_headers: dict, stub_telegram, caplog
):
    """A failed send logs the exception type and status — never the token.

    ``httpx.HTTPStatusError`` embeds the request URL (which carries the bot
    token) in its message, so ``logger.exception`` wrote the token in clear text
    into the backend log.
    """
    stub_telegram.status_code = 401
    await client.put(
        "/api/v1/settings/", json={"telegram_chat_id": "987654321"},
        headers=auth_headers,
    )

    with caplog.at_level(logging.DEBUG, logger="app.api.v1.settings"):
        resp = await client.post(
            "/api/v1/settings/test/telegram", headers=auth_headers
        )

    assert resp.status_code == 502
    assert "SUPER-SECRET-TOKEN" not in resp.text

    logged = "\n".join(
        record.getMessage() + (record.exc_text or "") for record in caplog.records
    )
    assert "SUPER-SECRET-TOKEN" not in logged
    assert "api.telegram.org/bot" not in logged
    assert "HTTPStatusError" in logged
    assert "status=401" in logged


# ---------------------------------------------------------------------------
# (4) alert timestamps carry a UTC offset
# ---------------------------------------------------------------------------


async def test_list_alerts_timestamps_are_offset_aware(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
):
    """Regression: naive ISO strings are parsed as *local* time by JavaScript,
    so "Last triggered" showed the wrong calendar day for any viewer whose UTC
    offset spanned the trigger instant."""
    user = (
        await db.execute(select(User).where(User.email == "testuser@example.com"))
    ).scalar_one()

    # Naive-UTC value, exactly as the alert engine writes it.
    triggered = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2)
    db.add(
        Alert(
            user_id=user.id,
            alert_type="PRICE_RANGE",
            condition={"above": 100.0},
            is_active=True,
            channels=["in_app"],
            last_triggered=triggered,
        )
    )
    await db.commit()

    resp = await client.get("/api/v1/alerts/", headers=auth_headers)
    assert resp.status_code == 200
    [alert] = resp.json()

    for field in ("created_at", "last_triggered"):
        value = alert[field]
        # An explicit UTC designator ("Z" or "+00:00") — never a bare
        # "2026-08-29T10:00:00", which JS reads as local time.
        assert value.endswith(("Z", "+00:00")), f"{field} is naive: {value}"
        assert datetime.fromisoformat(value).tzinfo is not None

    assert datetime.fromisoformat(alert["last_triggered"]) == triggered.replace(
        tzinfo=UTC
    )


async def test_created_alert_response_is_offset_aware(
    client: AsyncClient, auth_headers: dict
):
    """POST /alerts/ stamps the offset too (the UI renders this body directly)."""
    resp = await client.post(
        "/api/v1/alerts/",
        json={
            "alert_type": "PRICE_RANGE",
            "condition": {"above": 100.0},
            "channels": ["in_app"],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["created_at"].endswith(("Z", "+00:00"))
    assert body["last_triggered"] is None

    updated = await client.put(
        f"/api/v1/alerts/{body['id']}",
        json={"is_active": False},
        headers=auth_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["created_at"].endswith(("Z", "+00:00"))
