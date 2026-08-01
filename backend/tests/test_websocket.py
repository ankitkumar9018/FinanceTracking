"""Phase 2 tests for WebSocket endpoints (/ws/prices and /ws/alerts).

Uses Starlette's synchronous ``TestClient`` for WebSocket testing because
httpx.AsyncClient + ASGITransport does not support the WebSocket protocol.

The WS ``_authenticate`` helper now loads the user from the database and
rejects tokens for missing / deactivated accounts (and honours password-change
revocation), so a real, active user row is required — ``valid_ws_token``
registers one and returns its access token.
"""

from __future__ import annotations

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
