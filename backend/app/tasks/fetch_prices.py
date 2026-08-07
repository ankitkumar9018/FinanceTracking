"""Background task: fetch and broadcast current prices for all holdings."""

from __future__ import annotations

import logging

from app.api.ws.connection_manager import manager
from app.database import async_session_factory
from app.services.market_data_service import refresh_all_prices
from app.tasks.celery_app import celery_app, run_async

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core async task
# ---------------------------------------------------------------------------


async def fetch_prices_task() -> dict:
    """Fetch current prices for every holding and broadcast updates via WebSocket.

    Creates its own database session so it can be called from any context
    (APScheduler job, Celery worker, or manually).

    Returns
    -------
    dict
        Summary with keys ``updated``, ``failed``, ``total``.
    """
    logger.info("fetch_prices_task: starting price refresh")

    async with async_session_factory() as db:
        try:
            summary = await refresh_all_prices(db)
            await db.commit()

            logger.info(
                "fetch_prices_task: updated=%d, failed=%d, total=%d",
                summary["updated"],
                summary["failed"],
                summary["total"],
            )

            # Broadcast a generic "prices refreshed" event to all connected clients
            await manager.broadcast_all(
                {
                    "type": "prices_refreshed",
                    "data": summary,
                }
            )

            return summary
        except Exception:
            await db.rollback()
            logger.exception("fetch_prices_task: unhandled error during price refresh")
            raise


# ---------------------------------------------------------------------------
# Celery task wrapper (registered whenever Celery is importable)
# ---------------------------------------------------------------------------
# Register the task purely on Celery being importable: celery_app.py's
# beat_schedule always references this task name, so registration must not
# depend on any runtime state. The APScheduler-vs-Celery mode decision lives
# in scheduler.py and is driven by settings.use_celery.

if celery_app is not None:

    @celery_app.task(name="app.tasks.fetch_prices.fetch_prices_celery", bind=True)
    def fetch_prices_celery(self) -> dict:  # type: ignore[misc]
        """Celery-compatible wrapper that runs the async task synchronously."""
        return run_async(fetch_prices_task)
