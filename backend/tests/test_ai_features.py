"""Tests for the grounded AI features: digest, report AI summary, alert notes.

Everything is stubbed — no network, no real LLM provider:
- digest numbers-only fallback with no provider (grounded, real numbers),
- digest with a stub provider (its text + provider name),
- digest timeout falls back to the numbers-only digest,
- schedule PUT/GET round-trip via the API,
- scheduled task generates for a "daily" user and skips "off" users,
- report route unchanged without ai_summary; labeled section with a stub,
- alert explanation appended with a stub provider and absent on timeout.
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.ml.llm_assistant import ChatResponse
from app.models.alert import Alert
from app.models.holding import Holding
from app.models.notification_log import NotificationLog
from app.models.portfolio import Portfolio
from app.models.user import User
from app.services import ai_digest_service
from app.services.ai_digest_service import (
    DIGEST_LATEST_KEY,
    generate_digest,
)
from tests.conftest import TestSessionFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_portfolio(
    db: AsyncSession, email: str = "digest@example.com"
) -> tuple[User, Portfolio]:
    """User with one portfolio and two priced holdings (invested 42,500 INR)."""
    user = User(email=email, password_hash="x", display_name="Digest Tester")
    db.add(user)
    await db.flush()
    portfolio = Portfolio(user_id=user.id, name="Core", currency="INR")
    db.add(portfolio)
    await db.flush()
    db.add_all([
        Holding(
            portfolio_id=portfolio.id, stock_symbol="RELIANCE",
            stock_name="Reliance Industries", exchange="NSE", currency="INR",
            cumulative_quantity=10.0, average_price=2500.0, current_price=2800.0,
            sector="Energy",
        ),
        Holding(
            portfolio_id=portfolio.id, stock_symbol="TCS",
            stock_name="Tata Consultancy", exchange="NSE", currency="INR",
            cumulative_quantity=5.0, average_price=3500.0, current_price=3400.0,
            sector="IT",
        ),
    ])
    await db.flush()
    return user, portfolio


class _StubProvider:
    """Canned-reply provider; optionally sleeps to trigger timeouts."""

    NAME = "stub"

    def __init__(self, reply: str = "Stubbed AI digest.", delay: float = 0.0):
        self.reply = reply
        self.delay = delay
        self.calls = 0

    async def chat(self, messages, system_prompt: str = "") -> ChatResponse:
        self.calls += 1
        self.seen_system_prompt = system_prompt
        if self.delay:
            await asyncio.sleep(self.delay)
        return ChatResponse(
            message=self.reply, provider=self.NAME, model="stub", tokens_used=1
        )


def _patch_provider(monkeypatch, provider) -> None:
    async def _active():
        return provider

    monkeypatch.setattr(ai_digest_service, "get_active_provider", _active)


def _patch_no_provider(monkeypatch) -> None:
    _patch_provider(monkeypatch, None)


# ---------------------------------------------------------------------------
# Feature 1 — digest generation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_digest_numbers_only_fallback_no_provider(db: AsyncSession, monkeypatch):
    user, _ = await _seed_portfolio(db)
    _patch_no_provider(monkeypatch)

    digest = await generate_digest(user.id, db)

    assert digest["provider"] == "none"
    assert digest["grounded"] is True
    assert digest["generated_at"]
    # Real numbers from the compiled context, not generic filler.
    assert "RELIANCE" in digest["content"] and "TCS" in digest["content"]
    assert "42,500" in digest["content"] or "42500" in digest["content"]
    assert "not financial advice" in digest["content"].lower()
    # Persisted as the latest digest in the JSON preferences.
    stored = (user.notification_preferences or {}).get(DIGEST_LATEST_KEY)
    assert stored is not None and stored["content"] == digest["content"]


@pytest.mark.asyncio
async def test_digest_empty_account_is_ungrounded(db: AsyncSession, monkeypatch):
    user = User(email="empty-digest@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    _patch_no_provider(monkeypatch)

    digest = await generate_digest(user.id, db)
    assert digest["grounded"] is False
    assert digest["provider"] == "none"
    assert "No holdings" in digest["content"]


@pytest.mark.asyncio
async def test_digest_with_stub_provider(db: AsyncSession, monkeypatch):
    user, _ = await _seed_portfolio(db, email="digest-stub@example.com")
    stub = _StubProvider(reply="Your portfolio gained nicely this week.")
    _patch_provider(monkeypatch, stub)

    digest = await generate_digest(user.id, db)

    assert digest["provider"] == "stub"
    assert digest["content"] == "Your portfolio gained nicely this week."
    assert digest["grounded"] is True
    # The provider was grounded in the real context via the system prompt.
    assert "RELIANCE" in stub.seen_system_prompt
    assert "=== END PORTFOLIO CONTEXT ===" in stub.seen_system_prompt


@pytest.mark.asyncio
async def test_digest_timeout_falls_back_to_numbers(db: AsyncSession, monkeypatch):
    user, _ = await _seed_portfolio(db, email="digest-slow@example.com")
    stub = _StubProvider(reply="too late", delay=0.5)
    _patch_provider(monkeypatch, stub)
    monkeypatch.setattr(settings, "ai_digest_timeout", 0.05)

    digest = await generate_digest(user.id, db)

    assert digest["provider"] == "none"
    assert "too late" not in digest["content"]
    assert "RELIANCE" in digest["content"]  # numbers-only fallback served


# ---------------------------------------------------------------------------
# Feature 1 — schedule API round-trip
# ---------------------------------------------------------------------------


async def test_digest_schedule_roundtrip(client: AsyncClient, auth_headers):
    # Default is "off"
    resp = await client.get("/api/v1/ai/digest/schedule", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"frequency": "off"}

    resp = await client.put(
        "/api/v1/ai/digest/schedule",
        json={"frequency": "weekly"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {"frequency": "weekly"}

    resp = await client.get("/api/v1/ai/digest/schedule", headers=auth_headers)
    assert resp.json() == {"frequency": "weekly"}

    # Invalid frequency rejected by validation
    resp = await client.put(
        "/api/v1/ai/digest/schedule",
        json={"frequency": "hourly"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_digest_get_before_generate_404_with_hint(
    client: AsyncClient, auth_headers
):
    resp = await client.get("/api/v1/ai/digest/", headers=auth_headers)
    assert resp.status_code == 404
    assert "generate" in resp.json()["detail"].lower()


async def test_digest_generate_endpoint_then_get(
    client: AsyncClient, auth_headers, db: AsyncSession, monkeypatch
):
    _patch_no_provider(monkeypatch)

    resp = await client.post("/api/v1/ai/digest/generate", headers=auth_headers)
    assert resp.status_code == 200
    generated = resp.json()
    assert generated["provider"] == "none"

    resp = await client.get("/api/v1/ai/digest/", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["content"] == generated["content"]


# ---------------------------------------------------------------------------
# Feature 1 — scheduled task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduled_digests_daily_generated_off_skipped(
    db: AsyncSession, monkeypatch
):
    from app.tasks.ai_digest_task import run_scheduled_digests

    daily_user, _ = await _seed_portfolio(db, email="daily@example.com")
    daily_user.notification_preferences = {"ai_digest_frequency": "daily"}
    off_user, _ = await _seed_portfolio(db, email="off@example.com")
    off_user.notification_preferences = {"ai_digest_frequency": "off"}
    await db.commit()

    _patch_no_provider(monkeypatch)

    summary = await run_scheduled_digests(session_factory=TestSessionFactory)

    assert summary["users_checked"] == 2
    assert summary["digests_generated"] == 1
    assert summary["skipped"] == 1

    # Daily user got a stored digest + an in-app notification; off user didn't.
    await db.refresh(daily_user)
    await db.refresh(off_user)
    assert DIGEST_LATEST_KEY in (daily_user.notification_preferences or {})
    assert DIGEST_LATEST_KEY not in (off_user.notification_preferences or {})

    logs = (
        (await db.execute(select(NotificationLog))).scalars().all()
    )
    assert len(logs) == 1
    assert logs[0].user_id == daily_user.id
    assert logs[0].channel == "in_app"
    assert "RELIANCE" in logs[0].body


def test_ai_digest_job_registered_in_shared_spec():
    from app.tasks.celery_app import JOBS

    job = next(j for j in JOBS if j.id == "ai_digest_job")
    assert job.interval_seconds() == 24 * 60 * 60
    assert job.celery_task == "app.tasks.ai_digest_task.run_scheduled_digests_celery"


# ---------------------------------------------------------------------------
# Feature 2 — AI summary in the HTML report
# ---------------------------------------------------------------------------


async def _seed_auth_user_portfolio(db: AsyncSession) -> int:
    """Give the ``auth_headers`` user a priced portfolio; return its id."""
    result = await db.execute(
        select(User).where(User.email == "testuser@example.com")
    )
    user = result.scalar_one()
    portfolio = Portfolio(user_id=user.id, name="Report PF", currency="INR")
    db.add(portfolio)
    await db.flush()
    db.add(Holding(
        portfolio_id=portfolio.id, stock_symbol="INFY", stock_name="Infosys",
        exchange="NSE", currency="INR", cumulative_quantity=4.0,
        average_price=1500.0, current_price=1600.0, sector="IT",
    ))
    await db.commit()
    return portfolio.id


async def test_report_without_ai_summary_unchanged(
    client: AsyncClient, auth_headers, db: AsyncSession, monkeypatch
):
    pid = await _seed_auth_user_portfolio(db)

    # Even with a provider active, the section must not appear when the
    # param is absent or false — and the AI must not even be called.
    stub = _StubProvider(reply="should not appear")
    _patch_provider(monkeypatch, stub)

    resp = await client.get(
        f"/api/v1/import-export/export/report/{pid}", headers=auth_headers
    )
    assert resp.status_code == 200
    default_html = resp.text
    assert "AI Summary" not in default_html
    assert stub.calls == 0

    resp = await client.get(
        f"/api/v1/import-export/export/report/{pid}?ai_summary=false",
        headers=auth_headers,
    )
    assert resp.text == default_html  # byte-identical


async def test_report_with_ai_summary_stub_provider(
    client: AsyncClient, auth_headers, db: AsyncSession, monkeypatch
):
    pid = await _seed_auth_user_portfolio(db)
    stub = _StubProvider(reply="Portfolio is up overall; <IT> dominates.")
    _patch_provider(monkeypatch, stub)

    resp = await client.get(
        f"/api/v1/import-export/export/report/{pid}?ai_summary=true",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    html = resp.text
    assert "AI Summary" in html
    assert "AI-generated — educational, not financial advice" in html
    # Text present and HTML-escaped.
    assert "Portfolio is up overall; &lt;IT&gt; dominates." in html
    assert "<IT>" not in html
    assert stub.calls == 1


async def test_report_with_ai_summary_provider_failure_still_exports(
    client: AsyncClient, auth_headers, db: AsyncSession, monkeypatch
):
    pid = await _seed_auth_user_portfolio(db)

    async def _boom():
        raise RuntimeError("provider discovery exploded")

    monkeypatch.setattr(ai_digest_service, "get_active_provider", _boom)

    resp = await client.get(
        f"/api/v1/import-export/export/report/{pid}?ai_summary=true",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert "AI Summary" not in resp.text


# ---------------------------------------------------------------------------
# Feature 3 — alert explanations
# ---------------------------------------------------------------------------


def _triggered_alert_stub(user_id: int, alert_id: int) -> dict:
    from datetime import UTC, datetime

    return {
        "alert_id": alert_id,
        "alert_type": "PRICE_RANGE",
        "condition": {"above": 3500},
        "triggered_at": datetime.now(UTC),
        "stock_symbol": "TCS",
        "message": "TCS price 3600.00 above 3500.00",
        "channels": ["in_app"],
    }


async def _seed_alert_user(db: AsyncSession) -> tuple[User, Alert]:
    user, portfolio = await _seed_portfolio(db, email="alerts@example.com")
    holding_id = (
        await db.execute(
            select(Holding.id).where(Holding.portfolio_id == portfolio.id).limit(1)
        )
    ).scalar_one()
    alert = Alert(
        user_id=user.id, holding_id=holding_id, alert_type="PRICE_RANGE",
        condition={"above": 3500}, is_active=True, channels=["in_app"],
    )
    db.add(alert)
    await db.commit()
    return user, alert


async def _run_check_alerts(monkeypatch, user: User, alert: Alert) -> str:
    """Run check_alerts_task against the test DB with a canned triggered alert;
    return the notification body that was stored."""
    import app.tasks.check_alerts as check_alerts_mod

    monkeypatch.setattr(
        check_alerts_mod, "async_session_factory", TestSessionFactory
    )

    async def _fake_check_all(user_id: int, db) -> list[dict]:
        return [_triggered_alert_stub(user_id, alert.id)]

    monkeypatch.setattr(
        check_alerts_mod, "check_all_alerts_for_user", _fake_check_all
    )

    result = await check_alerts_mod.check_alerts_task()
    assert result["alerts_triggered"] == 1

    async with TestSessionFactory() as db:
        log = (
            (await db.execute(select(NotificationLog))).scalars().all()
        )
        assert len(log) == 1
        return log[0].body


@pytest.mark.asyncio
async def test_alert_explanation_appended_with_stub(db: AsyncSession, monkeypatch):
    user, alert = await _seed_alert_user(db)
    stub = _StubProvider(reply="TCS crossed your upper price threshold.")
    _patch_provider(monkeypatch, stub)

    body = await _run_check_alerts(monkeypatch, user, alert)

    assert body.startswith("TCS price 3600.00 above 3500.00")
    assert "TCS crossed your upper price threshold." in body


@pytest.mark.asyncio
async def test_alert_explanation_absent_on_timeout(db: AsyncSession, monkeypatch):
    user, alert = await _seed_alert_user(db)
    stub = _StubProvider(reply="way too slow", delay=0.5)
    _patch_provider(monkeypatch, stub)
    monkeypatch.setattr(settings, "ai_alert_explain_timeout", 0.05)

    body = await _run_check_alerts(monkeypatch, user, alert)

    assert body == "TCS price 3600.00 above 3500.00"


@pytest.mark.asyncio
async def test_alert_explanation_disabled_by_setting(db: AsyncSession, monkeypatch):
    user, alert = await _seed_alert_user(db)
    stub = _StubProvider(reply="should never be asked")
    _patch_provider(monkeypatch, stub)
    monkeypatch.setattr(settings, "ai_alert_explanations", False)

    body = await _run_check_alerts(monkeypatch, user, alert)

    assert body == "TCS price 3600.00 above 3500.00"
    assert stub.calls == 0
