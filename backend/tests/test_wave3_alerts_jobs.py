"""Wave-3 fixes for the alert engine and the background jobs.

Covers, in order:

1.  Alerts are edge-triggered — a condition that merely *stays* true does not
    re-notify every cooldown window (it used to, up to 288 times a day). The
    latch's durability across a restart is covered in
    ``test_alert_edge_durability.py``.
2.  The read-only evaluation used by the alerts UI is still level-triggered
    and leaves both ``last_triggered`` and the edge latch untouched.
3.  ``{"once": true}`` in the condition deactivates the alert after one send.
4.  A non-numeric threshold is ignored instead of raising out of the cycle.
5.  ``check_alerts_task`` isolates a failing user instead of aborting the run.
6.  Cooldown stamps and notification logs are committed *before* the
    irreversible send, so a later failure can't cause a re-send.
7.  The ``price_update`` broadcast no longer carries one holder's private
    ``action_needed`` zone to every other subscriber of that symbol.
8.  ``run_async`` no longer re-runs a whole Celery task when it raises
    RuntimeError.
9.  AI alert explanations run concurrently under one deadline instead of
    ~20 s serially per alert.
10. Telegram no longer falls back to the shared chat id on a multi-user
    instance.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import ClassVar

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.alert import Alert
from app.models.holding import Holding
from app.models.notification_log import NotificationLog
from app.models.portfolio import Portfolio
from app.models.user import User
from app.services import alert_service
from app.services.alert_service import check_alerts_for_holding

from .conftest import TestSessionFactory

# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_holding(
    db: AsyncSession,
    *,
    email: str,
    price: float = 1500.0,
    symbol: str = "RELIANCE",
) -> tuple[User, Holding]:
    user = User(email=email, password_hash="x", display_name="Alerts Tester")
    db.add(user)
    await db.flush()
    portfolio = Portfolio(user_id=user.id, name="Core", currency="INR")
    db.add(portfolio)
    await db.flush()
    holding = Holding(
        portfolio_id=portfolio.id,
        stock_symbol=symbol,
        stock_name=symbol,
        exchange="NSE",
        currency="INR",
        cumulative_quantity=10.0,
        average_price=1000.0,
        current_price=price,
    )
    db.add(holding)
    await db.flush()
    return user, holding


async def _add_alert(
    db: AsyncSession,
    user: User,
    holding: Holding,
    condition: dict,
    *,
    alert_type: str = "PRICE_RANGE",
) -> Alert:
    alert = Alert(
        user_id=user.id,
        holding_id=holding.id,
        alert_type=alert_type,
        condition=condition,
        is_active=True,
        channels=["in_app"],
    )
    db.add(alert)
    await db.commit()
    return alert


# ---------------------------------------------------------------------------
# 1. Edge triggering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_alert_fires_once_while_the_condition_stays_true(db: AsyncSession):
    """A price that crosses a threshold and stays there notifies once, not forever."""
    user, holding = await _seed_holding(db, email="edge@example.com", price=1500.0)
    alert = await _add_alert(db, user, holding, {"above": 1400})

    first = await check_alerts_for_holding(holding, db)
    assert len(first) == 1
    assert "above threshold 1400.00" in first[0]["message"]

    # Clear the 5-minute cooldown: without edge triggering this is exactly the
    # every-5-minutes re-send the cooldown alone could not prevent.
    alert.last_triggered = None
    await db.commit()

    assert await check_alerts_for_holding(holding, db) == []


@pytest.mark.asyncio
async def test_alert_re_arms_after_the_condition_goes_false(db: AsyncSession):
    """Falling back below the threshold re-arms the alert for the next crossing."""
    user, holding = await _seed_holding(db, email="rearm@example.com", price=1500.0)
    alert = await _add_alert(db, user, holding, {"above": 1400})

    assert len(await check_alerts_for_holding(holding, db)) == 1

    # Condition goes false — no notification, and the latch is released.
    holding.current_price = 1300.0
    alert.last_triggered = None
    await db.commit()
    assert await check_alerts_for_holding(holding, db) == []

    # Crossing again is a fresh rising edge.
    holding.current_price = 1500.0
    await db.commit()
    assert len(await check_alerts_for_holding(holding, db)) == 1


@pytest.mark.asyncio
async def test_cooldown_defers_a_rising_edge_instead_of_consuming_it(
    db: AsyncSession,
):
    """An edge inside the cooldown window is delivered once the window expires."""
    user, holding = await _seed_holding(db, email="defer@example.com", price=1500.0)
    alert = await _add_alert(db, user, holding, {"above": 1400})
    alert.last_triggered = datetime.now(UTC).replace(tzinfo=None)
    await db.commit()

    # Inside the cooldown: nothing is sent and the latch is NOT set.
    assert await check_alerts_for_holding(holding, db) == []

    alert.last_triggered = datetime.now(UTC).replace(tzinfo=None) - timedelta(
        seconds=alert_service.ALERT_COOLDOWN_SECONDS + 1
    )
    await db.commit()

    assert len(await check_alerts_for_holding(holding, db)) == 1


# ---------------------------------------------------------------------------
# 2. Read-only evaluation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_only_check_is_level_triggered_and_stateless(db: AsyncSession):
    """The alerts UI keeps seeing a satisfied condition and never latches it."""
    user, holding = await _seed_holding(db, email="readonly@example.com", price=1500.0)
    alert = await _add_alert(db, user, holding, {"above": 1400})

    for _ in range(3):
        live = await check_alerts_for_holding(holding, db, update_state=False)
        assert len(live) == 1

    assert alert.last_triggered is None
    # The read-only pass left the latch alone, so the dispatcher still fires.
    assert len(await check_alerts_for_holding(holding, db)) == 1


# ---------------------------------------------------------------------------
# 3. One-shot alerts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_shot_alert_deactivates_itself(db: AsyncSession):
    """``{"once": true}`` survives a restart by clearing ``is_active``."""
    user, holding = await _seed_holding(db, email="oneshot@example.com", price=1500.0)
    alert = await _add_alert(db, user, holding, {"above": 1400, "once": True})

    assert len(await check_alerts_for_holding(holding, db)) == 1
    await db.commit()
    assert alert.is_active is False

    # Even with the latch forcibly cleared and no cooldown, it stays quiet.
    alert.condition_was_true = False
    alert.last_triggered = None
    await db.commit()
    assert await check_alerts_for_holding(holding, db) == []


# ---------------------------------------------------------------------------
# 4. Malformed conditions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_numeric_threshold_is_ignored_not_raised(db: AsyncSession):
    """``Alert.condition`` is unvalidated JSON — a text threshold must not raise."""
    user, holding = await _seed_holding(db, email="badcond@example.com", price=1500.0)
    await _add_alert(db, user, holding, {"above": "not-a-number"})

    assert await check_alerts_for_holding(holding, db) == []


@pytest.mark.asyncio
async def test_non_dict_condition_is_ignored_not_raised(db: AsyncSession):
    """A condition stored as a list must not raise AttributeError either."""
    user, holding = await _seed_holding(db, email="listcond@example.com", price=1500.0)
    await _add_alert(db, user, holding, {"above": 1400})
    # Bypass the ORM type check the same way bad data would arrive from an
    # older row: assign the raw JSON value.
    alert = (await db.execute(select(Alert))).scalar_one()
    alert.condition = ["above", 1400]  # type: ignore[assignment]
    await db.commit()

    assert await check_alerts_for_holding(holding, db) == []


# ---------------------------------------------------------------------------
# 5-6. check_alerts_task: per-user isolation and commit-before-send
# ---------------------------------------------------------------------------


def _stub_trigger(alert_id: int, symbol: str = "RELIANCE") -> dict:
    return {
        "alert_id": alert_id,
        "alert_type": "PRICE_RANGE",
        "condition": {"above": 1400},
        "triggered_at": datetime.now(UTC),
        "stock_symbol": symbol,
        "message": f"{symbol} price 1500.00 is above threshold 1400.00",
        "channels": ["in_app"],
    }


@pytest.fixture
def _no_ai_explanations(monkeypatch):
    monkeypatch.setattr(settings, "ai_alert_explanations", False)


@pytest.mark.asyncio
async def test_one_failing_user_does_not_abort_the_cycle(
    db: AsyncSession, monkeypatch, _no_ai_explanations
):
    """A malformed alert for user A must not stop user B from being notified."""
    import app.tasks.check_alerts as check_alerts_mod

    user_a, holding_a = await _seed_holding(db, email="a-fails@example.com")
    user_b, holding_b = await _seed_holding(
        db, email="b-works@example.com", symbol="TCS"
    )
    await _add_alert(db, user_a, holding_a, {"above": 1400})
    alert_b = await _add_alert(db, user_b, holding_b, {"above": 1400})

    monkeypatch.setattr(check_alerts_mod, "async_session_factory", TestSessionFactory)

    async def _check(user_id: int, session) -> list[dict]:
        if user_id == user_a.id:
            raise ValueError("could not convert string to float: 'boom'")
        return [_stub_trigger(alert_b.id, "TCS")]

    monkeypatch.setattr(check_alerts_mod, "check_all_alerts_for_user", _check)

    result = await check_alerts_mod.check_alerts_task()

    assert result["users_checked"] == 2
    assert result["users_failed"] == 1
    assert result["alerts_triggered"] == 1
    assert result["notifications_sent"] == 1

    async with TestSessionFactory() as fresh:
        logs = (await fresh.execute(select(NotificationLog))).scalars().all()
    assert [(log.user_id, log.channel) for log in logs] == [(user_b.id, "in_app")]


@pytest.mark.asyncio
async def test_cooldown_stamp_is_committed_before_the_send(
    db: AsyncSession, monkeypatch, _no_ai_explanations
):
    """A dispatch failure must not roll back the dedup stamp of a real send."""
    import app.tasks.check_alerts as check_alerts_mod

    user, holding = await _seed_holding(db, email="stamp@example.com")
    alert = await _add_alert(db, user, holding, {"above": 1400})

    monkeypatch.setattr(check_alerts_mod, "async_session_factory", TestSessionFactory)

    async def _boom(**kwargs):
        raise RuntimeError("SMTP is down")

    monkeypatch.setattr(check_alerts_mod, "dispatch_notification", _boom)

    result = await check_alerts_mod.check_alerts_task()
    assert result["alerts_triggered"] == 1
    assert result["notifications_sent"] == 0
    assert result["users_failed"] == 0

    async with TestSessionFactory() as fresh:
        stored = await fresh.get(Alert, alert.id)
        assert stored is not None
        # Committed before dispatch, so the next cycle won't re-send it.
        assert stored.last_triggered is not None


@pytest.mark.asyncio
async def test_delivered_notifications_survive_a_later_user_failure(
    db: AsyncSession, monkeypatch, _no_ai_explanations
):
    """User A's committed log entry outlives an exception raised for user B."""
    import app.tasks.check_alerts as check_alerts_mod

    user_a, holding_a = await _seed_holding(db, email="first@example.com")
    user_b, holding_b = await _seed_holding(
        db, email="second@example.com", symbol="INFY"
    )
    alert_a = await _add_alert(db, user_a, holding_a, {"above": 1400})
    await _add_alert(db, user_b, holding_b, {"above": 1400})

    monkeypatch.setattr(check_alerts_mod, "async_session_factory", TestSessionFactory)

    async def _check(user_id: int, session) -> list[dict]:
        if user_id == user_a.id:
            return [_stub_trigger(alert_a.id)]
        raise RuntimeError("transient DB error")

    monkeypatch.setattr(check_alerts_mod, "check_all_alerts_for_user", _check)

    result = await check_alerts_mod.check_alerts_task()
    assert result["users_failed"] == 1
    assert result["notifications_sent"] == 1

    async with TestSessionFactory() as fresh:
        logs = (await fresh.execute(select(NotificationLog))).scalars().all()
    assert len(logs) == 1
    assert logs[0].user_id == user_a.id
    assert logs[0].status == "SENT"


# ---------------------------------------------------------------------------
# 7. price_update payload must not leak a private zone
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_price_broadcast_omits_the_private_action_zone(monkeypatch):
    """``action_needed`` is derived from the owner's private levels — never fan it out."""
    from app.tasks import fetch_prices as fp

    seen: list[tuple[str, dict]] = []

    class _Recorder:
        async def broadcast_price_update(
            self, symbol: str, data: dict, exchange: str | None = None
        ) -> None:
            seen.append((symbol, data))

    monkeypatch.setattr(fp, "manager", _Recorder())

    sent = await fp._broadcast_updates(
        [
            {
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "current_price": 1500.0,
                "rsi": 61.2,
                "action_needed": "Y_DARK_GREEN",
                "last_price_update": "2026-09-05T10:00:00+00:00",
            }
        ]
    )

    assert sent == 1
    symbol, payload = seen[0]
    assert symbol == "RELIANCE"
    assert "action_needed" not in payload
    assert payload == {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "current_price": 1500.0,
        "rsi": 61.2,
        "last_price_update": "2026-09-05T10:00:00+00:00",
    }


# ---------------------------------------------------------------------------
# 8. run_async
# ---------------------------------------------------------------------------


def test_run_async_does_not_rerun_a_task_that_raises_runtimeerror():
    """A RuntimeError from the task itself must not be read as 'no event loop'."""
    from app.tasks.celery_app import run_async

    calls = []

    async def _task() -> dict:
        calls.append(1)
        raise RuntimeError("alert cycle blew up")

    with pytest.raises(RuntimeError, match="alert cycle blew up"):
        run_async(_task)

    assert calls == [1], "the task body ran twice — duplicate sends"


def test_run_async_returns_the_result_with_no_running_loop():
    from app.tasks.celery_app import run_async

    async def _task() -> dict:
        return {"ok": True}

    assert run_async(_task) == {"ok": True}


@pytest.mark.asyncio
async def test_run_async_from_inside_a_running_loop():
    """The defensive thread path still runs the coroutine exactly once."""
    from app.tasks.celery_app import run_async

    calls = []

    async def _task() -> dict:
        calls.append(1)
        return {"ok": True}

    assert await asyncio.to_thread(run_async, _task) == {"ok": True}
    assert calls == [1]


# ---------------------------------------------------------------------------
# 9. AI explanations: concurrent and time-boxed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_alert_explanations_run_concurrently(monkeypatch):
    """Five slow explanations must cost about one delay, not five."""
    from app.services import ai_digest_service
    from app.tasks import check_alerts as check_alerts_mod

    monkeypatch.setattr(settings, "ai_alert_explanations", True)
    monkeypatch.setattr(settings, "ai_alert_explain_timeout", 5.0)

    async def _slow(alert_info: dict) -> str:
        await asyncio.sleep(0.2)
        return f"because {alert_info['stock_symbol']} moved"

    monkeypatch.setattr(ai_digest_service, "explain_alert_trigger", _slow)

    infos = [_stub_trigger(i, f"SYM{i}") for i in range(5)]
    started = time.perf_counter()
    explanations = await check_alerts_mod._explain_batch(infos)
    elapsed = time.perf_counter() - started

    assert explanations == [f"because SYM{i} moved" for i in range(5)]
    # Serial (the old behaviour) would be >= 1.0 s.
    assert elapsed < 0.6, f"explanations appear to be serial ({elapsed:.2f}s)"


@pytest.mark.asyncio
async def test_alert_explanations_are_time_boxed_end_to_end(monkeypatch):
    """A hung provider probe can no longer delay the alert job past its budget."""
    from app.services import ai_digest_service
    from app.tasks import check_alerts as check_alerts_mod

    monkeypatch.setattr(settings, "ai_alert_explanations", True)
    monkeypatch.setattr(settings, "ai_alert_explain_timeout", 0.1)
    monkeypatch.setattr(settings, "alert_check_interval", 1)

    async def _hangs(alert_info: dict) -> str:
        await asyncio.sleep(30)
        return "never"

    monkeypatch.setattr(ai_digest_service, "explain_alert_trigger", _hangs)

    infos = [_stub_trigger(i, f"SYM{i}") for i in range(3)]
    started = time.perf_counter()
    explanations = await check_alerts_mod._explain_batch(infos)
    elapsed = time.perf_counter() - started

    assert explanations == [None, None, None]
    assert elapsed < 2.0, f"explanation phase was not time-boxed ({elapsed:.2f}s)"


@pytest.mark.asyncio
async def test_explanations_skipped_when_disabled(monkeypatch):
    from app.services import ai_digest_service
    from app.tasks import check_alerts as check_alerts_mod

    monkeypatch.setattr(settings, "ai_alert_explanations", False)

    called = []

    async def _tracked(alert_info: dict) -> str:
        called.append(alert_info)
        return "x"

    monkeypatch.setattr(ai_digest_service, "explain_alert_trigger", _tracked)

    assert await check_alerts_mod._explain_batch([_stub_trigger(1)]) == [None]
    assert called == []


# ---------------------------------------------------------------------------
# 10. Telegram must not fall back to the shared chat id on a multi-user install
# ---------------------------------------------------------------------------


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None


class _FakeAsyncClient:
    """Records every Telegram Bot API call instead of making one."""

    posts: ClassVar[list[dict]] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def post(self, url: str, json: dict | None = None) -> _FakeResponse:
        _FakeAsyncClient.posts.append(json or {})
        return _FakeResponse()


@pytest.fixture
def _fake_telegram(monkeypatch):
    import app.services.notification_service as ns

    _FakeAsyncClient.posts = []
    monkeypatch.setattr(ns.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(settings, "telegram_bot_token", "test-token")
    monkeypatch.setattr(settings, "telegram_chat_id", "operator-chat")
    return _FakeAsyncClient


@pytest.mark.asyncio
async def test_telegram_refuses_the_shared_chat_id_on_a_multi_user_instance(
    db: AsyncSession, _fake_telegram
):
    """User B without a chat id must not have their alerts sent to the operator."""
    from app.services.notification_service import send_telegram

    db.add_all(
        [
            User(email="owner@example.com", password_hash="x", display_name="Owner"),
            User(email="other@example.com", password_hash="x", display_name="Other"),
        ]
    )
    await db.flush()
    other = (
        await db.execute(select(User).where(User.email == "other@example.com"))
    ).scalar_one()

    ok = await send_telegram(
        message="RELIANCE is above 1400", user_id=other.id, db=db, chat_id=None
    )

    assert ok is False
    assert _fake_telegram.posts == []
    log = (await db.execute(select(NotificationLog))).scalar_one()
    assert log.channel == "telegram"
    assert log.status == "FAILED"
    assert log.sent_at is None


@pytest.mark.asyncio
async def test_telegram_uses_the_shared_chat_id_on_a_single_user_instance(
    db: AsyncSession, _fake_telegram
):
    """The desktop/.env single-account setup keeps working without a per-user id."""
    from app.services.notification_service import send_telegram

    user = User(email="solo@example.com", password_hash="x", display_name="Solo")
    db.add(user)
    await db.flush()

    ok = await send_telegram(
        message="RELIANCE is above 1400", user_id=user.id, db=db, chat_id=None
    )

    assert ok is True
    assert [p["chat_id"] for p in _fake_telegram.posts] == ["operator-chat"]


@pytest.mark.asyncio
async def test_telegram_always_prefers_the_per_user_chat_id(
    db: AsyncSession, _fake_telegram
):
    from app.services.notification_service import send_telegram

    user = User(email="mine@example.com", password_hash="x", display_name="Mine")
    db.add(user)
    await db.flush()

    ok = await send_telegram(
        message="hello", user_id=user.id, db=db, chat_id="my-own-chat"
    )

    assert ok is True
    assert [p["chat_id"] for p in _fake_telegram.posts] == ["my-own-chat"]
