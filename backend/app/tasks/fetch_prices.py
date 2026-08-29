"""Background task: fetch and broadcast current prices for all holdings."""

from __future__ import annotations

import logging

from app.api.ws.connection_manager import manager
from app.database import async_session_factory
from app.services.market_data_service import (
    refresh_all_prices,
    refresh_watchlist_prices,
)
from app.tasks.celery_app import celery_app, run_async

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core async task
# ---------------------------------------------------------------------------


async def _broadcast_updates(updates: list[dict]) -> int:
    """Push one ``price_update`` message per refreshed symbol.

    Broadcasting is best effort: the DB write has already been committed by the
    time this runs, so a WebSocket failure must never fail (or roll back) the
    refresh. Each symbol is sent at most once — a symbol that is both held and
    watchlisted would otherwise be delivered twice.
    """
    sent = 0
    seen: set[str] = set()
    for update in updates:
        symbol = update.get("symbol")
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        try:
            await manager.broadcast_price_update(symbol, update)
            sent += 1
        except Exception:
            logger.warning(
                "fetch_prices_task: price_update broadcast failed for %s",
                symbol,
                exc_info=True,
            )
    return sent


async def fetch_prices_task() -> dict:
    """Fetch current prices for every holding and broadcast updates via WebSocket.

    Creates its own database session so it can be called from any context
    (APScheduler job, Celery worker, or manually).

    Returns
    -------
    dict
        Summary with keys ``updated``, ``failed``, ``total`` (holdings) plus
        ``watchlist`` (the same counts for watchlist items) and ``broadcast``
        (how many per-symbol WebSocket messages were pushed).
    """
    logger.info("fetch_prices_task: starting price refresh")

    async with async_session_factory() as db:
        try:
            summary = await refresh_all_prices(db)
            # Watchlist items carry their own price/RSI/action columns and are
            # what watchlist alerts evaluate against; without this pass they
            # stayed permanently NULL and those alerts could never fire.
            watchlist_summary = await refresh_watchlist_prices(db)
            await db.commit()

            logger.info(
                "fetch_prices_task: updated=%d, failed=%d, total=%d "
                "(watchlist updated=%d, failed=%d, total=%d)",
                summary["updated"],
                summary["failed"],
                summary["total"],
                watchlist_summary["updated"],
                watchlist_summary["failed"],
                watchlist_summary["total"],
            )

            # Per-symbol updates: the only thing that actually moves the numbers
            # on an open page. Sent AFTER the commit so a client that reacts by
            # re-fetching always sees the committed values.
            sent = await _broadcast_updates(
                list(summary.get("updates", []))
                + list(watchlist_summary.get("updates", []))
            )

            result = {
                "updated": summary["updated"],
                "failed": summary["failed"],
                "total": summary["total"],
                "watchlist": {
                    "updated": watchlist_summary["updated"],
                    "failed": watchlist_summary["failed"],
                    "total": watchlist_summary["total"],
                },
                "broadcast": sent,
            }

            # Coarse "something changed" event, kept as a fallback for clients
            # that are not subscribed to individual symbols. Counts only — the
            # per-holding payloads go out via broadcast_price_update above.
            try:
                await manager.broadcast_all(
                    {
                        "type": "prices_refreshed",
                        "data": result,
                    }
                )
            except Exception:
                logger.warning(
                    "fetch_prices_task: prices_refreshed broadcast failed",
                    exc_info=True,
                )

            return result
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
