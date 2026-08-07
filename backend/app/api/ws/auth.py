"""Shared WebSocket authentication.

Previously this logic was duplicated byte-for-byte as ``_authenticate`` /
``_authenticate_scoped`` in ``price_stream.py`` and ``alert_stream.py``; both
stream routers now import from here.
"""

from __future__ import annotations

from fastapi import WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import validate_pcat
from app.database import get_db
from app.models.user import User
from app.utils.security import decode_token


async def authenticate_token(token: str | None, db: AsyncSession) -> int | None:
    """Validate a JWT and confirm the user is still valid; return ``user_id``.

    Mirrors ``app.api.deps.get_current_user``: beyond checking the signature,
    type and ``sub``, it loads the user and rejects tokens for a missing or
    deactivated account, and honours password-change revocation via the ``pcat``
    claim (a token minted before the user's most recent password change is no
    longer accepted). Returns ``None`` on any failure so the caller closes 4001.
    """
    if not token:
        return None
    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        return None
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError, TypeError):
        return None

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None

    # Reject tokens minted before the user's most recent password change.
    if not validate_pcat(payload, user):
        return None

    return user_id


async def authenticate_ws(websocket: WebSocket, token: str | None) -> int | None:
    """Authenticate a WebSocket with a SHORT-LIVED DB session that is closed
    before this function returns — i.e. before the caller's receive loop
    starts.

    Holding a ``Depends(get_db)`` session for the entire connection lifetime
    kept an aiosqlite worker pinned while the socket blocked in
    ``receive_json`` — a deadlock surface (seen as a rare CI hang) and a
    wasted connection per socket. The dependency-overrides lookup keeps test
    ``get_db`` overrides working.
    """
    dep = websocket.app.dependency_overrides.get(get_db, get_db)
    agen = dep()
    try:
        db = await anext(agen)
        return await authenticate_token(token, db)
    finally:
        await agen.aclose()
