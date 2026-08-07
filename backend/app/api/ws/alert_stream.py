"""WebSocket endpoint for real-time alert notifications."""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.ws.auth import authenticate_ws
from app.api.ws.connection_manager import manager

logger = logging.getLogger(__name__)

router = APIRouter()


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
    user_id = await authenticate_ws(websocket, token)
    if user_id is None:
        # Accept the handshake BEFORE closing: closing an unaccepted socket
        # makes uvicorn reject the handshake as HTTP 403 and the 4001 close
        # frame never reaches the client, so browsers can't tell auth-expiry
        # apart from server-down. The success path accepts exactly once, in
        # manager.connect().
        await websocket.accept()
        await websocket.close(code=4001, reason="Authentication failed")
        return

    # ── register connection (manager.connect performs the accept) ─
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
