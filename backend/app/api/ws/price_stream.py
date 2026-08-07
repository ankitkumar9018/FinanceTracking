"""WebSocket endpoint for real-time stock price streaming."""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.ws.auth import authenticate_ws
from app.api.ws.connection_manager import manager

logger = logging.getLogger(__name__)

router = APIRouter()


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
