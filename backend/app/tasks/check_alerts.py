"""Background task: evaluate all active alerts and dispatch notifications."""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func as sql_func

from app.api.ws.connection_manager import manager
from app.config import settings
from app.database import async_session_factory
from app.models.alert import Alert
from app.models.user import User
from app.services.alert_service import check_all_alerts_for_user
from app.services.notification_service import dispatch_notification
from app.tasks.celery_app import celery_app, run_async
from app.utils.concurrency import gather_bounded

logger = logging.getLogger(__name__)

# How many AI explanations may be in flight at once. The whole point is that
# the phase costs about one timeout instead of one timeout per alert.
_EXPLAIN_CONCURRENCY = 8


# ---------------------------------------------------------------------------
# AI explanations
# ---------------------------------------------------------------------------


async def _explain_batch(alert_infos: list[dict]) -> list[str | None]:
    """Best-effort one-sentence AI explanations for a batch of triggered alerts.

    These used to be generated one at a time, each awaited before its own alert
    was dispatched, and only the provider's ``chat()`` call was time-boxed —
    the availability probe in front of it was not. A reachable-but-slow local
    model therefore added ~20 s of latency *per triggered alert* inside a job
    that runs every ``alert_check_interval`` (60 s) under APScheduler's
    ``max_instances=1``, so from three alerts upwards the job overran its own
    interval and the following cycles were silently dropped.

    Running the batch concurrently with the per-item timeout applied to the
    *entire* call (probe included) keeps the phase at roughly one timeout, and
    the outer deadline caps it even when many alerts fire in one cycle. Any
    failure yields ``None`` for that alert and the plain message is sent.
    """
    count = len(alert_infos)
    if not count or not settings.ai_alert_explanations:
        return [None] * count

    from app.services.ai_digest_service import explain_alert_trigger

    per_item = max(1.0, float(settings.ai_alert_explain_timeout))
    # Never let the explanation phase eat more than half the job's interval.
    overall = max(per_item, float(settings.alert_check_interval) / 2)

    factories: list[Callable[[], Awaitable[str | None]]] = [
        functools.partial(explain_alert_trigger, info) for info in alert_infos
    ]
    try:
        async with asyncio.timeout(overall):
            explanations = await gather_bounded(
                factories, limit=_EXPLAIN_CONCURRENCY, timeout=per_item
            )
        return list(explanations)
    except TimeoutError:
        logger.warning(
            "alert explanations exceeded the %.0fs budget — sending plain messages",
            overall,
        )
    except Exception:
        logger.debug("alert explanations unavailable", exc_info=True)
    return [None] * count


# ---------------------------------------------------------------------------
# Per-user evaluation + dispatch
# ---------------------------------------------------------------------------


async def _process_user(db: AsyncSession, user_id: int) -> tuple[int, int]:
    """Evaluate and dispatch one user's alerts.

    Returns ``(alerts_triggered, notifications_sent)``. Raises only on errors
    the caller should isolate — the caller rolls back and moves to the next
    user so one bad alert cannot stop alert checking for the whole install.
    """
    # Load the user for the email/phone/chat-id the notification channels need.
    user_obj = await db.get(User, user_id)
    user_email = user_obj.email if user_obj else None
    user_phone = getattr(user_obj, "phone", None) if user_obj else None
    user_telegram_chat_id = (
        getattr(user_obj, "telegram_chat_id", None) if user_obj else None
    )

    triggered = await check_all_alerts_for_user(user_id, db)

    # Commit the cooldown stamps BEFORE anything is sent. Email/SMS/Telegram
    # are irreversible side effects; while this state was only flushed and
    # committed after the whole run, any later failure (or the desktop shell
    # killing the process on close) rolled it back and every alert already
    # delivered was delivered again on the next cycle, forever.
    await db.commit()

    if not triggered:
        return 0, 0

    explanations = await _explain_batch(triggered)
    notifications = 0

    for alert_info, explanation in zip(triggered, explanations, strict=True):
        message = alert_info.get("message", "Alert triggered")
        if explanation:
            message = f"{message}\n{explanation}"
        subject = (
            f"Alert: {alert_info.get('stock_symbol', 'N/A')} "
            f"— {alert_info.get('alert_type', 'CUSTOM')}"
        )

        try:
            results = await dispatch_notification(
                channels=alert_info.get("channels", ["in_app"]),
                subject=subject,
                body=message,
                user_id=user_id,
                db=db,
                alert_id=alert_info.get("alert_id"),
                user_email=user_email,
                user_phone=user_phone,
                telegram_chat_id=user_telegram_chat_id,
            )
            notifications += sum(1 for ok in results.values() if ok)
            # Persist this alert's NotificationLog rows straight away, so the
            # in-app list can't lose entries for messages already delivered.
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception(
                "Notification dispatch failed for alert %s",
                alert_info.get("alert_id"),
            )

        # ── Real-time WebSocket alert ─────────────────────────────────────
        try:
            await manager.send_alert(
                user_id,
                {
                    "type": "alert_triggered",
                    "data": {
                        "alert_id": alert_info.get("alert_id"),
                        "alert_type": alert_info.get("alert_type"),
                        "stock_symbol": alert_info.get("stock_symbol"),
                        "message": message,
                        "triggered_at": (
                            alert_info.get("triggered_at") or datetime.now(UTC)
                        ).isoformat(),
                    },
                },
            )
        except Exception:
            logger.exception("WebSocket alert delivery failed for user %d", user_id)

    return len(triggered), notifications


# ---------------------------------------------------------------------------
# Core async task
# ---------------------------------------------------------------------------


async def check_alerts_task() -> dict:
    """Check every active alert and dispatch notifications for triggered ones.

    Deduplication is twofold: an alert only notifies on a false -> true edge of
    its condition, and never more than once per cooldown window (5 minutes).

    Each user is evaluated and committed independently, so a malformed alert —
    ``Alert.condition`` is unvalidated JSON — can no longer abort the cycle for
    everyone else.

    Returns
    -------
    dict
        Summary with keys ``users_checked``, ``alerts_triggered``,
        ``notifications_sent`` and ``users_failed``.
    """
    logger.info("check_alerts_task: starting alert evaluation")

    async with async_session_factory() as db:
        try:
            # Discover all distinct users that own at least one active alert
            result = await db.execute(
                select(sql_func.distinct(Alert.user_id)).where(
                    Alert.is_active.is_(True),
                )
            )
            user_ids: list[int] = [row[0] for row in result.all()]
        except Exception:
            await db.rollback()
            logger.exception(
                "check_alerts_task: could not list users with active alerts"
            )
            raise

        if not user_ids:
            logger.debug("check_alerts_task: no users with active alerts")
            return {
                "users_checked": 0,
                "alerts_triggered": 0,
                "notifications_sent": 0,
                "users_failed": 0,
            }

        total_triggered = 0
        total_notifications = 0
        failed_users = 0

        for user_id in user_ids:
            try:
                triggered, notifications = await _process_user(db, user_id)
            except Exception:
                # Isolate the blast radius: roll back only this user's
                # uncommitted work and keep going. Everything already
                # dispatched was committed before it was sent.
                failed_users += 1
                try:
                    await db.rollback()
                except Exception:
                    logger.exception(
                        "check_alerts_task: rollback failed for user %d", user_id
                    )
                logger.exception(
                    "check_alerts_task: alert evaluation failed for user %d "
                    "— continuing with the remaining users",
                    user_id,
                )
                continue
            total_triggered += triggered
            total_notifications += notifications

        logger.info(
            "check_alerts_task: users=%d, triggered=%d, notifications=%d, failed=%d",
            len(user_ids),
            total_triggered,
            total_notifications,
            failed_users,
        )

        return {
            "users_checked": len(user_ids),
            "alerts_triggered": total_triggered,
            "notifications_sent": total_notifications,
            "users_failed": failed_users,
        }


# ---------------------------------------------------------------------------
# Celery task wrapper (registered whenever Celery is importable)
# ---------------------------------------------------------------------------
# Register the task purely on Celery being importable: celery_app.py's
# beat_schedule always references this task name, so registration must not
# depend on any runtime state. The APScheduler-vs-Celery mode decision lives
# in scheduler.py and is driven by settings.use_celery.

if celery_app is not None:

    @celery_app.task(name="app.tasks.check_alerts.check_alerts_celery", bind=True)
    def check_alerts_celery(self) -> dict:  # type: ignore[misc]
        """Celery-compatible wrapper that runs the async task synchronously."""
        return run_async(check_alerts_task)
