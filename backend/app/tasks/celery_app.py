"""Celery application configuration with Redis as broker.

Celery is an *opt-in* execution mode:

- It runs ONLY when ``settings.use_celery`` (env ``USE_CELERY``) is True AND
  the ``celery`` package is importable — see ``scheduler.py``. A merely
  reachable Redis is NOT evidence that a worker/beat process exists (any other
  local project's Redis used to disable APScheduler while nothing consumed the
  queue, so prices/alerts silently never refreshed).
- **Known limitation:** in Celery mode the WebSocket broadcasts inside
  ``fetch_prices_task`` / ``check_alerts_task`` execute in the *worker*
  process, whose ``ConnectionManager`` holds no client sockets — so real-time
  WS pushes are NOT delivered to connected browsers. With ``use_celery``
  defaulting to False, every standard deployment (desktop sidecar, run.sh,
  uvicorn) gets the in-process APScheduler path where broadcasts work.

This module also owns the single ``JOBS`` spec consumed by BOTH the
APScheduler registrar (``scheduler.py``) and the Celery beat schedule, plus
the shared ``run_async`` bridge used by the Celery task wrappers.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

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
# Job specs — single source of truth for the periodic background jobs.
# Consumed by both the APScheduler registrar (scheduler.py) and the Celery
# beat schedule below, so the two modes can never drift apart.
# ---------------------------------------------------------------------------


def _fetch_prices_coro() -> Coroutine[Any, Any, dict]:
    # Lazy import: fetch_prices imports this module for celery_app/run_async.
    from app.tasks.fetch_prices import fetch_prices_task

    return fetch_prices_task()


def _check_alerts_coro() -> Coroutine[Any, Any, dict]:
    from app.tasks.check_alerts import check_alerts_task

    return check_alerts_task()


def _ai_digest_coro() -> Coroutine[Any, Any, dict]:
    from app.tasks.ai_digest_task import run_scheduled_digests

    return run_scheduled_digests()


@dataclass(frozen=True)
class JobSpec:
    """One periodic background job, mode-agnostic."""

    id: str
    name: str
    celery_task: str  # dotted Celery task name
    interval_seconds: Callable[[], int]  # read settings at schedule time
    coro_factory: Callable[[], Coroutine[Any, Any, dict]]


JOBS: tuple[JobSpec, ...] = (
    JobSpec(
        id="fetch_prices_job",
        name="Fetch prices for all holdings",
        celery_task="app.tasks.fetch_prices.fetch_prices_celery",
        interval_seconds=lambda: settings.price_refresh_interval * 60,
        coro_factory=_fetch_prices_coro,
    ),
    JobSpec(
        id="check_alerts_job",
        name="Check all active alerts",
        celery_task="app.tasks.check_alerts.check_alerts_celery",
        interval_seconds=lambda: settings.alert_check_interval,
        coro_factory=_check_alerts_coro,
    ),
    JobSpec(
        id="ai_digest_job",
        name="Generate scheduled AI portfolio digests",
        celery_task="app.tasks.ai_digest_task.run_scheduled_digests_celery",
        # Daily cadence; the task itself decides per user (daily vs weekly on
        # Monday vs off) from each user's stored digest frequency.
        interval_seconds=lambda: 24 * 60 * 60,
        coro_factory=_ai_digest_coro,
    ),
)


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

    # -- Beat schedule (periodic tasks) — derived from the shared JOBS spec.
    celery_app.conf.beat_schedule = {
        job.id: {
            "task": job.celery_task,
            "schedule": job.interval_seconds(),
        }
        for job in JOBS
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
# Public helpers
# ---------------------------------------------------------------------------


def run_async[T](coro_factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """Run an async task to completion from a synchronous (Celery) context.

    Shared by the Celery task wrappers in ``fetch_prices.py`` /
    ``check_alerts.py`` (which used to duplicate this 16-line dance). Takes a
    coroutine *factory* so the coroutine is created inside whichever event
    loop actually runs it.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Inside an already-running loop (unlikely in a Celery worker,
            # but handle defensively via a new thread)
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro_factory())
                return future.result()
        return loop.run_until_complete(coro_factory())
    except RuntimeError:
        # No current event loop — create a fresh one
        return asyncio.run(coro_factory())


def is_celery_available() -> bool:
    """Diagnostic: is Celery importable AND its Redis broker answering a ping?

    This is intentionally NOT used to decide the scheduling mode anymore —
    a pingable Redis says nothing about a worker/beat actually running (any
    other local project's Redis satisfied it, which silently disabled the
    APScheduler while nobody consumed the queue). The mode decision lives in
    ``scheduler.py`` and is driven by ``settings.use_celery``.

    Note: this pings Redis synchronously (blocking). It is only called from
    sync contexts; if it ever ends up on an async path, wrap the call in
    ``asyncio.to_thread``.
    """
    if not (_HAS_CELERY and celery_app is not None):
        return False
    try:
        import redis

        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        client.ping()
        return True
    except Exception:
        logger.info(
            "Celery installed but broker unreachable at %s",
            settings.redis_url,
        )
        return False
