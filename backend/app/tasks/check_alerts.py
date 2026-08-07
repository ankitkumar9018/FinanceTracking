"""Background task: evaluate all active alerts and dispatch notifications."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.sql import func as sql_func

from app.api.ws.connection_manager import manager
from app.database import async_session_factory
from app.models.alert import Alert
from app.models.user import User
from app.services.alert_service import check_all_alerts_for_user
from app.services.notification_service import dispatch_notification
from app.tasks.celery_app import celery_app, run_async

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core async task
# ---------------------------------------------------------------------------


async def check_alerts_task() -> dict:
    """Check every active alert and dispatch notifications for triggered ones.

    Implements smart deduplication: alerts whose ``last_triggered`` timestamp
    falls within the cooldown window (5 minutes) are silently skipped.

    Returns
    -------
    dict
        Summary with keys ``users_checked``, ``alerts_triggered``, ``notifications_sent``.
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

            if not user_ids:
                logger.debug("check_alerts_task: no users with active alerts")
                return {
                    "users_checked": 0,
                    "alerts_triggered": 0,
                    "notifications_sent": 0,
                }

            total_triggered = 0
            total_notifications = 0
            now = datetime.now(UTC)

            for user_id in user_ids:
                # Load user for email/phone needed by notification channels
                user_obj = await db.get(User, user_id)
                user_email = user_obj.email if user_obj else None
                user_phone = getattr(user_obj, "phone", None) if user_obj else None
                user_telegram_chat_id = (
                    getattr(user_obj, "telegram_chat_id", None) if user_obj else None
                )

                triggered = await check_all_alerts_for_user(user_id, db)

                for alert_info in triggered:
                    # Cooldown already checked in alert_service.check_alerts_for_holding()
                    total_triggered += 1

                    # ── Dispatch notifications via configured channels ────
                    channels = alert_info.get("channels", ["in_app"])
                    message = alert_info.get("message", "Alert triggered")
                    subject = (
                        f"Alert: {alert_info.get('stock_symbol', 'N/A')} "
                        f"— {alert_info.get('alert_type', 'CUSTOM')}"
                    )

                    try:
                        results = await dispatch_notification(
                            channels=channels,
                            subject=subject,
                            body=message,
                            user_id=user_id,
                            db=db,
                            alert_id=alert_info.get("alert_id"),
                            user_email=user_email,
                            user_phone=user_phone,
                            telegram_chat_id=user_telegram_chat_id,
                        )
                        total_notifications += sum(
                            1 for ok in results.values() if ok
                        )
                    except Exception:
                        logger.exception(
                            "Notification dispatch failed for alert %s",
                            alert_info.get("alert_id"),
                        )

                    # ── Real-time WebSocket alert ─────────────────────────
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
                                        alert_info.get("triggered_at", now).isoformat()
                                    ),
                                },
                            },
                        )
                    except Exception:
                        logger.exception(
                            "WebSocket alert delivery failed for user %d", user_id
                        )

            await db.commit()

            logger.info(
                "check_alerts_task: users=%d, triggered=%d, notifications=%d",
                len(user_ids),
                total_triggered,
                total_notifications,
            )

            return {
                "users_checked": len(user_ids),
                "alerts_triggered": total_triggered,
                "notifications_sent": total_notifications,
            }
        except Exception:
            await db.rollback()
            logger.exception(
                "check_alerts_task: unhandled error during alert evaluation"
            )
            raise


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
