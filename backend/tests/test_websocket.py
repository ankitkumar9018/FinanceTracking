"""Phase 2 tests for WebSocket endpoints (/ws/prices and /ws/alerts).

Uses Starlette's synchronous ``TestClient`` for WebSocket testing because
httpx.AsyncClient + ASGITransport does not support the WebSocket protocol.

The shared WS auth helper (``app.api.ws.auth.authenticate_ws``) loads the user
from the database and rejects tokens for missing / deactivated accounts (and
honours password-change revocation), so a real, active user row is required —
``valid_ws_token`` registers one and returns its access token.

Auth failures are surfaced as an ACCEPTED handshake followed by an immediate
close with code 4001: closing an unaccepted socket would be rejected by uvicorn
as HTTP 403 and the 4001 frame would never reach a real client.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile

import pytest
from sqlalchemy import create_engine as create_sync_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session as SyncSession
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect, WebSocketState

from app.database import Base, get_db
from app.main import app
from app.models.user import User
from app.utils.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Dedicated file-backed DB for the WS tests
# ---------------------------------------------------------------------------
# Starlette's ``TestClient`` drives the app from its own BlockingPortal thread /
# event loop, and each bare request may run on a fresh portal loop. Now that WS
# auth issues DB queries, we need a DB that (a) is visible across those portal
# loops and (b) never shares a single connection object across event loops (that
# blows up the pytest-loop teardown of the conftest engine). A *file*-backed
# SQLite with ``NullPool`` gives both: every checkout opens its own short-lived
# connection to the same file, so nothing is shared cross-loop. The conftest
# in-memory engine is left untouched because ``get_db`` is overridden below.

_ws_db_fd, _ws_db_path = tempfile.mkstemp(suffix="_ws.sqlite")
os.close(_ws_db_fd)

_ws_async_engine = create_async_engine(
    f"sqlite+aiosqlite:///{_ws_db_path}",
    connect_args={"check_same_thread": False},
    poolclass=NullPool,
)
_ws_session_factory = async_sessionmaker(
    _ws_async_engine, class_=AsyncSession, expire_on_commit=False
)
_ws_sync_engine = create_sync_engine(f"sqlite:///{_ws_db_path}")
Base.metadata.create_all(_ws_sync_engine)


async def _ws_get_db():
    """``get_db`` override backed by the WS file DB (portal-loop safe)."""
    async with _ws_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def _seed_ws_user(
    email: str = "ws-user@example.com", *, is_active: bool = True
) -> tuple[int, int]:
    """Insert (or fetch) a user in the WS file DB; return ``(user_id, pcat)``.

    Written synchronously so it doesn't depend on any event loop, then read back
    by the async WS handler through the same file.
    """
    with SyncSession(_ws_sync_engine) as session:
        user = session.query(User).filter(User.email == email).one_or_none()
        if user is None:
            user = User(
                email=email,
                password_hash=hash_password("SecurePass123!"),
                is_active=is_active,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
        pcat = (
            int(user.password_changed_at.timestamp())
            if user.password_changed_at is not None
            else 0
        )
        return user.id, pcat


@pytest.fixture(autouse=True)
def _use_ws_db():
    """Point ``get_db`` at the WS file DB for the duration of a test."""
    original = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _ws_get_db
    yield
    if original is not None:
        app.dependency_overrides[get_db] = original
    else:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture(scope="module", autouse=True)
def _ws_db_cleanup():
    """Remove the temp WS DB file once the module's tests finish."""
    yield
    _ws_sync_engine.dispose()
    with contextlib.suppress(OSError):
        os.remove(_ws_db_path)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def ws_client() -> TestClient:
    """Synchronous Starlette test client for WebSocket interactions."""
    return TestClient(app)


@pytest.fixture()
def valid_ws_token() -> str:
    """A valid access token for a real, active user in the WS file DB.

    The token carries the matching ``pcat`` claim so password-change revocation
    accepts it, and refers to an existing active account so the DB user check
    passes.
    """
    user_id, pcat = _seed_ws_user()
    return create_access_token(data={"sub": str(user_id), "pcat": pcat})


# ---------------------------------------------------------------------------
# /ws/prices tests
# ---------------------------------------------------------------------------


class TestPriceStream:
    """Tests for the /ws/prices WebSocket endpoint."""

    def test_price_stream_no_auth(self, ws_client: TestClient) -> None:
        """Without a token the handshake is accepted, then closed with 4001.

        The accept-then-close order is deliberate: a close() on an unaccepted
        socket is rejected by uvicorn as HTTP 403 and the 4001 frame never
        reaches a real client.
        """
        with ws_client.websocket_connect("/ws/prices") as ws:
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_json()
            assert exc_info.value.code == 4001

    def test_price_stream_invalid_token(self, ws_client: TestClient) -> None:
        """A garbage token yields an accepted handshake then a 4001 close."""
        with ws_client.websocket_connect("/ws/prices?token=not-a-real-jwt") as ws:
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_json()
            assert exc_info.value.code == 4001

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
        """Without a token the handshake is accepted, then closed with 4001."""
        with ws_client.websocket_connect("/ws/alerts") as ws:
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_json()
            assert exc_info.value.code == 4001

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


# ---------------------------------------------------------------------------
# ConnectionManager — failed sends must close the socket, not just drop it
# ---------------------------------------------------------------------------


class _FakeWebSocket:
    """Minimal stand-in for a starlette WebSocket in manager unit tests."""

    def __init__(self, *, send_error: Exception | None = None) -> None:
        self.client_state = WebSocketState.CONNECTED
        self.send_error = send_error
        self.sent: list[dict] = []
        self.closed_with: int | None = None

    async def send_json(self, data: dict) -> None:
        if self.send_error is not None:
            raise self.send_error
        self.sent.append(data)

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.closed_with = code


async def test_fan_out_failed_send_disconnects_and_closes_socket() -> None:
    """A send that raises drops the client AND schedules a socket close, so
    the client's receive loop ends and its reconnect logic fires (previously
    the socket lingered as a zombie whose subscribes silently no-op'd)."""
    from app.api.ws.connection_manager import ConnectionInfo, ConnectionManager

    mgr = ConnectionManager()
    bad = _FakeWebSocket(send_error=RuntimeError("boom"))
    good = _FakeWebSocket()
    mgr._connections[bad] = ConnectionInfo(user_id=1)  # type: ignore[index]
    mgr._connections[good] = ConnectionInfo(user_id=2)  # type: ignore[index]

    await mgr._fan_out([bad, good], {"type": "price_update"})  # type: ignore[list-item]

    # Failed client is out of the registry; healthy client is untouched.
    assert bad not in mgr._connections
    assert good in mgr._connections
    assert good.sent == [{"type": "price_update"}]

    # The best-effort close was scheduled as a task; let it run.
    if mgr._close_tasks:
        await asyncio.gather(*mgr._close_tasks, return_exceptions=True)
    assert bad.closed_with == 1011
    assert good.closed_with is None


async def test_close_quietly_swallows_close_errors() -> None:
    """_close_quietly never propagates — the socket may already be dead."""
    from app.api.ws.connection_manager import ConnectionManager

    class _ExplodingWS:
        async def close(self, code: int = 1000, reason: str | None = None) -> None:
            raise RuntimeError("already closed")

    # Must not raise.
    await ConnectionManager._close_quietly(_ExplodingWS())  # type: ignore[arg-type]
