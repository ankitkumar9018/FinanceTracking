"""WebSocket connection manager — tracks active connections and subscriptions."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from fastapi import WebSocket
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)

# A single stalled client must not delay delivery to everyone else, so each
# individual send is bounded by this timeout and all sends fan out concurrently.
_SEND_TIMEOUT_SECONDS = 5.0


# ── Subscription keys ─────────────────────────────────────────────────────────
#
# A ticker is NOT unique: the same symbol trades on NSE and on XETRA (and the
# two are different instruments in different currencies). Keying subscriptions
# on the symbol alone meant one exchange's price was pushed to holders of the
# other — a wrong number on screen, not merely a redundant one. So a
# subscription is a ``(symbol, exchange)`` pair.
#
# ``exchange`` may be ``None``, meaning "any exchange". That is what a plain
# ``"RELIANCE"`` subscription requests, which keeps every existing client
# working; a client that wants one listing sends ``"RELIANCE:NSE"`` (or
# ``{"symbol": "RELIANCE", "exchange": "NSE"}``) and then receives only that
# exchange's prices.

SubscriptionKey = tuple[str, str | None]

# What a client may send in the ``symbols`` list: "SYM", "SYM:EXCHANGE", or
# ``{"symbol": ..., "exchange": ...}``.
SubscriptionEntry = str | Mapping[str, object]


def parse_subscription(entry: SubscriptionEntry) -> SubscriptionKey | None:
    """Normalise one client-supplied subscription entry to a key.

    Returns ``None`` for an entry with no usable symbol, so a blank or
    malformed element is dropped rather than registering an unmatchable key.
    """
    if isinstance(entry, Mapping):
        raw_symbol = entry.get("symbol")
        raw_exchange = entry.get("exchange")
        symbol = "" if raw_symbol is None else str(raw_symbol)
        exchange = "" if raw_exchange is None else str(raw_exchange)
    else:
        symbol, _, exchange = str(entry).partition(":")
    symbol = symbol.upper().strip()
    exchange = exchange.upper().strip()
    if not symbol:
        return None
    return (symbol, exchange or None)


def format_subscription(key: SubscriptionKey) -> str:
    """Render a key back into the ``"SYM"`` / ``"SYM:EXCHANGE"`` wire form.

    Round-trips through :func:`parse_subscription`, so a client can unsubscribe
    with exactly the strings the ``subscribed`` confirmation echoed back.
    """
    symbol, exchange = key
    return f"{symbol}:{exchange}" if exchange else symbol


def _parse_all(entries: Sequence[SubscriptionEntry]) -> set[SubscriptionKey]:
    """Parse a client's ``symbols`` list, dropping the unusable entries."""
    return {key for entry in entries if (key := parse_subscription(entry))}


# ── Connection metadata ───────────────────────────────────────────────────────

@dataclass
class ConnectionInfo:
    """Metadata stored for each active WebSocket connection."""

    user_id: int
    subscriptions: set[SubscriptionKey] = field(default_factory=set)


# ── Manager ───────────────────────────────────────────────────────────────────

class ConnectionManager:
    """Manages WebSocket connections, subscriptions, and message broadcasting.

    A single module-level instance (``manager``) should be used across the
    application so that all routers share the same connection registry.
    """

    def __init__(self) -> None:
        self._connections: dict[WebSocket, ConnectionInfo] = {}
        # Strong references to in-flight best-effort close tasks so they are
        # not garbage-collected mid-flight (each removes itself when done).
        self._close_tasks: set[asyncio.Task] = set()

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

    def subscribe(
        self, websocket: WebSocket, symbols: Sequence[SubscriptionEntry]
    ) -> None:
        """Subscribe a connection to price updates for the given symbols.

        Each entry is a ``"SYM"`` (any exchange), ``"SYM:EXCHANGE"``, or
        ``{"symbol": ..., "exchange": ...}`` — see :func:`parse_subscription`.
        """
        info = self._connections.get(websocket)
        if info is None:
            return
        normalised = _parse_all(symbols)
        info.subscriptions |= normalised
        logger.debug(
            "user_id=%s subscribed to %s (now watching %s)",
            info.user_id,
            normalised,
            info.subscriptions,
        )

    def unsubscribe(
        self, websocket: WebSocket, symbols: Sequence[SubscriptionEntry]
    ) -> None:
        """Unsubscribe a connection from the given symbols.

        Removal is exact: unsubscribing from ``"RELIANCE"`` drops the
        any-exchange subscription and leaves an explicit ``"RELIANCE:NSE"`` one
        in place, mirroring how they were added.
        """
        info = self._connections.get(websocket)
        if info is None:
            return
        normalised = _parse_all(symbols)
        info.subscriptions -= normalised
        logger.debug(
            "user_id=%s unsubscribed from %s (now watching %s)",
            info.user_id,
            normalised,
            info.subscriptions,
        )

    def get_subscription_keys(self, websocket: WebSocket) -> set[SubscriptionKey]:
        """Return the ``(symbol, exchange)`` keys a connection is watching."""
        info = self._connections.get(websocket)
        return set(info.subscriptions) if info is not None else set()

    def get_subscriptions(self, websocket: WebSocket) -> set[str]:
        """Return a connection's subscriptions in the ``"SYM[:EXCHANGE]"`` wire form.

        Strings (rather than tuples) so the confirmation frames stay a sortable
        JSON array of scalars and round-trip straight back into ``unsubscribe``.
        """
        return {
            format_subscription(key) for key in self.get_subscription_keys(websocket)
        }

    # -- broadcasting --------------------------------------------------------

    async def broadcast_price_update(
        self, symbol: str, data: dict, exchange: str | None = None
    ) -> None:
        """Send a price update for *symbol* on *exchange* to its subscribers.

        Delivery is by ``(symbol, exchange)``, so a cross-listed ticker's NSE
        quote no longer reaches someone watching the XETRA listing. Both sides
        of the pair treat a missing exchange as a wildcard:

        - a client subscribed to the bare symbol receives every exchange's
          updates (it asked for any listing);
        - an update with no exchange reaches everyone watching that symbol,
          whichever listing they named, since there is nothing to filter on.
        """
        symbol_upper = symbol.upper().strip()
        exchange_upper = exchange.upper().strip() if exchange else None
        payload = {
            "type": "price_update",
            "symbol": symbol_upper,
            "exchange": exchange_upper,
            "data": data,
        }

        targets = [
            ws
            for ws, info in list(self._connections.items())
            if self._matches(info.subscriptions, symbol_upper, exchange_upper)
        ]
        await self._fan_out(targets, payload)

    @staticmethod
    def _matches(
        subscriptions: set[SubscriptionKey],
        symbol: str,
        exchange: str | None,
    ) -> bool:
        """Whether a connection's subscriptions cover *symbol* on *exchange*."""
        if exchange is None:
            return any(sub_symbol == symbol for sub_symbol, _ in subscriptions)
        return (symbol, exchange) in subscriptions or (symbol, None) in subscriptions

    async def send_alert(self, user_id: int, alert_data: dict) -> None:
        """Send an alert payload to all connections belonging to *user_id*."""
        targets = [
            ws
            for ws, info in list(self._connections.items())
            if info.user_id == user_id
        ]
        await self._fan_out(targets, alert_data)

    async def broadcast_all(self, data: dict) -> None:
        """Send a message to every connected client."""
        targets = list(self._connections)
        await self._fan_out(targets, data)

    # -- internals -----------------------------------------------------------

    async def _fan_out(self, targets: list[WebSocket], data: dict) -> None:
        """Send *data* to every websocket in *targets* concurrently.

        Every send runs in parallel and is bounded by ``_SEND_TIMEOUT_SECONDS``
        (inside ``_safe_send``), so one slow/stalled client can't hold up the
        others. Any connection whose send fails or times out is dropped.
        """
        if not targets:
            return

        results = await asyncio.gather(
            *(self._safe_send(ws, data) for ws in targets),
            return_exceptions=True,
        )
        for ws, result in zip(targets, results):
            if result is not True:
                self.disconnect(ws)
                # Dropping the registry entry alone leaves a zombie: the
                # client's receive loop keeps running, its subscribes silently
                # no-op, and it never reconnects. Best-effort close the socket
                # so the client's reconnect logic fires.
                task = asyncio.create_task(self._close_quietly(ws))
                self._close_tasks.add(task)
                task.add_done_callback(self._close_tasks.discard)

    @staticmethod
    async def _close_quietly(websocket: WebSocket) -> None:
        """Best-effort close of a dropped socket (1011 = internal error).

        The socket may already be closed or mid-teardown; any error here is
        irrelevant because the connection is already out of the registry.
        """
        try:
            await websocket.close(code=1011)
        except Exception:
            logger.debug("Ignoring error while closing a dropped WebSocket")

    @staticmethod
    async def _safe_send(websocket: WebSocket, data: dict) -> bool:
        """Send JSON to a websocket, returning ``False`` on failure/timeout."""
        try:
            if websocket.client_state != WebSocketState.CONNECTED:
                return False
            await asyncio.wait_for(
                websocket.send_json(data), timeout=_SEND_TIMEOUT_SECONDS
            )
            return True
        except Exception:
            logger.debug("Failed to send to WebSocket, marking as stale")
            return False


# ── Module-level singleton ────────────────────────────────────────────────────

manager = ConnectionManager()
