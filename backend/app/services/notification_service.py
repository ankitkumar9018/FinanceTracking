"""Notification service: multi-channel dispatch (email, Telegram, WhatsApp, SMS, in-app)."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.notification_log import NotificationLog

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional third-party imports — graceful degradation if not installed
# ---------------------------------------------------------------------------

try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail

    _HAS_SENDGRID = True
except ImportError:  # pragma: no cover
    _HAS_SENDGRID = False

try:
    import httpx

    _HAS_HTTPX = True
except ImportError:  # pragma: no cover
    _HAS_HTTPX = False

try:
    from twilio.rest import Client as TwilioClient

    _HAS_TWILIO = True
except ImportError:  # pragma: no cover
    _HAS_TWILIO = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _log_notification(
    *,
    db: AsyncSession,
    user_id: int,
    channel: str,
    subject: str | None,
    body: str,
    status: str,
    alert_id: int | None,
    sent_at: datetime | None,
) -> NotificationLog:
    """Persist a notification log entry and flush it to the session."""
    entry = NotificationLog(
        user_id=user_id,
        channel=channel,
        subject=subject,
        body=body,
        status=status,
        related_alert_id=alert_id,
        sent_at=sent_at,
    )
    db.add(entry)
    await db.flush()
    return entry


# ---------------------------------------------------------------------------
# Email (SendGrid)
# ---------------------------------------------------------------------------


async def send_email(
    to_email: str,
    subject: str,
    body: str,
    user_id: int,
    db: AsyncSession,
    alert_id: int | None = None,
) -> bool:
    """Send an email via SendGrid and log the result."""
    if not _HAS_SENDGRID:
        logger.warning("sendgrid package not installed — skipping email")
        await _log_notification(
            db=db, user_id=user_id, channel="email", subject=subject,
            body=body, status="FAILED", alert_id=alert_id, sent_at=None,
        )
        return False

    if not settings.sendgrid_api_key or not settings.email_from:
        logger.warning("SendGrid not configured — skipping email")
        await _log_notification(
            db=db, user_id=user_id, channel="email", subject=subject,
            body=body, status="FAILED", alert_id=alert_id, sent_at=None,
        )
        return False

    try:
        message = Mail(
            from_email=settings.email_from,
            to_emails=to_email,
            subject=subject,
            html_content=body,
        )
        sg = SendGridAPIClient(settings.sendgrid_api_key)
        await asyncio.to_thread(sg.send, message)

        now = datetime.now(UTC)
        await _log_notification(
            db=db, user_id=user_id, channel="email", subject=subject,
            body=body, status="SENT", alert_id=alert_id, sent_at=now,
        )
        logger.info("Email sent to %s", to_email)
        return True
    except Exception:
        logger.exception("Failed to send email to %s", to_email)
        await _log_notification(
            db=db, user_id=user_id, channel="email", subject=subject,
            body=body, status="FAILED", alert_id=alert_id, sent_at=None,
        )
        return False


# ---------------------------------------------------------------------------
# Telegram (Bot API via httpx)
# ---------------------------------------------------------------------------


async def send_telegram(
    message: str,
    user_id: int,
    db: AsyncSession,
    alert_id: int | None = None,
    chat_id: str | None = None,
) -> bool:
    """Send a Telegram message via the Bot API."""
    if not _HAS_HTTPX:
        logger.warning("httpx package not installed — skipping Telegram")
        await _log_notification(
            db=db, user_id=user_id, channel="telegram", subject=None,
            body=message, status="FAILED", alert_id=alert_id, sent_at=None,
        )
        return False

    token = settings.telegram_bot_token
    target_chat = chat_id or settings.telegram_chat_id
    if not token or not target_chat:
        logger.warning("Telegram not configured — skipping")
        await _log_notification(
            db=db, user_id=user_id, channel="telegram", subject=None,
            body=message, status="FAILED", alert_id=alert_id, sent_at=None,
        )
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": target_chat, "text": message, "parse_mode": "HTML"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()

        now = datetime.now(UTC)
        await _log_notification(
            db=db, user_id=user_id, channel="telegram", subject=None,
            body=message, status="SENT", alert_id=alert_id, sent_at=now,
        )
        logger.info("Telegram message sent to chat %s", target_chat)
        return True
    except Exception as exc:
        # Use warning (not exception) to avoid leaking the bot token from the URL
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        logger.warning(
            "Failed to send Telegram message: %s (status=%s)",
            type(exc).__name__,
            status_code,
        )
        await _log_notification(
            db=db, user_id=user_id, channel="telegram", subject=None,
            body=message, status="FAILED", alert_id=alert_id, sent_at=None,
        )
        return False


# ---------------------------------------------------------------------------
# WhatsApp (Twilio)
# ---------------------------------------------------------------------------


async def send_whatsapp(
    to_number: str,
    message: str,
    user_id: int,
    db: AsyncSession,
    alert_id: int | None = None,
) -> bool:
    """Send a WhatsApp message via Twilio."""
    if not _HAS_TWILIO:
        logger.warning("twilio package not installed — skipping WhatsApp")
        await _log_notification(
            db=db, user_id=user_id, channel="whatsapp", subject=None,
            body=message, status="FAILED", alert_id=alert_id, sent_at=None,
        )
        return False

    sid = settings.twilio_account_sid
    token = settings.twilio_auth_token
    from_number = settings.twilio_whatsapp_from
    if not sid or not token or not from_number:
        logger.warning("Twilio WhatsApp not configured — skipping")
        await _log_notification(
            db=db, user_id=user_id, channel="whatsapp", subject=None,
            body=message, status="FAILED", alert_id=alert_id, sent_at=None,
        )
        return False

    try:
        client = TwilioClient(sid, token)
        await asyncio.to_thread(
            client.messages.create,
            body=message,
            from_=f"whatsapp:{from_number}",
            to=f"whatsapp:{to_number}",
        )

        now = datetime.now(UTC)
        await _log_notification(
            db=db, user_id=user_id, channel="whatsapp", subject=None,
            body=message, status="SENT", alert_id=alert_id, sent_at=now,
        )
        logger.info("WhatsApp message sent to %s", to_number)
        return True
    except Exception:
        logger.exception("Failed to send WhatsApp message to %s", to_number)
        await _log_notification(
            db=db, user_id=user_id, channel="whatsapp", subject=None,
            body=message, status="FAILED", alert_id=alert_id, sent_at=None,
        )
        return False


# ---------------------------------------------------------------------------
# SMS (Twilio)
# ---------------------------------------------------------------------------


async def send_sms(
    to_number: str,
    message: str,
    user_id: int,
    db: AsyncSession,
    alert_id: int | None = None,
) -> bool:
    """Send an SMS via Twilio."""
    if not _HAS_TWILIO:
        logger.warning("twilio package not installed — skipping SMS")
        await _log_notification(
            db=db, user_id=user_id, channel="sms", subject=None,
            body=message, status="FAILED", alert_id=alert_id, sent_at=None,
        )
        return False

    sid = settings.twilio_account_sid
    token = settings.twilio_auth_token
    from_number = settings.twilio_sms_from
    if not sid or not token or not from_number:
        logger.warning("Twilio SMS not configured — skipping")
        await _log_notification(
            db=db, user_id=user_id, channel="sms", subject=None,
            body=message, status="FAILED", alert_id=alert_id, sent_at=None,
        )
        return False

    try:
        client = TwilioClient(sid, token)
        await asyncio.to_thread(
            client.messages.create,
            body=message,
            from_=from_number,
            to=to_number,
        )

        now = datetime.now(UTC)
        await _log_notification(
            db=db, user_id=user_id, channel="sms", subject=None,
            body=message, status="SENT", alert_id=alert_id, sent_at=now,
        )
        logger.info("SMS sent to %s", to_number)
        return True
    except Exception:
        logger.exception("Failed to send SMS to %s", to_number)
        await _log_notification(
            db=db, user_id=user_id, channel="sms", subject=None,
            body=message, status="FAILED", alert_id=alert_id, sent_at=None,
        )
        return False


# ---------------------------------------------------------------------------
# In-App notification (DB only)
# ---------------------------------------------------------------------------


async def store_in_app_notification(
    subject: str,
    body: str,
    user_id: int,
    db: AsyncSession,
    alert_id: int | None = None,
) -> bool:
    """Store a notification in the database for in-app display."""
    try:
        now = datetime.now(UTC)
        await _log_notification(
            db=db, user_id=user_id, channel="in_app", subject=subject,
            body=body, status="SENT", alert_id=alert_id, sent_at=now,
        )
        logger.info("In-app notification stored for user %d", user_id)
        return True
    except Exception:
        logger.exception("Failed to store in-app notification for user %d", user_id)
        return False


# ---------------------------------------------------------------------------
# Multi-channel dispatcher
# ---------------------------------------------------------------------------


async def dispatch_notification(
    channels: list[str],
    subject: str,
    body: str,
    user_id: int,
    db: AsyncSession,
    alert_id: int | None = None,
    user_email: str | None = None,
    user_phone: str | None = None,
    telegram_chat_id: str | None = None,
) -> dict[str, bool]:
    """Dispatch a notification across multiple channels.

    Returns a mapping of channel name to success boolean.
    """
    results: dict[str, bool] = {}

    for channel in channels:
        ch = channel.lower().strip()

        if ch == "email":
            if not user_email:
                logger.warning("No email address provided — skipping email channel")
                results["email"] = False
                continue
            results["email"] = await send_email(
                to_email=user_email, subject=subject, body=body,
                user_id=user_id, db=db, alert_id=alert_id,
            )

        elif ch == "telegram":
            results["telegram"] = await send_telegram(
                message=body, user_id=user_id, db=db,
                alert_id=alert_id, chat_id=telegram_chat_id,
            )

        elif ch == "whatsapp":
            if not user_phone:
                logger.warning("No phone number provided — skipping WhatsApp channel")
                results["whatsapp"] = False
                continue
            results["whatsapp"] = await send_whatsapp(
                to_number=user_phone, message=body,
                user_id=user_id, db=db, alert_id=alert_id,
            )

        elif ch == "sms":
            if not user_phone:
                logger.warning("No phone number provided — skipping SMS channel")
                results["sms"] = False
                continue
            results["sms"] = await send_sms(
                to_number=user_phone, message=body,
                user_id=user_id, db=db, alert_id=alert_id,
            )

        elif ch == "in_app":
            results["in_app"] = await store_in_app_notification(
                subject=subject, body=body,
                user_id=user_id, db=db, alert_id=alert_id,
            )

        else:
            logger.warning("Unknown notification channel: %s", ch)
            results[ch] = False

    return results
