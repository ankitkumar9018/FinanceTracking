"""WebSocket connection manager — tracks active connections and subscriptions."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from fastapi import WebSocket
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)


# ── Connection metadata ───────────────────────────────────────────────────────

@dataclass
class ConnectionInfo:
    """Metadata stored for each active WebSocket connection."""

    user_id: int
    subscribed_symbols: set[str] = field(default_factory=set)


# ── Manager ───────────────────────────────────────────────────────────────────

class ConnectionManager:
    """Manages WebSocket connections, subscriptions, and message broadcasting.

    A single module-level instance (``manager``) should be used across the
    application so that all routers share the same connection registry.
    """

    def __init__(self) -> None:
        self._connections: dict[WebSocket, ConnectionInfo] = {}

    # -- connection lifecycle ------------------------------------------------

    async def connect(self, websocket: WebSocket, user_id: int) -> None:
        """Accept the WebSocket handshake and register the connection."""
        await websocket.accept()
        self._connections[websocket] = ConnectionInfo(user_id=user_id)
        logger.info(
            "WebSocket connected: user_id=%s (total=%d)",
            user_id,
            len(self._connections),
        )

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a connection from the registry."""
        info = self._connections.pop(websocket, None)
        if info is not None:
            logger.info(
                "WebSocket disconnected: user_id=%s (total=%d)",
                info.user_id,
                len(self._connections),
            )

    # -- subscriptions -------------------------------------------------------

    def subscribe(self, websocket: WebSocket, symbols: list[str]) -> None:
        """Subscribe a connection to price updates for the given symbols."""
        info = self._connections.get(websocket)
        if info is None:
            return
        normalised = {s.upper().strip() for s in symbols if s.strip()}
        info.subscribed_symbols |= normalised
        logger.debug(
            "user_id=%s subscribed to %s (now watching %s)",
            info.user_id,
            normalised,
            info.subscribed_symbols,
        )

    def unsubscribe(self, websocket: WebSocket, symbols: list[str]) -> None:
        """Unsubscribe a connection from the given symbols."""
        info = self._connections.get(websocket)
        if info is None:
            return
        normalised = {s.upper().strip() for s in symbols if s.strip()}
        info.subscribed_symbols -= normalised
        logger.debug(
            "user_id=%s unsubscribed from %s (now watching %s)",
            info.user_id,
            normalised,
            info.subscribed_symbols,
        )

    def get_subscriptions(self, websocket: WebSocket) -> set[str]:
        """Return the set of subscribed symbols for a connection (or empty set)."""
        info = self._connections.get(websocket)
        return set(info.subscribed_symbols) if info is not None else set()

    # -- broadcasting --------------------------------------------------------

    async def broadcast_price_update(self, symbol: str, data: dict) -> None:
        """Send a price update to every connection subscribed to *symbol*."""
        symbol_upper = symbol.upper().strip()
        payload = {"type": "price_update", "symbol": symbol_upper, "data": data}

        stale: list[WebSocket] = []
        for ws, info in list(self._connections.items()):
            if symbol_upper in info.subscribed_symbols:
                if not await self._safe_send(ws, payload):
                    stale.append(ws)

        for ws in stale:
            self.disconnect(ws)

    async def send_alert(self, user_id: int, alert_data: dict) -> None:
        """Send an alert payload to all connections belonging to *user_id*."""
        stale: list[WebSocket] = []
        for ws, info in list(self._connections.items()):
            if info.user_id == user_id:
                if not await self._safe_send(ws, alert_data):
                    stale.append(ws)

        for ws in stale:
            self.disconnect(ws)

    async def broadcast_all(self, data: dict) -> None:
        """Send a message to every connected client."""
        stale: list[WebSocket] = []
        for ws in list(self._connections):
            if not await self._safe_send(ws, data):
                stale.append(ws)

        for ws in stale:
            self.disconnect(ws)

    # -- internals -----------------------------------------------------------

    @staticmethod
    async def _safe_send(websocket: WebSocket, data: dict) -> bool:
        """Send JSON to a websocket, returning ``False`` on failure."""
        try:
            if websocket.client_state != WebSocketState.CONNECTED:
                return False
            await websocket.send_json(data)
            return True
        except Exception:
            logger.debug("Failed to send to WebSocket, marking as stale")
            return False


# ── Module-level singleton ────────────────────────────────────────────────────

manager = ConnectionManager()
