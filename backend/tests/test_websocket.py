"""Phase 2 tests for WebSocket endpoints (/ws/prices and /ws/alerts).

Uses Starlette's synchronous ``TestClient`` for WebSocket testing because
httpx.AsyncClient + ASGITransport does not support the WebSocket protocol.
Authentication tokens are created directly via ``create_access_token``
(the WS ``_authenticate`` helper only inspects the JWT payload, so no
real user row is required in the database).
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.utils.security import create_access_token


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def ws_client() -> TestClient:
    """Synchronous Starlette test client for WebSocket interactions."""
    return TestClient(app)


@pytest.fixture()
def valid_ws_token() -> str:
    """A valid JWT access token with sub='1' (synthetic user id)."""
    return create_access_token(data={"sub": "1"})


# ---------------------------------------------------------------------------
# /ws/prices tests
# ---------------------------------------------------------------------------


class TestPriceStream:
    """Tests for the /ws/prices WebSocket endpoint."""

    def test_price_stream_no_auth(self, ws_client: TestClient) -> None:
        """Connecting without a token closes the socket with code 4001."""
        with pytest.raises(Exception) as exc_info:
            with ws_client.websocket_connect("/ws/prices"):
                pass  # pragma: no cover
        # WebSocketDisconnect stores the code in .code attribute
        assert getattr(exc_info.value, "code", None) == 4001

    def test_price_stream_invalid_token(self, ws_client: TestClient) -> None:
        """Connecting with a garbage token closes the socket with code 4001."""
        with pytest.raises(Exception) as exc_info:
            with ws_client.websocket_connect("/ws/prices?token=not-a-real-jwt"):
                pass  # pragma: no cover
        assert getattr(exc_info.value, "code", None) == 4001

    def test_price_stream_subscribe(
        self, ws_client: TestClient, valid_ws_token: str
    ) -> None:
        """Subscribing to symbols returns a 'subscribed' confirmation."""
        with ws_client.websocket_connect(
            f"/ws/prices?token={valid_ws_token}"
        ) as ws:
            ws.send_json({"action": "subscribe", "symbols": ["RELIANCE"]})
            data = ws.receive_json()

            assert data["type"] == "subscribed"
            assert "RELIANCE" in data["symbols"]

    def test_price_stream_unsubscribe(
        self, ws_client: TestClient, valid_ws_token: str
    ) -> None:
        """Unsubscribing removes symbols from the active subscription list."""
        with ws_client.websocket_connect(
            f"/ws/prices?token={valid_ws_token}"
        ) as ws:
            # Subscribe to two symbols first
            ws.send_json(
                {"action": "subscribe", "symbols": ["RELIANCE", "TCS"]}
            )
            sub_data = ws.receive_json()
            assert sub_data["type"] == "subscribed"
            assert "RELIANCE" in sub_data["symbols"]
            assert "TCS" in sub_data["symbols"]

            # Unsubscribe from one
            ws.send_json({"action": "unsubscribe", "symbols": ["TCS"]})
            unsub_data = ws.receive_json()

            assert unsub_data["type"] == "unsubscribed"
            assert "TCS" not in unsub_data["symbols"]
            assert "RELIANCE" in unsub_data["symbols"]

    def test_price_stream_invalid_message(
        self, ws_client: TestClient, valid_ws_token: str
    ) -> None:
        """Sending an unknown action returns an error message."""
        with ws_client.websocket_connect(
            f"/ws/prices?token={valid_ws_token}"
        ) as ws:
            ws.send_json({"action": "unknown"})
            data = ws.receive_json()

            assert data["type"] == "error"
            assert "Invalid message" in data["message"]


# ---------------------------------------------------------------------------
# /ws/alerts tests
# ---------------------------------------------------------------------------


class TestAlertStream:
    """Tests for the /ws/alerts WebSocket endpoint."""

    def test_alert_stream_no_auth(self, ws_client: TestClient) -> None:
        """Connecting without a token closes the socket with code 4001."""
        with pytest.raises(Exception) as exc_info:
            with ws_client.websocket_connect("/ws/alerts"):
                pass  # pragma: no cover
        assert getattr(exc_info.value, "code", None) == 4001

    def test_alert_stream_ack(
        self, ws_client: TestClient, valid_ws_token: str
    ) -> None:
        """Acknowledging an alert returns an ack_confirmed response."""
        with ws_client.websocket_connect(
            f"/ws/alerts?token={valid_ws_token}"
        ) as ws:
            ws.send_json({"action": "ack", "alert_id": 1})
            data = ws.receive_json()

            assert data["type"] == "ack_confirmed"
            assert data["alert_id"] == 1
