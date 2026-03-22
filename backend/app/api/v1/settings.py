"""Application settings endpoints.

Module named ``settings.py`` in the route layer; the router import in
``router.py`` uses ``from app.api.v1 import settings as settings_routes``
to avoid any collision with the stdlib ``settings`` or the config module.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings as app_settings
from app.database import get_db
from app.models.user import User
from app.schemas.settings import HealthStatus, SettingsUpdate

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# GET / — current user settings (grouped)
# ---------------------------------------------------------------------------

@router.get("/")
async def get_settings(
    user: User = Depends(get_current_user),
) -> dict:
    """Return all settings for the current user, grouped by category."""
    notif_prefs = user.notification_preferences or {}

    return {
        "display": {
            "preferred_currency": user.preferred_currency,
            "theme_preference": user.theme_preference,
            "display_name": user.display_name,
        },
        "notifications": {
            "email_enabled": notif_prefs.get("email_enabled", False),
            "telegram_enabled": notif_prefs.get("telegram_enabled", False),
            "whatsapp_enabled": notif_prefs.get("whatsapp_enabled", False),
            "in_app_enabled": notif_prefs.get("in_app_enabled", True),
            "alert_check_interval": notif_prefs.get(
                "alert_check_interval", app_settings.alert_check_interval
            ),
        },
        "market": {
            "price_refresh_interval": app_settings.price_refresh_interval,
            "default_chart_days": app_settings.default_chart_days,
        },
        "integrations": {
            "llm_provider": app_settings.llm_provider,
            "ollama_url": app_settings.ollama_url,
            "ollama_model": app_settings.ollama_model,
            "has_sendgrid_key": bool(app_settings.sendgrid_api_key),
            "has_telegram_bot": bool(app_settings.telegram_bot_token),
        },
    }


# ---------------------------------------------------------------------------
# PUT / — update settings
# ---------------------------------------------------------------------------

@router.put("/")
async def update_settings(
    body: SettingsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update user-level settings (display, notifications)."""
    update_data = body.model_dump(exclude_unset=True)

    if "preferred_currency" in update_data:
        user.preferred_currency = update_data["preferred_currency"]

    if "theme_preference" in update_data:
        valid_themes = {"dark", "light", "system"}
        if update_data["theme_preference"] not in valid_themes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid theme. Valid: {sorted(valid_themes)}",
            )
        user.theme_preference = update_data["theme_preference"]

    if "display_name" in update_data:
        user.display_name = update_data["display_name"]

    if "notification_preferences" in update_data:
        # Merge with existing preferences
        existing = user.notification_preferences or {}
        existing.update(update_data["notification_preferences"])
        user.notification_preferences = existing

    await db.flush()
    await db.refresh(user)

    return {"status": "updated"}


# ---------------------------------------------------------------------------
# POST /test/email — send test email
# ---------------------------------------------------------------------------

@router.post("/test/email")
async def test_email(
    user: User = Depends(get_current_user),
) -> dict:
    """Send a test email to the current user's email address."""
    if not app_settings.sendgrid_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SendGrid API key not configured",
        )

    try:
        import sendgrid
        from sendgrid.helpers.mail import Content, Email, Mail, To

        sg = sendgrid.SendGridAPIClient(api_key=app_settings.sendgrid_api_key)
        from_email = Email(app_settings.email_from or "noreply@financetracker.local")
        to_email = To(user.email)
        subject = "FinanceTracker — Test Email"
        content = Content(
            "text/plain",
            f"Hello {user.display_name or user.email},\n\n"
            "This is a test email from your FinanceTracker instance.\n"
            "If you received this, email notifications are working correctly.\n\n"
            "— FinanceTracker",
        )
        mail = Mail(from_email, to_email, subject, content)
        response = sg.client.mail.send.post(request_body=mail.get())

        return {
            "status": "sent",
            "to": user.email,
            "sendgrid_status_code": response.status_code,
        }
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="sendgrid package not installed",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to send test email: {exc}",
        )


# ---------------------------------------------------------------------------
# POST /test/telegram — send test telegram message
# ---------------------------------------------------------------------------

@router.post("/test/telegram")
async def test_telegram(
    user: User = Depends(get_current_user),
) -> dict:
    """Send a test message via Telegram bot."""
    if not app_settings.telegram_bot_token or not app_settings.telegram_chat_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram bot token or chat ID not configured",
        )

    try:
        import httpx

        url = (
            f"https://api.telegram.org/bot{app_settings.telegram_bot_token}"
            f"/sendMessage"
        )
        payload = {
            "chat_id": app_settings.telegram_chat_id,
            "text": (
                f"FinanceTracker Test\n\n"
                f"Hello {user.display_name or user.email}!\n"
                f"Telegram notifications are working correctly."
            ),
            "parse_mode": "HTML",
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()

        return {
            "status": "sent",
            "chat_id": app_settings.telegram_chat_id,
        }
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="httpx package not installed",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to send Telegram message: {exc}",
        )


# ---------------------------------------------------------------------------
# POST /test/llm — test LLM connection
# ---------------------------------------------------------------------------

@router.post("/test/llm")
async def test_llm(
    user: User = Depends(get_current_user),
) -> dict:
    """Test the configured LLM connection (Ollama, OpenAI, etc.)."""
    provider = app_settings.llm_provider

    if provider == "none":
        return {"status": "disabled", "provider": "none"}

    if provider == "ollama":
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                # Check if Ollama is running
                resp = await client.get(f"{app_settings.ollama_url}/api/tags")
                resp.raise_for_status()
                tags = resp.json()
                models = [m["name"] for m in tags.get("models", [])]

                # Check if the configured model is available
                model_available = any(
                    app_settings.ollama_model in m for m in models
                )

                return {
                    "status": "connected",
                    "provider": "ollama",
                    "url": app_settings.ollama_url,
                    "model": app_settings.ollama_model,
                    "model_available": model_available,
                    "available_models": models,
                }
        except ImportError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="httpx package not installed",
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Ollama connection failed: {exc}",
            )

    elif provider == "openai":
        if not app_settings.openai_api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OpenAI API key not configured",
            )
        return {
            "status": "configured",
            "provider": "openai",
            "model": app_settings.openai_model,
        }

    elif provider == "anthropic":
        if not app_settings.anthropic_api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Anthropic API key not configured",
            )
        return {
            "status": "configured",
            "provider": "anthropic",
        }

    elif provider == "google":
        if not app_settings.google_api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Google API key not configured",
            )
        return {
            "status": "configured",
            "provider": "google",
        }

    return {"status": "unknown", "provider": provider}


# ---------------------------------------------------------------------------
# GET /health — service health status
# ---------------------------------------------------------------------------

@router.get("/health", response_model=HealthStatus)
async def health_check(
    user: User = Depends(get_current_user),
) -> dict:
    """Check the health of all dependent services: database, Redis, Ollama, broker."""
    statuses: dict[str, str] = {}

    # Database — if we got this far, DB is working
    statuses["database"] = "healthy"

    # Redis
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(app_settings.redis_url, decode_responses=True)
        await r.ping()
        await r.aclose()
        statuses["redis"] = "healthy"
    except Exception:
        statuses["redis"] = "unavailable"

    # Ollama / LLM
    if app_settings.llm_provider == "ollama":
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{app_settings.ollama_url}/api/tags")
                resp.raise_for_status()
                statuses["ollama"] = "healthy"
        except Exception:
            statuses["ollama"] = "unavailable"
    elif app_settings.llm_provider == "none":
        statuses["ollama"] = "disabled"
    else:
        statuses["ollama"] = f"using_{app_settings.llm_provider}"

    # Broker
    broker_configured = bool(
        app_settings.zerodha_api_key
        or app_settings.icici_app_key
    )
    statuses["broker"] = "configured" if broker_configured else "not_configured"

    # Overall
    critical = [statuses["database"]]
    statuses["overall"] = (
        "healthy" if all(s == "healthy" for s in critical) else "degraded"
    )

    return statuses
