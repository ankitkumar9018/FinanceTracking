"""APScheduler fallback for background tasks when Celery/Redis is not available.

Uses ``AsyncIOScheduler`` from APScheduler (``apscheduler>=3.10.4``) to run
periodic jobs directly inside the FastAPI event loop.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.tasks.celery_app import is_celery_available

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level scheduler instance
# ---------------------------------------------------------------------------

_scheduler: AsyncIOScheduler | None = None


# ---------------------------------------------------------------------------
# Job wrappers
# ---------------------------------------------------------------------------


async def _fetch_prices_job() -> None:
    """Periodic job: refresh prices for all holdings."""
    from app.tasks.fetch_prices import fetch_prices_task

    try:
        await fetch_prices_task()
    except Exception:
        logger.exception("Scheduled fetch_prices_job failed")


async def _check_alerts_job() -> None:
    """Periodic job: evaluate all active alerts."""
    from app.tasks.check_alerts import check_alerts_task

    try:
        await check_alerts_task()
    except Exception:
        logger.exception("Scheduled check_alerts_job failed")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def start_scheduler() -> None:
    """Start the APScheduler if Celery is **not** available.

    Safe to call multiple times; subsequent calls are no-ops if the scheduler
    is already running.
    """
    global _scheduler

    if is_celery_available():
        logger.info("Celery is available — APScheduler will not be started")
        return

    if _scheduler is not None and _scheduler.running:
        logger.debug("APScheduler is already running")
        return

    _scheduler = AsyncIOScheduler(timezone="UTC")

    # Fetch prices every N minutes
    _scheduler.add_job(
        _fetch_prices_job,
        trigger="interval",
        minutes=settings.price_refresh_interval,
        id="fetch_prices_job",
        name="Fetch prices for all holdings",
        replace_existing=True,
    )

    # Check alerts every N seconds
    _scheduler.add_job(
        _check_alerts_job,
        trigger="interval",
        seconds=settings.alert_check_interval,
        id="check_alerts_job",
        name="Check all active alerts",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info(
        "APScheduler started: price_interval=%dm, alert_interval=%ds",
        settings.price_refresh_interval,
        settings.alert_check_interval,
    )


def stop_scheduler() -> None:
    """Gracefully shut down the APScheduler (if running)."""
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("APScheduler shut down")
    _scheduler = None


def get_scheduler() -> AsyncIOScheduler | None:
    """Return the current scheduler instance, or ``None`` if not started."""
    return _scheduler
