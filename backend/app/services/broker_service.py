"""Broker service — credential management, connection lifecycle, and sync."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.brokers import BROKER_REGISTRY, get_broker
from app.models.broker_connection import BrokerConnection
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.utils.security import decrypt_value as _decrypt
from app.utils.security import encrypt_value as _encrypt

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# connect_broker
# ---------------------------------------------------------------------------

async def connect_broker(
    user_id: int,
    broker_name: str,
    api_key: str,
    api_secret: str,
    db: AsyncSession,
    additional_params: dict | None = None,
) -> BrokerConnection:
    """Encrypt credentials, save to DB, and optionally test the connection.

    Parameters
    ----------
    user_id : int
        The ID of the authenticated user.
    broker_name : str
        Key from ``BROKER_REGISTRY`` (e.g. ``"zerodha"``).
    api_key, api_secret : str
        Raw API credentials that will be Fernet-encrypted before storage.
    db : AsyncSession
        Database session.
    additional_params : dict | None
        Extra parameters forwarded to the broker's ``connect()`` method
        (e.g. ``request_token`` for Zerodha).

    Returns
    -------
    BrokerConnection
        The newly-created (or reactivated) database record.

    Raises
    ------
    ValueError
        If the broker name is unknown.
    RuntimeError
        If the broker SDK is not installed or connection fails.
    """
    # Validate broker name
    if broker_name not in BROKER_REGISTRY:
        available = ", ".join(sorted(BROKER_REGISTRY.keys()))
        raise ValueError(f"Unknown broker '{broker_name}'. Available: {available}")

    # Check for existing active connection for this user + broker
    result = await db.execute(
        select(BrokerConnection).where(
            BrokerConnection.user_id == user_id,
            BrokerConnection.broker_name == broker_name,
            BrokerConnection.is_active.is_(True),
        )
    )
    existing = result.scalar_one_or_none()

    # Encrypt credentials
    encrypted_key = _encrypt(api_key)
    encrypted_secret = _encrypt(api_secret)

    # Attempt a test connection
    adapter = get_broker(broker_name)
    kwargs = additional_params or {}
    connect_result = await adapter.connect(api_key, api_secret, **kwargs)

    access_token = connect_result.get("access_token")
    encrypted_access_token = _encrypt(access_token) if access_token else None

    if existing:
        # Update existing connection
        existing.encrypted_api_key = encrypted_key
        existing.encrypted_api_secret = encrypted_secret
        existing.access_token_encrypted = encrypted_access_token
        existing.is_active = True
        await db.flush()
        await db.refresh(existing)
        logger.info(
            "Updated broker connection id=%d broker=%s user=%d",
            existing.id,
            broker_name,
            user_id,
        )
        return existing

    # Create new connection
    connection = BrokerConnection(
        user_id=user_id,
        broker_name=broker_name,
        encrypted_api_key=encrypted_key,
        encrypted_api_secret=encrypted_secret,
        access_token_encrypted=encrypted_access_token,
        is_active=True,
    )
    db.add(connection)
    await db.flush()
    await db.refresh(connection)

    logger.info(
        "Created broker connection id=%d broker=%s user=%d",
        connection.id,
        broker_name,
        user_id,
    )
    return connection


# ---------------------------------------------------------------------------
# disconnect_broker
# ---------------------------------------------------------------------------

async def disconnect_broker(
    connection_id: int,
    user_id: int,
    db: AsyncSession,
) -> None:
    """Deactivate a broker connection.

    Raises
    ------
    ValueError
        If the connection is not found or does not belong to the user.
    """
    connection = await _get_user_connection(connection_id, user_id, db)

    # Try to gracefully disconnect the adapter
    try:
        adapter = get_broker(connection.broker_name)
        if connection.access_token_encrypted:
            api_key = _decrypt(connection.encrypted_api_key)
            api_secret = _decrypt(connection.encrypted_api_secret)
            await adapter.connect(api_key, api_secret)
            await adapter.disconnect()
    except Exception:
        logger.warning(
            "Failed to gracefully disconnect broker id=%d", connection_id, exc_info=True
        )

    connection.is_active = False
    connection.access_token_encrypted = None
    await db.flush()

    logger.info("Deactivated broker connection id=%d user=%d", connection_id, user_id)


# ---------------------------------------------------------------------------
# sync_holdings
# ---------------------------------------------------------------------------

async def sync_holdings(
    connection_id: int,
    user_id: int,
    db: AsyncSession,
) -> dict:
    """Fetch holdings from the broker and upsert into the holdings table.

    Returns
    -------
    dict
        ``{"holdings_synced": ..., "new_holdings": ..., "updated_holdings": ..., "errors": [...]}``
    """
    connection = await _get_user_connection(connection_id, user_id, db)

    if not connection.is_active:
        raise ValueError("Broker connection is not active")

    # Decrypt credentials and connect
    api_key = _decrypt(connection.encrypted_api_key)
    api_secret = _decrypt(connection.encrypted_api_secret)

    adapter = get_broker(connection.broker_name)

    # Re-establish connection using stored access token if available
    connect_kwargs: dict = {}
    if connection.access_token_encrypted:
        # For reconnection, we pass the stored access token info
        pass  # Adapter will use api_key/secret to reconnect

    await adapter.connect(api_key, api_secret, **connect_kwargs)

    # Fetch holdings from broker
    broker_holdings = await adapter.get_holdings()

    # Get or create a default portfolio for the user
    portfolio = await _get_or_create_default_portfolio(user_id, db)

    new_count = 0
    updated_count = 0
    errors: list[str] = []

    for bh in broker_holdings:
        try:
            # Check if holding already exists
            result = await db.execute(
                select(Holding).where(
                    Holding.portfolio_id == portfolio.id,
                    Holding.stock_symbol == bh.symbol,
                    Holding.exchange == bh.exchange,
                )
            )
            existing_holding = result.scalar_one_or_none()

            if existing_holding:
                # Update existing holding
                existing_holding.cumulative_quantity = bh.quantity
                existing_holding.average_price = bh.average_price
                if bh.last_price is not None:
                    existing_holding.current_price = bh.last_price
                    existing_holding.last_price_update = datetime.now(timezone.utc)
                updated_count += 1
            else:
                # Create new holding
                new_holding = Holding(
                    portfolio_id=portfolio.id,
                    stock_symbol=bh.symbol,
                    stock_name=bh.symbol,  # Use symbol as name; can be enriched later
                    exchange=bh.exchange,
                    cumulative_quantity=bh.quantity,
                    average_price=bh.average_price,
                    current_price=bh.last_price,
                    last_price_update=(
                        datetime.now(timezone.utc) if bh.last_price else None
                    ),
                )
                db.add(new_holding)
                new_count += 1
        except Exception as exc:
            error_msg = f"Error syncing {bh.symbol}: {exc}"
            errors.append(error_msg)
            logger.warning(error_msg, exc_info=True)

    # Update last_synced timestamp
    connection.last_synced = datetime.now(timezone.utc)
    await db.flush()

    total_synced = new_count + updated_count
    logger.info(
        "Sync complete for connection id=%d: %d synced (%d new, %d updated, %d errors)",
        connection_id,
        total_synced,
        new_count,
        updated_count,
        len(errors),
    )

    return {
        "holdings_synced": total_synced,
        "new_holdings": new_count,
        "updated_holdings": updated_count,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# list_connections
# ---------------------------------------------------------------------------

async def list_connections(
    user_id: int,
    db: AsyncSession,
) -> list[BrokerConnection]:
    """List all active broker connections for a user."""
    result = await db.execute(
        select(BrokerConnection)
        .where(
            BrokerConnection.user_id == user_id,
            BrokerConnection.is_active.is_(True),
        )
        .order_by(BrokerConnection.created_at.desc())
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# get_connection_status
# ---------------------------------------------------------------------------

async def get_connection_status(
    connection_id: int,
    user_id: int,
    db: AsyncSession,
) -> dict:
    """Check the health of a broker connection.

    Returns
    -------
    dict
        ``{"connection_id": ..., "broker_name": ..., "is_active": ...,
        "is_connected": ..., "last_synced": ...}``
    """
    connection = await _get_user_connection(connection_id, user_id, db)

    is_connected = False
    if connection.is_active and connection.access_token_encrypted:
        try:
            api_key = _decrypt(connection.encrypted_api_key)
            api_secret = _decrypt(connection.encrypted_api_secret)
            adapter = get_broker(connection.broker_name)
            await adapter.connect(api_key, api_secret)
            is_connected = adapter.is_connected()
        except Exception:
            logger.debug(
                "Connection health check failed for id=%d", connection_id, exc_info=True
            )

    return {
        "connection_id": connection.id,
        "broker_name": connection.broker_name,
        "is_active": connection.is_active,
        "is_connected": is_connected,
        "last_synced": connection.last_synced,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _get_user_connection(
    connection_id: int,
    user_id: int,
    db: AsyncSession,
) -> BrokerConnection:
    """Fetch a broker connection ensuring it belongs to the user.

    Raises
    ------
    ValueError
        If the connection is not found or does not belong to the user.
    """
    result = await db.execute(
        select(BrokerConnection).where(
            BrokerConnection.id == connection_id,
            BrokerConnection.user_id == user_id,
        )
    )
    connection = result.scalar_one_or_none()
    if connection is None:
        raise ValueError("Broker connection not found")
    return connection


async def _get_or_create_default_portfolio(
    user_id: int,
    db: AsyncSession,
) -> Portfolio:
    """Get the user's default portfolio, creating one if it doesn't exist."""
    result = await db.execute(
        select(Portfolio).where(
            Portfolio.user_id == user_id,
            Portfolio.is_default.is_(True),
        )
    )
    portfolio = result.scalar_one_or_none()

    if portfolio is None:
        # Fall back to any portfolio
        result = await db.execute(
            select(Portfolio)
            .where(Portfolio.user_id == user_id)
            .order_by(Portfolio.created_at.asc())
            .limit(1)
        )
        portfolio = result.scalar_one_or_none()

    if portfolio is None:
        # Create a default portfolio
        portfolio = Portfolio(
            user_id=user_id,
            name="Broker Sync",
            description="Auto-created portfolio for broker-synced holdings",
            is_default=True,
        )
        db.add(portfolio)
        await db.flush()
        await db.refresh(portfolio)

    return portfolio
