"""The alert edge-trigger latch is durable, and bad conditions never get stored.

Follow-ups to the wave-3 edge-triggering work (``test_wave3_alerts_jobs.py``),
which left three gaps:

1.  The false -> true latch lived in a process-local dict, so a restart forgot
    it and every alert whose threshold was *still* crossed sent one more
    notification on the next cycle. It is now ``alerts.condition_was_true``.
2.  Editing an alert's condition kept the old latch, so a freshly raised
    threshold that the price had just crossed read as a continuation of the
    old condition and never notified.
3.  ``condition`` was a bare dict: a non-numeric threshold was accepted, then
    silently ignored at evaluation time, leaving an alert that could never
    fire and no way for the user to find out.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.user import User
from app.services.alert_service import check_alerts_for_holding

from .conftest import TEST_USER_EMAIL, TestSessionFactory

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
    user = User(email=email, password_hash="x", display_name="Latch Tester")
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


async def _seed_holding_for_auth_user(db: AsyncSession, price: float) -> Holding:
    """A holding owned by the user the ``auth_headers`` fixture registered."""
    user = (
        await db.execute(select(User).where(User.email == TEST_USER_EMAIL))
    ).scalar_one()
    portfolio = Portfolio(user_id=user.id, name="Core", currency="INR")
    db.add(portfolio)
    await db.flush()
    holding = Holding(
        portfolio_id=portfolio.id,
        stock_symbol="RELIANCE",
        stock_name="Reliance",
        exchange="NSE",
        currency="INR",
        cumulative_quantity=10.0,
        average_price=1000.0,
        current_price=price,
    )
    db.add(holding)
    await db.flush()
    await db.commit()
    return holding


# ---------------------------------------------------------------------------
# 1. The latch survives a restart
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_latch_is_persisted_on_the_row(db: AsyncSession):
    """Firing writes the latch to the column, not just to process memory."""
    user, holding = await _seed_holding(db, email="persist@example.com")
    alert = await _add_alert(db, user, holding, {"above": 1400})
    assert alert.condition_was_true is False

    assert len(await check_alerts_for_holding(holding, db)) == 1
    await db.commit()

    async with TestSessionFactory() as fresh:
        stored = (
            await fresh.execute(select(Alert).where(Alert.id == alert.id))
        ).scalar_one()
        assert stored.condition_was_true is True


@pytest.mark.asyncio
async def test_restart_does_not_re_notify_a_still_true_alert(db: AsyncSession):
    """The bug this replaces: every restart re-sent every still-crossed alert."""
    user, holding = await _seed_holding(db, email="restart@example.com")
    alert = await _add_alert(db, user, holding, {"above": 1400})

    assert len(await check_alerts_for_holding(holding, db)) == 1
    alert.last_triggered = None  # clear the cooldown; only the latch may stop it
    await db.commit()

    # A brand-new session with no in-process state at all — a restarted worker.
    async with TestSessionFactory() as fresh:
        reloaded = (
            await fresh.execute(select(Holding).where(Holding.id == holding.id))
        ).scalar_one()
        assert await check_alerts_for_holding(reloaded, fresh) == []


@pytest.mark.asyncio
async def test_falling_edge_is_persisted_so_the_next_crossing_still_fires(
    db: AsyncSession,
):
    """Re-arming must be durable too, or a restart swallows the next crossing."""
    user, holding = await _seed_holding(db, email="rearm-durable@example.com")
    alert = await _add_alert(db, user, holding, {"above": 1400})

    assert len(await check_alerts_for_holding(holding, db)) == 1

    # Falls back below the threshold: nothing fires, and the latch must be
    # written back to false — this pass triggers nothing, so a "flush only when
    # something triggered" rule would have dropped the write.
    holding.current_price = 1300.0
    alert.last_triggered = None
    await db.commit()
    assert await check_alerts_for_holding(holding, db) == []
    await db.commit()

    async with TestSessionFactory() as fresh:
        stored = (
            await fresh.execute(select(Alert).where(Alert.id == alert.id))
        ).scalar_one()
        assert stored.condition_was_true is False

        reloaded = (
            await fresh.execute(select(Holding).where(Holding.id == holding.id))
        ).scalar_one()
        reloaded.current_price = 1500.0
        assert len(await check_alerts_for_holding(reloaded, fresh)) == 1


@pytest.mark.asyncio
async def test_read_only_check_never_writes_the_latch(db: AsyncSession):
    """The alerts UI must not consume the dispatcher's rising edge."""
    user, holding = await _seed_holding(db, email="readonly-latch@example.com")
    alert = await _add_alert(db, user, holding, {"above": 1400})

    assert len(await check_alerts_for_holding(holding, db, update_state=False)) == 1
    await db.commit()

    async with TestSessionFactory() as fresh:
        stored = (
            await fresh.execute(select(Alert).where(Alert.id == alert.id))
        ).scalar_one()
        assert stored.condition_was_true is False
    assert alert.last_triggered is None


# ---------------------------------------------------------------------------
# 2. Editing an alert re-arms it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_editing_the_condition_re_arms_the_alert(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    """A raised threshold the price has already passed must still notify."""
    holding = await _seed_holding_for_auth_user(db, price=1500.0)

    created = await client.post(
        "/api/v1/alerts/",
        json={
            "holding_id": holding.id,
            "alert_type": "PRICE_RANGE",
            "condition": {"above": 1400},
        },
        headers=auth_headers,
    )
    assert created.status_code == 201
    alert_id = created.json()["id"]

    async with TestSessionFactory() as session:
        alert = (
            await session.execute(select(Alert).where(Alert.id == alert_id))
        ).scalar_one()
        h = (
            await session.execute(select(Holding).where(Holding.id == holding.id))
        ).scalar_one()
        assert len(await check_alerts_for_holding(h, session)) == 1
        alert.last_triggered = None  # only the latch is under test
        await session.commit()
        assert alert.condition_was_true is True

    resp = await client.put(
        f"/api/v1/alerts/{alert_id}",
        json={"condition": {"above": 1450}},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    async with TestSessionFactory() as session:
        alert = (
            await session.execute(select(Alert).where(Alert.id == alert_id))
        ).scalar_one()
        assert alert.condition_was_true is False
        h = (
            await session.execute(select(Holding).where(Holding.id == holding.id))
        ).scalar_one()
        assert len(await check_alerts_for_holding(h, session)) == 1


@pytest.mark.asyncio
async def test_editing_only_is_active_keeps_the_latch(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    """Toggling an unrelated field must not turn into a licence to re-notify."""
    holding = await _seed_holding_for_auth_user(db, price=1500.0)
    created = await client.post(
        "/api/v1/alerts/",
        json={"holding_id": holding.id, "condition": {"above": 1400}},
        headers=auth_headers,
    )
    alert_id = created.json()["id"]

    async with TestSessionFactory() as session:
        alert = (
            await session.execute(select(Alert).where(Alert.id == alert_id))
        ).scalar_one()
        alert.condition_was_true = True
        await session.commit()

    resp = await client.put(
        f"/api/v1/alerts/{alert_id}",
        json={"is_active": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    async with TestSessionFactory() as session:
        alert = (
            await session.execute(select(Alert).where(Alert.id == alert_id))
        ).scalar_one()
        assert alert.condition_was_true is True


@pytest.mark.asyncio
async def test_changing_the_alert_type_re_arms_the_alert(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    """A different type means a different meaning of "true" — start clean."""
    holding = await _seed_holding_for_auth_user(db, price=1500.0)
    created = await client.post(
        "/api/v1/alerts/",
        json={"holding_id": holding.id, "condition": {"above": 1400}},
        headers=auth_headers,
    )
    alert_id = created.json()["id"]

    async with TestSessionFactory() as session:
        alert = (
            await session.execute(select(Alert).where(Alert.id == alert_id))
        ).scalar_one()
        alert.condition_was_true = True
        await session.commit()

    resp = await client.put(
        f"/api/v1/alerts/{alert_id}",
        json={"alert_type": "RSI", "condition": {"rsi_above": 70}},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    async with TestSessionFactory() as session:
        alert = (
            await session.execute(select(Alert).where(Alert.id == alert_id))
        ).scalar_one()
        assert alert.condition_was_true is False


# ---------------------------------------------------------------------------
# 3. Condition validation at the API boundary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        # Non-numeric thresholds: previously stored, then ignored at evaluation.
        {"alert_type": "PRICE_RANGE", "condition": {"above": "not-a-number"}},
        {"alert_type": "PRICE_RANGE", "condition": {"below": {"nested": 1}}},
        {"alert_type": "PRICE_RANGE", "condition": {"above": [1400]}},
        # bool is an int subclass — float(True) == 1.0 is a threshold nobody meant.
        {"alert_type": "PRICE_RANGE", "condition": {"above": True}},
        # NaN compares false against everything: an alert that never fires.
        {"alert_type": "PRICE_RANGE", "condition": {"above": "nan"}},
        {"alert_type": "PRICE_RANGE", "condition": {"above": "inf"}},
        # A non-positive price threshold cannot describe a real crossing.
        {"alert_type": "PRICE_RANGE", "condition": {"above": 0}},
        {"alert_type": "PRICE_RANGE", "condition": {"below": -5}},
        # RSI is defined on 0..100; anything else never fires.
        {"alert_type": "RSI", "condition": {"rsi_above": 150}},
        {"alert_type": "RSI", "condition": {"rsi_below": "abc"}},
        # Conditions no evaluation path can satisfy.
        {"alert_type": "PRICE_RANGE", "condition": {}},
        {"alert_type": "PRICE_RANGE", "condition": {"rsi_above": 70}},
        {"alert_type": "RSI", "condition": {"above": 1400}},
        {"alert_type": "CUSTOM", "condition": {"action_needed": "Y_DARK_PURPLE"}},
        {"alert_type": "CUSTOM", "condition": {"above": 1400}},
    ],
)
@pytest.mark.asyncio
async def test_unusable_condition_is_rejected_at_create(
    client: AsyncClient, auth_headers: dict[str, str], payload: dict
):
    resp = await client.post(
        "/api/v1/alerts/", json=payload, headers=auth_headers
    )
    assert resp.status_code == 422, resp.text

    listed = await client.get("/api/v1/alerts/", headers=auth_headers)
    assert listed.json() == []


@pytest.mark.asyncio
async def test_valid_conditions_are_accepted_and_normalised(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Numbers round-trip unchanged; a numeric string is coerced to a number."""
    for alert_type, condition, expected in (
        ("PRICE_RANGE", {"above": 1400}, {"above": 1400}),
        ("PRICE_RANGE", {"below": 1400.5}, {"below": 1400.5}),
        ("PRICE_RANGE", {"above": " 1400 "}, {"above": 1400.0}),
        ("RSI", {"rsi_above": 70}, {"rsi_above": 70}),
        ("CUSTOM", {"action_needed": "Y_DARK_GREEN"}, {"action_needed": "Y_DARK_GREEN"}),
    ):
        resp = await client.post(
            "/api/v1/alerts/",
            json={"alert_type": alert_type, "condition": condition},
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        stored = resp.json()["condition"]
        assert stored == expected
        # The stored threshold is a real number, never the string that came in
        # — ``_as_float`` would otherwise re-parse it on every evaluation.
        for key in ("above", "below", "rsi_above", "rsi_below"):
            if key in stored:
                assert isinstance(stored[key], int | float)


@pytest.mark.asyncio
async def test_unusable_condition_is_rejected_on_update(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """An edit is validated against the alert's *effective* type."""
    created = await client.post(
        "/api/v1/alerts/",
        json={"alert_type": "RSI", "condition": {"rsi_above": 70}},
        headers=auth_headers,
    )
    alert_id = created.json()["id"]

    # A price threshold on an RSI alert: the request body alone never reveals
    # the mismatch, so this is caught in the endpoint against the stored type.
    resp = await client.put(
        f"/api/v1/alerts/{alert_id}",
        json={"condition": {"above": 1400}},
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text

    bad_value = await client.put(
        f"/api/v1/alerts/{alert_id}",
        json={"condition": {"rsi_above": "high"}},
        headers=auth_headers,
    )
    assert bad_value.status_code == 422

    unchanged = await client.get("/api/v1/alerts/", headers=auth_headers)
    assert unchanged.json()[0]["condition"] == {"rsi_above": 70}


@pytest.mark.asyncio
async def test_retyping_an_alert_revalidates_the_condition_it_keeps(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Switching type without touching the condition must not strand it."""
    created = await client.post(
        "/api/v1/alerts/",
        json={"alert_type": "PRICE_RANGE", "condition": {"above": 1400}},
        headers=auth_headers,
    )
    alert_id = created.json()["id"]

    # {"above": 1400} means nothing to the RSI path — the alert would go quiet
    # forever with no error anywhere.
    resp = await client.put(
        f"/api/v1/alerts/{alert_id}",
        json={"alert_type": "RSI"},
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text

    stored = (await client.get("/api/v1/alerts/", headers=auth_headers)).json()[0]
    assert stored["alert_type"] == "PRICE_RANGE"
    assert stored["condition"] == {"above": 1400}


# ---------------------------------------------------------------------------
# 4. The typed one-shot field
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_once_field_creates_a_one_shot_alert(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    """``once: true`` is the discoverable spelling of ``condition['once']``."""
    holding = await _seed_holding_for_auth_user(db, price=1500.0)
    created = await client.post(
        "/api/v1/alerts/",
        json={
            "holding_id": holding.id,
            "condition": {"above": 1400},
            "once": True,
        },
        headers=auth_headers,
    )
    assert created.status_code == 201
    body = created.json()
    assert body["condition"] == {"above": 1400, "once": True}
    alert_id = body["id"]

    async with TestSessionFactory() as session:
        h = (
            await session.execute(select(Holding).where(Holding.id == holding.id))
        ).scalar_one()
        assert len(await check_alerts_for_holding(h, session)) == 1
        await session.commit()
        alert = (
            await session.execute(select(Alert).where(Alert.id == alert_id))
        ).scalar_one()
        assert alert.is_active is False


@pytest.mark.asyncio
async def test_once_on_update_merges_into_the_stored_condition(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Setting the flag alone must not wipe the threshold beside it."""
    created = await client.post(
        "/api/v1/alerts/",
        json={"condition": {"above": 1400}},
        headers=auth_headers,
    )
    alert_id = created.json()["id"]
    assert created.json()["condition"] == {"above": 1400}

    turned_on = await client.put(
        f"/api/v1/alerts/{alert_id}", json={"once": True}, headers=auth_headers
    )
    assert turned_on.status_code == 200
    assert turned_on.json()["condition"] == {"above": 1400, "once": True}

    turned_off = await client.put(
        f"/api/v1/alerts/{alert_id}", json={"once": False}, headers=auth_headers
    )
    assert turned_off.json()["condition"] == {"above": 1400, "once": False}


@pytest.mark.asyncio
async def test_once_overrides_the_legacy_one_shot_key(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """The typed field is authoritative — a stale ``one_shot`` cannot contradict it."""
    created = await client.post(
        "/api/v1/alerts/",
        json={"condition": {"above": 1400, "one_shot": True}, "once": False},
        headers=auth_headers,
    )
    assert created.status_code == 201
    assert created.json()["condition"] == {"above": 1400, "once": False}
