"""Celery application configuration with Redis as broker.

Celery is an optional dependency. When not installed (or Redis is unavailable),
the application falls back to APScheduler (see ``scheduler.py``).
"""

from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional Celery import
# ---------------------------------------------------------------------------

try:
    from celery import Celery
    from celery.schedules import crontab  # noqa: F401 — re-exported for convenience

    _HAS_CELERY = True
except ImportError:
    _HAS_CELERY = False

# ---------------------------------------------------------------------------
# Celery app instance
# ---------------------------------------------------------------------------

celery_app: Celery | None = None

if _HAS_CELERY:
    celery_app = Celery("financetracker")

    celery_app.conf.update(
        broker_url=settings.redis_url,
        result_backend=settings.redis_url,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        # Avoid prefetching many tasks at once for a lightweight app
        worker_prefetch_multiplier=1,
    )

    # -- Beat schedule (periodic tasks) ------------------------------------
    celery_app.conf.beat_schedule = {
        "fetch-prices": {
            "task": "app.tasks.fetch_prices.fetch_prices_celery",
            "schedule": settings.price_refresh_interval * 60,  # seconds
        },
        "check-alerts": {
            "task": "app.tasks.check_alerts.check_alerts_celery",
            "schedule": settings.alert_check_interval,  # already in seconds
        },
    }

    # Auto-discover task modules inside the tasks package
    celery_app.autodiscover_tasks(["app.tasks"])

    logger.info(
        "Celery configured: broker=%s, price_interval=%dm, alert_interval=%ds",
        settings.redis_url,
        settings.price_refresh_interval,
        settings.alert_check_interval,
    )
else:
    logger.info("Celery not installed — background tasks will use APScheduler fallback")


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------


def is_celery_available() -> bool:
    """Return ``True`` if the Celery library is installed and the app is configured."""
    return _HAS_CELERY and celery_app is not None
