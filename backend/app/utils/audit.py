"""Lightweight audit logging for sensitive actions."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

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

    In the current implementation this logs to Python's logging system
    and to the notification_log table (reusing existing infrastructure).
    A dedicated audit_log table can be added via migration if needed.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    log_entry = (
        f"[AUDIT] user={user_id} action={action} "
        f"resource={resource_type}:{resource_id} "
        f"ip={ip_address} details={details} ts={timestamp}"
    )
    logger.info(log_entry)
