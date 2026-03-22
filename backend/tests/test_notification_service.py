"""Phase 2 tests for the notification service.

Tests exercise ``dispatch_notification`` and ``store_in_app_notification``
directly, verifying that NotificationLog entries are persisted with the
correct channel and status values.  Email / Telegram channels are expected
to fail gracefully in CI where SendGrid / Telegram are not configured.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_log import NotificationLog
from app.models.user import User
from app.services.notification_service import (
    dispatch_notification,
    store_in_app_notification,
)
from app.utils.security import hash_password


# ---------------------------------------------------------------------------
# Helper — create a minimal user so the FK on notification_logs is satisfied
# ---------------------------------------------------------------------------

async def _create_test_user(db: AsyncSession) -> User:
    user = User(
        email="notif@test.com",
        password_hash=hash_password("Test1234!"),
        display_name="Test",
    )
    db.add(user)
    await db.flush()
    return user


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStoreInAppNotification:
    """Direct calls to store_in_app_notification()."""

    async def test_store_in_app_notification(self, db: AsyncSession) -> None:
        """Storing an in-app notification returns True and creates a SENT log entry."""
        user = await _create_test_user(db)

        result = await store_in_app_notification(
            subject="Price Alert",
            body="RELIANCE crossed 2500",
            user_id=user.id,
            db=db,
        )

        assert result is True

        rows = (await db.execute(select(NotificationLog))).scalars().all()
        assert len(rows) == 1

        log = rows[0]
        assert log.channel == "in_app"
        assert log.status == "SENT"
        assert log.user_id == user.id
        assert log.subject == "Price Alert"
        assert log.body == "RELIANCE crossed 2500"
        assert log.sent_at is not None


class TestDispatchNotification:
    """Tests for the multi-channel dispatch_notification() function."""

    async def test_dispatch_in_app_only(self, db: AsyncSession) -> None:
        """Dispatching to in_app returns success and persists a log entry."""
        user = await _create_test_user(db)

        results = await dispatch_notification(
            channels=["in_app"],
            subject="Test Subject",
            body="Test Body",
            user_id=user.id,
            db=db,
        )

        assert results == {"in_app": True}

        log = (await db.execute(select(NotificationLog))).scalar_one()
        assert log.channel == "in_app"
        assert log.status == "SENT"

    async def test_dispatch_email_not_configured(self, db: AsyncSession) -> None:
        """Email dispatch fails gracefully when SendGrid is not configured."""
        user = await _create_test_user(db)

        results = await dispatch_notification(
            channels=["email"],
            subject="Email Subject",
            body="Email Body",
            user_id=user.id,
            db=db,
            user_email="test@test.com",
        )

        assert results == {"email": False}

        log = (await db.execute(select(NotificationLog))).scalar_one()
        assert log.channel == "email"
        assert log.status == "FAILED"
        assert log.sent_at is None

    async def test_dispatch_telegram_not_configured(self, db: AsyncSession) -> None:
        """Telegram dispatch fails gracefully when bot token is not configured."""
        user = await _create_test_user(db)

        results = await dispatch_notification(
            channels=["telegram"],
            subject="TG Subject",
            body="TG Body",
            user_id=user.id,
            db=db,
        )

        assert results == {"telegram": False}

        log = (await db.execute(select(NotificationLog))).scalar_one()
        assert log.channel == "telegram"
        assert log.status == "FAILED"
        assert log.sent_at is None

    async def test_dispatch_unknown_channel(self, db: AsyncSession) -> None:
        """An unrecognised channel name returns False without creating a log entry."""
        user = await _create_test_user(db)

        results = await dispatch_notification(
            channels=["carrier_pigeon"],
            subject="Pigeon Post",
            body="Coo coo",
            user_id=user.id,
            db=db,
        )

        assert results == {"carrier_pigeon": False}

        # Unknown channels are silently skipped — no log entry is created
        rows = (await db.execute(select(NotificationLog))).scalars().all()
        assert len(rows) == 0

    async def test_dispatch_multiple_channels(self, db: AsyncSession) -> None:
        """Dispatching to [in_app, email] succeeds for in_app, fails for email."""
        user = await _create_test_user(db)

        results = await dispatch_notification(
            channels=["in_app", "email"],
            subject="Multi Channel",
            body="Body text",
            user_id=user.id,
            db=db,
            user_email="test@test.com",
        )

        assert "in_app" in results
        assert "email" in results
        assert results["in_app"] is True
        assert results["email"] is False

        logs = (
            (await db.execute(select(NotificationLog).order_by(NotificationLog.id)))
            .scalars()
            .all()
        )
        assert len(logs) == 2

        channels_and_statuses = {(l.channel, l.status) for l in logs}
        assert ("in_app", "SENT") in channels_and_statuses
        assert ("email", "FAILED") in channels_and_statuses
