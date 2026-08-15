"""Background task: generate scheduled AI portfolio digests.

Runs on a daily cadence (see the shared JOBS spec in ``celery_app.py``).
For each active user whose ``ai_digest_frequency`` preference is:

- ``daily``  → generate on every run;
- ``weekly`` → generate only on Mondays (UTC);
- ``off`` / unset → skip.

The digest is stored as the user's latest (inside ``notification_preferences``)
and dispatched as an in-app notification plus whichever extra channels the
user has enabled in their notification preferences. Everything per-user is
best-effort: one failing user never blocks the rest, and notification
dispatch failures never fail the digest.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select

from app.database import async_session_factory
from app.models.user import User
from app.services.ai_digest_service import generate_digest, get_digest_frequency
from app.services.notification_service import dispatch_notification
from app.tasks.celery_app import celery_app, run_async

logger = logging.getLogger(__name__)

# Channels a user can additionally enable via notification_preferences
# ("<channel>_enabled" flags, same shape the settings API reads/writes).
_OPTIONAL_CHANNELS = ("email", "telegram", "whatsapp", "sms")


def _digest_channels(prefs: dict) -> list[str]:
    """In-app always; plus every channel the user enabled in preferences."""
    channels = ["in_app"]
    channels.extend(
        ch for ch in _OPTIONAL_CHANNELS if prefs.get(f"{ch}_enabled", False)
    )
    return channels


# ---------------------------------------------------------------------------
# Core async task
# ---------------------------------------------------------------------------


async def run_scheduled_digests(
    session_factory: Callable | None = None,
) -> dict:
    """Generate + store + dispatch digests for every scheduled user.

    ``session_factory`` is injectable for tests; production callers use the
    app's ``async_session_factory``.

    Returns a summary dict: ``users_checked``, ``digests_generated``,
    ``notifications_sent``, ``skipped``.
    """
    factory = session_factory or async_session_factory
    is_monday = datetime.now(UTC).weekday() == 0

    generated = 0
    notifications = 0
    skipped = 0

    async with factory() as db:
        result = await db.execute(select(User).where(User.is_active.is_(True)))
        users = list(result.scalars().all())

        for user in users:
            frequency = get_digest_frequency(user)
            due = frequency == "daily" or (frequency == "weekly" and is_monday)
            if not due:
                skipped += 1
                continue

            try:
                digest = await generate_digest(user.id, db)
                generated += 1
            except Exception:
                logger.exception(
                    "scheduled digest generation failed for user %d", user.id
                )
                continue

            # Best-effort dispatch — never let a channel failure raise.
            try:
                prefs = user.notification_preferences or {}
                results = await dispatch_notification(
                    channels=_digest_channels(prefs),
                    subject="Your AI portfolio digest",
                    body=digest["content"],
                    user_id=user.id,
                    db=db,
                    user_email=user.email,
                    user_phone=user.phone,
                    telegram_chat_id=user.telegram_chat_id,
                )
                notifications += sum(1 for ok in results.values() if ok)
            except Exception:
                logger.exception(
                    "digest notification dispatch failed for user %d", user.id
                )

        await db.commit()

    logger.info(
        "run_scheduled_digests: users=%d, generated=%d, notifications=%d, skipped=%d",
        len(users),
        generated,
        notifications,
        skipped,
    )
    return {
        "users_checked": len(users),
        "digests_generated": generated,
        "notifications_sent": notifications,
        "skipped": skipped,
    }


# ---------------------------------------------------------------------------
# Celery task wrapper (registered whenever Celery is importable)
# ---------------------------------------------------------------------------
# Same pattern as check_alerts.py: registration depends only on the package
# being importable, because the beat schedule always references this name.

if celery_app is not None:

    @celery_app.task(
        name="app.tasks.ai_digest_task.run_scheduled_digests_celery", bind=True
    )
    def run_scheduled_digests_celery(self) -> dict:  # type: ignore[misc]
        """Celery-compatible wrapper that runs the async task synchronously."""
        return run_async(run_scheduled_digests)
