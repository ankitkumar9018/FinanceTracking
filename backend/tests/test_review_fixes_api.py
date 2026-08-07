"""Tests for the API / WS / task-layer review fixes.

Covers:
- indicators risk routes 404 for a missing / non-owned portfolio (ownership),
- goal creation rejecting a linked_portfolio_id owned by another user,
- alert_history resolving the correct stock symbols via the batched lookup,
- export PDF raising when xhtml2pdf reports a failure,
- WebSocket auth (shared ``app.api.ws.auth``) rejecting deactivated / missing /
  revoked tokens.

Reuses the shared conftest fixtures (``client``, ``auth_headers``, ``db``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.user import User
from app.models.watchlist import WatchlistItem
from app.utils.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_other_user_portfolio(db: AsyncSession) -> tuple[int, int]:
    """Create a second user with a portfolio; return (user_id, portfolio_id)."""
    other = User(
        email="other-owner@example.com",
        password_hash=hash_password("SecurePass123!"),
        is_active=True,
    )
    db.add(other)
    await db.flush()
    portfolio = Portfolio(user_id=other.id, name="Other's PF", currency="INR")
    db.add(portfolio)
    await db.flush()
    await db.commit()
    return other.id, portfolio.id


async def _auth_user(db: AsyncSession) -> User:
    """Return the user registered by the ``auth_headers`` fixture."""
    result = await db.execute(
        select(User).where(User.email == "testuser@example.com")
    )
    return result.scalar_one()


# ---------------------------------------------------------------------------
# 1. indicators risk routes — ownership -> 404
# ---------------------------------------------------------------------------

async def test_indicators_risk_missing_portfolio_returns_404(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.get("/api/v1/indicators/risk/999999", headers=auth_headers)
    assert resp.status_code == 404


async def test_indicators_risk_other_user_portfolio_returns_404(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
) -> None:
    _, other_pid = await _make_other_user_portfolio(db)

    resp = await client.get(
        f"/api/v1/indicators/risk/{other_pid}", headers=auth_headers
    )
    assert resp.status_code == 404

    resp_holdings = await client.get(
        f"/api/v1/indicators/risk/{other_pid}/holdings", headers=auth_headers
    )
    assert resp_holdings.status_code == 404


# ---------------------------------------------------------------------------
# 2. goal creation — linked_portfolio_id ownership
# ---------------------------------------------------------------------------

async def test_create_goal_with_other_users_portfolio_rejected(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
) -> None:
    _, other_pid = await _make_other_user_portfolio(db)

    resp = await client.post(
        "/api/v1/goals/",
        json={
            "name": "Borrow someone's portfolio",
            "target_amount": 100000,
            "category": "wealth",
            "linked_portfolio_id": other_pid,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 400


async def test_create_goal_with_own_portfolio_succeeds(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    pf = await client.post(
        "/api/v1/portfolios/",
        json={"name": "My PF", "currency": "INR"},
        headers=auth_headers,
    )
    assert pf.status_code == 201
    pid = pf.json()["id"]

    resp = await client.post(
        "/api/v1/goals/",
        json={
            "name": "Retirement",
            "target_amount": 100000,
            "category": "wealth",
            "linked_portfolio_id": pid,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["linked_portfolio_id"] == pid


# ---------------------------------------------------------------------------
# 3. alert_history — correct symbols via batched lookup
# ---------------------------------------------------------------------------

async def test_alert_history_resolves_correct_symbols(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
) -> None:
    user = await _auth_user(db)

    portfolio = Portfolio(user_id=user.id, name="Alert PF", currency="INR")
    db.add(portfolio)
    await db.flush()

    h1 = Holding(
        portfolio_id=portfolio.id,
        stock_symbol="RELIANCE",
        stock_name="Reliance Industries",
        exchange="NSE",
        cumulative_quantity=10,
        average_price=2500,
    )
    h2 = Holding(
        portfolio_id=portfolio.id,
        stock_symbol="TCS",
        stock_name="Tata Consultancy",
        exchange="NSE",
        cumulative_quantity=5,
        average_price=3500,
    )
    db.add_all([h1, h2])
    await db.flush()

    watch = WatchlistItem(
        user_id=user.id,
        stock_symbol="INFY",
        stock_name="Infosys",
        exchange="NSE",
    )
    db.add(watch)
    await db.flush()

    now = datetime.now(UTC)
    a1 = Alert(
        user_id=user.id, holding_id=h1.id, alert_type="PRICE",
        condition={}, is_active=True, channels=["in_app"], last_triggered=now,
    )
    a2 = Alert(
        user_id=user.id, holding_id=h2.id, alert_type="PRICE",
        condition={}, is_active=True, channels=["in_app"], last_triggered=now,
    )
    a3 = Alert(
        user_id=user.id, watchlist_item_id=watch.id, alert_type="PRICE",
        condition={}, is_active=True, channels=["in_app"], last_triggered=now,
    )
    db.add_all([a1, a2, a3])
    await db.commit()

    a1_id, a2_id, a3_id = a1.id, a2.id, a3.id

    # Keep the endpoint's live-check side channel off the network.
    with patch(
        "app.api.v1.alerts.check_all_alerts_for_user",
        new=AsyncMock(return_value=[]),
    ):
        resp = await client.get("/api/v1/alerts/history", headers=auth_headers)

    assert resp.status_code == 200
    history = resp.json()["history"]
    symbols = {entry["alert_id"]: entry["stock_symbol"] for entry in history}
    assert symbols[a1_id] == "RELIANCE"
    assert symbols[a2_id] == "TCS"
    assert symbols[a3_id] == "INFY"


# ---------------------------------------------------------------------------
# 4. export PDF — raise on xhtml2pdf failure
# ---------------------------------------------------------------------------

async def test_generate_portfolio_pdf_raises_on_pisa_error(db: AsyncSession) -> None:
    pytest.importorskip("xhtml2pdf")
    from app.services import export_service

    with patch.object(
        export_service,
        "generate_portfolio_report_html",
        new=AsyncMock(return_value="<html><body>ok</body></html>"),
    ), patch(
        "xhtml2pdf.pisa.CreatePDF", return_value=SimpleNamespace(err=1)
    ), pytest.raises(RuntimeError):
        await export_service.generate_portfolio_pdf(1, "Tester", db)


async def test_generate_portfolio_pdf_success_returns_bytes(db: AsyncSession) -> None:
    pytest.importorskip("xhtml2pdf")
    from app.services import export_service

    with patch.object(
        export_service,
        "generate_portfolio_report_html",
        new=AsyncMock(return_value="<html><body>Report</body></html>"),
    ):
        pdf = await export_service.generate_portfolio_pdf(1, "Tester", db)

    assert isinstance(pdf, bytes)
    assert len(pdf) > 0


# ---------------------------------------------------------------------------
# 5. WebSocket auth — user existence + revocation (unit tests)
# ---------------------------------------------------------------------------

async def test_ws_authenticate_rejects_deactivated_user(db: AsyncSession) -> None:
    from app.api.ws.auth import authenticate_token

    user = User(
        email="deactivated@example.com",
        password_hash=hash_password("SecurePass123!"),
        is_active=False,
    )
    db.add(user)
    await db.flush()

    token = create_access_token(data={"sub": str(user.id)})
    assert await authenticate_token(token, db) is None


async def test_ws_authenticate_rejects_missing_user(db: AsyncSession) -> None:
    from app.api.ws.auth import authenticate_token

    token = create_access_token(data={"sub": "987654"})
    assert await authenticate_token(token, db) is None


async def test_ws_authenticate_accepts_active_user(db: AsyncSession) -> None:
    from app.api.ws.auth import authenticate_token

    user = User(
        email="ws-active@example.com",
        password_hash=hash_password("SecurePass123!"),
        is_active=True,
    )
    db.add(user)
    await db.flush()

    pcat = (
        int(user.password_changed_at.timestamp())
        if user.password_changed_at is not None
        else 0
    )
    token = create_access_token(data={"sub": str(user.id), "pcat": pcat})
    assert await authenticate_token(token, db) == user.id


async def test_ws_authenticate_rejects_password_change_revocation(
    db: AsyncSession,
) -> None:
    from app.api.ws.auth import authenticate_token

    user = User(
        email="ws-revoked@example.com",
        password_hash=hash_password("SecurePass123!"),
        is_active=True,
    )
    db.add(user)
    await db.flush()
    assert user.password_changed_at is not None

    # Token minted BEFORE the stored password-change stamp -> revoked.
    stale_pcat = int(user.password_changed_at.timestamp()) - 100
    token = create_access_token(data={"sub": str(user.id), "pcat": stale_pcat})
    assert await authenticate_token(token, db) is None


async def test_authenticate_ws_scoped_session_honours_overrides(
    db: AsyncSession,
) -> None:
    """``authenticate_ws`` resolves ``get_db`` through dependency overrides and
    closes the session generator before returning (the deadlock-fix contract)."""
    from app.api.ws.auth import authenticate_ws
    from app.database import get_db

    user = User(
        email="ws-scoped@example.com",
        password_hash=hash_password("SecurePass123!"),
        is_active=True,
    )
    db.add(user)
    await db.flush()

    pcat = (
        int(user.password_changed_at.timestamp())
        if user.password_changed_at is not None
        else 0
    )
    token = create_access_token(data={"sub": str(user.id), "pcat": pcat})

    closed = {"value": False}

    async def _fake_get_db():
        try:
            yield db
        finally:
            closed["value"] = True

    fake_ws = SimpleNamespace(
        app=SimpleNamespace(dependency_overrides={get_db: _fake_get_db})
    )
    assert await authenticate_ws(fake_ws, token) == user.id  # type: ignore[arg-type]
    # The short-lived auth session must be closed before authenticate_ws
    # returns, i.e. before the caller's receive loop starts.
    assert closed["value"] is True
