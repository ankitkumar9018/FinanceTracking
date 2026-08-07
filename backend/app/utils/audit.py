"""Lightweight audit logging for sensitive actions."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("audit")


async def audit_log(
    db: AsyncSession,
    *,
    user_id: int,
    action: str,
    resource_type: str,
    resource_id: int | str | None = None,
    details: str | None = None,
    ip_address: str | None = None,
) -> None:
    """Record an auditable action.

    Current implementation logs a structured entry to Python's logging system
    (the ``audit`` logger) ONLY — nothing is persisted to the database. The
    ``db`` session parameter is accepted (and passed by all callers) so a
    future dedicated audit_log table can be adopted without changing call
    sites, but it is intentionally unused today.
    """
    timestamp = datetime.now(UTC).isoformat()
    log_entry = (
        f"[AUDIT] user={user_id} action={action} "
        f"resource={resource_type}:{resource_id} "
        f"ip={ip_address} details={details} ts={timestamp}"
    )
    logger.info(log_entry)
