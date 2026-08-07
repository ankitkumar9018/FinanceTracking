"""APScheduler runner for background tasks (the default execution mode).

Uses ``AsyncIOScheduler`` from APScheduler (``apscheduler>=3.10.4``) to run
periodic jobs directly inside the FastAPI event loop.

Mode selection: Celery is used ONLY when ``settings.use_celery`` (env
``USE_CELERY``) is True AND the ``celery`` package is importable. The old
heuristic — "Redis answers a ping, therefore Celery must be running" — was
wrong: any local Redis (from an unrelated project) disabled the APScheduler
while no worker existed, so prices and alerts silently never refreshed.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.tasks.celery_app import JOBS, JobSpec, celery_app

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level scheduler instance
# ---------------------------------------------------------------------------

_scheduler: AsyncIOScheduler | None = None


# ---------------------------------------------------------------------------
# Mode decision
# ---------------------------------------------------------------------------


def _celery_mode() -> bool:
    """True only when Celery mode is explicitly enabled AND usable."""
    if not settings.use_celery:
        return False
    if celery_app is None:
        logger.warning(
            "USE_CELERY=true but the celery package is not installed — "
            "falling back to APScheduler"
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Job wrappers
# ---------------------------------------------------------------------------


def _make_job(spec: JobSpec):
    """Build the async APScheduler callable for a shared JobSpec."""

    async def _job() -> None:
        try:
            await spec.coro_factory()
        except Exception:
            logger.exception("Scheduled job %s failed", spec.id)

    _job.__name__ = spec.id
    return _job


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def start_scheduler() -> None:
    """Start the APScheduler unless Celery mode is explicitly enabled.

    Safe to call multiple times; subsequent calls are no-ops if the scheduler
    is already running.
    """
    global _scheduler

    if _celery_mode():
        logger.info(
            "USE_CELERY=true — expecting an external Celery worker/beat; "
            "APScheduler will not be started (note: WS pushes are not "
            "delivered in Celery mode, see tasks/celery_app.py)"
        )
        return

    if _scheduler is not None and _scheduler.running:
        logger.debug("APScheduler is already running")
        return

    _scheduler = AsyncIOScheduler(timezone="UTC")

    # Register every job from the shared JOBS spec (same source the Celery
    # beat schedule is generated from, so the two modes cannot drift).
    for spec in JOBS:
        _scheduler.add_job(
            _make_job(spec),
            trigger="interval",
            seconds=spec.interval_seconds(),
            id=spec.id,
            name=spec.name,
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
