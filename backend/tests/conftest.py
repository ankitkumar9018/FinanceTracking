"""Shared test fixtures for the FinanceTracker backend test suite.

Provides:
- In-memory SQLite async engine (fresh per test session)
- Async session factory bound to the test engine
- ``client`` — httpx.AsyncClient wired to the FastAPI app via ASGITransport
- ``db`` — async database session for direct ORM operations in tests
- ``auth_headers`` — registers a test user and returns JWT Authorization headers
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base, get_db
from app.main import app
from app.utils.rate_limiter import limiter

# Disable rate limiting during tests
limiter.enabled = False

# ---------------------------------------------------------------------------
# Test engine & session factory (in-memory SQLite)
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite+aiosqlite://"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

TestSessionFactory = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# Override the get_db dependency so all API routes use the test database
# ---------------------------------------------------------------------------

async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


app.dependency_overrides[get_db] = _override_get_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
async def _setup_teardown_tables():
    """Create all tables before each test, drop them after."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Provide a test database session for direct ORM operations."""
    async with TestSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an httpx.AsyncClient connected to the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# Test user credentials used across all authenticated tests
TEST_USER_EMAIL = "testuser@example.com"
TEST_USER_PASSWORD = "SecurePass123!"
TEST_USER_DISPLAY = "Test User"


@pytest.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    """Register a test user, log in, and return Authorization headers.

    Returns a dict like ``{"Authorization": "Bearer <access_token>"}``.
    """
    # Register
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": TEST_USER_EMAIL,
            "password": TEST_USER_PASSWORD,
            "display_name": TEST_USER_DISPLAY,
        },
    )

    # Login to obtain tokens
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={
            "email": TEST_USER_EMAIL,
            "password": TEST_USER_PASSWORD,
        },
    )
    tokens = login_resp.json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.fixture(autouse=True)
def _no_live_market_fallbacks(request, monkeypatch):
    """Keep the suite hermetic and fast.

    Several services now fall back to a LIVE market fetch when stored history
    is thin (benchmark returns for beta/alpha, technical indicators). In tests
    the seeded DB is deliberately small, so those fallbacks fire and make real
    yfinance calls — which is slow locally and, on CI runners that Yahoo
    rate-limits, is exactly what previously hung the pipeline for 10+ minutes.

    Default them to "no live data" so tests exercise the stored-data path
    deterministically. A test that deliberately covers the fallback opts out
    with ``@pytest.mark.live_fallback`` and installs its own stub.
    """
    if request.node.get_closest_marker("live_fallback") is not None:
        return
    import pandas as pd

    async def _no_benchmark(*_args, **_kwargs):
        return pd.Series(dtype=float)

    async def _no_ohlcv(*_args, **_kwargs):
        return []

    from app.ml import risk_calculator, technical_indicators

    monkeypatch.setattr(
        risk_calculator, "_fetch_benchmark_returns_live", _no_benchmark, raising=False
    )
    monkeypatch.setattr(
        technical_indicators, "_fetch_live_ohlcv", _no_ohlcv, raising=False
    )
