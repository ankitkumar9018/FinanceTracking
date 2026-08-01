"""WebSocket endpoint for real-time alert notifications."""

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
    receive loop starts (see price_stream._authenticate_scoped — holding a
    connection-lifetime session was a deadlock surface and a wasted
    connection per socket). Override-aware for tests.
    """
    dep = websocket.app.dependency_overrides.get(get_db, get_db)
    agen = dep()
    try:
        db = await anext(agen)
        return await _authenticate(token, db)
    finally:
        await agen.aclose()


# ── WebSocket route ───────────────────────────────────────────────────────────

@router.websocket("/ws/alerts")
async def websocket_alert_stream(
    websocket: WebSocket,
    token: str | None = None,
) -> None:
    """Push real-time alert notifications to authenticated clients.

    **Query parameters**:
        ``token`` — JWT access token.

    **Server -> Client messages** (JSON):
        ``{"type": "alert", "alert_id": 1, "alert_type": "PRICE_RANGE",
          "message": "...", "stock_symbol": "TCS", "channels": [...],
          "triggered_at": "..."}``

    **Client -> Server messages** (JSON):
        ``{"action": "ack", "alert_id": 1}``  — acknowledge receipt of an alert.
    """
    # ── authenticate (short-lived DB session; closed before the loop) ──
    user_id = await _authenticate_scoped(websocket, token)
    if user_id is None:
        await websocket.close(code=4001, reason="Authentication failed")
        return

    # ── register connection ───────────────────────────────────────
    await manager.connect(websocket, user_id)
    logger.info("Alert stream connected: user_id=%s", user_id)

    try:
        while True:
            try:
                raw = await websocket.receive_json()
            except ValueError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            action: str | None = raw.get("action")

            if action == "ack":
                alert_id = raw.get("alert_id")
                if alert_id is not None:
                    logger.info(
                        "Alert acknowledged: user_id=%s alert_id=%s",
                        user_id,
                        alert_id,
                    )
                    await websocket.send_json({
                        "type": "ack_confirmed",
                        "alert_id": alert_id,
                    })
                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": "ack requires 'alert_id'",
                    })

            else:
                await websocket.send_json({
                    "type": "error",
                    "message": (
                        "Invalid message. Expected "
                        '{"action": "ack", "alert_id": <int>}'
                    ),
                })

    except WebSocketDisconnect:
        logger.info("Alert stream client disconnected: user_id=%s", user_id)
    except Exception:
        logger.exception(
            "Unexpected error in alert stream for user_id=%s", user_id
        )
    finally:
        manager.disconnect(websocket)
