"""WebSocket endpoint for real-time stock price streaming."""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ws.connection_manager import manager
from app.database import get_db
from app.models.user import User
from app.utils.security import decode_token

logger = logging.getLogger(__name__)

router = APIRouter()


# ── helpers ───────────────────────────────────────────────────────────────────

async def _authenticate(token: str | None, db: AsyncSession) -> int | None:
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
    token_pcat_raw = payload.get("pcat", 0)
    try:
        token_pcat = int(token_pcat_raw)
    except (TypeError, ValueError):
        token_pcat = 0
    if user.password_changed_at is not None:
        current_pcat = int(user.password_changed_at.timestamp())
        if token_pcat < current_pcat:
            return None

    return user_id


async def _authenticate_scoped(websocket: WebSocket, token: str | None) -> int | None:
    """Authenticate with a SHORT-LIVED DB session that closes before the
    receive loop starts.

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
        return await _authenticate(token, db)
    finally:
        await agen.aclose()


# ── WebSocket route ───────────────────────────────────────────────────────────

@router.websocket("/ws/prices")
async def websocket_price_stream(
    websocket: WebSocket,
    token: str | None = None,
) -> None:
    """Stream real-time price updates to authenticated clients.

    **Query parameters**:
        ``token`` — JWT access token.

    **Client -> Server messages** (JSON):
        ``{"action": "subscribe", "symbols": ["RELIANCE", "TCS"]}``
        ``{"action": "unsubscribe", "symbols": ["TCS"]}``

    **Server -> Client messages** (JSON):
        ``{"type": "price_update", "symbol": "RELIANCE", "data": {...}}``
        ``{"type": "error", "message": "..."}``
    """
    # ── authenticate (short-lived DB session; closed before the loop) ──
    user_id = await _authenticate_scoped(websocket, token)
    if user_id is None:
        await websocket.close(code=4001, reason="Authentication failed")
        return

    # ── register connection ───────────────────────────────────────
    await manager.connect(websocket, user_id)

    try:
        while True:
            try:
                raw = await websocket.receive_json()
            except ValueError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            action: str | None = raw.get("action")
            symbols: list[str] | None = raw.get("symbols")

            if action == "subscribe" and isinstance(symbols, list):
                manager.subscribe(websocket, symbols)
                await websocket.send_json({
                    "type": "subscribed",
                    "symbols": sorted(
                        manager.get_subscriptions(websocket)
                    ),
                })

            elif action == "unsubscribe" and isinstance(symbols, list):
                manager.unsubscribe(websocket, symbols)
                await websocket.send_json({
                    "type": "unsubscribed",
                    "symbols": sorted(
                        manager.get_subscriptions(websocket)
                    ),
                })

            else:
                await websocket.send_json({
                    "type": "error",
                    "message": (
                        "Invalid message. Expected "
                        '{"action": "subscribe"|"unsubscribe", "symbols": [...]}'
                    ),
                })

    except WebSocketDisconnect:
        logger.info("Price stream client disconnected: user_id=%s", user_id)
    except Exception:
        logger.exception("Unexpected error in price stream for user_id=%s", user_id)
    finally:
        manager.disconnect(websocket)
