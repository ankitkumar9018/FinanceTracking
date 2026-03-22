"""Broker integration endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.brokers import BROKER_REGISTRY
from app.database import get_db
from app.models.user import User
from app.schemas.broker import (
    BrokerConnectRequest,
    BrokerConnectionResponse,
    BrokerStatusResponse,
    BrokerSyncResponse,
)
from app.services.broker_service import (
    connect_broker,
    disconnect_broker,
    get_connection_status,
    list_connections,
    sync_holdings,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[BrokerConnectionResponse])
async def list_broker_connections(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    """List all active broker connections for the current user."""
    connections = await list_connections(user.id, db)
    return connections


@router.post(
    "/connect",
    response_model=BrokerConnectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def connect_new_broker(
    body: BrokerConnectRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> object:
    """Connect a new broker by providing API credentials.

    The credentials are encrypted before storage.  If the broker supports
    an OAuth flow (e.g. Zerodha, ICICI Direct), the ``additional_params``
    field can carry the ``request_token`` / ``session_token``.
    """
    try:
        connection = await connect_broker(
            user_id=user.id,
            broker_name=body.broker_name,
            api_key=body.api_key,
            api_secret=body.api_secret,
            db=db,
            additional_params=body.additional_params,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return connection


@router.post("/{connection_id}/sync", response_model=BrokerSyncResponse)
async def sync_broker_holdings(
    connection_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Sync holdings from a connected broker into the local portfolio."""
    try:
        result = await sync_holdings(
            connection_id=connection_id,
            user_id=user.id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return result


@router.get("/{connection_id}/status", response_model=BrokerStatusResponse)
async def broker_connection_status(
    connection_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Check the health/status of a broker connection."""
    try:
        status_info = await get_connection_status(
            connection_id=connection_id,
            user_id=user.id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return status_info


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_broker_connection(
    connection_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Disconnect (deactivate) a broker connection."""
    try:
        await disconnect_broker(
            connection_id=connection_id,
            user_id=user.id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/available", response_model=list[dict])
async def list_available_brokers(
    user: User = Depends(get_current_user),
) -> list[dict]:
    """List all available brokers from the registry.

    Returns the broker name, display name, and implementation status.
    """
    brokers: list[dict] = []
    for name, cls in BROKER_REGISTRY.items():
        # Detect stub adapters by checking if connect raises NotImplementedError
        is_stub = False
        try:
            instance = cls()
            # Check if all abstract methods raise NotImplementedError
            # We look at the class itself — stubs have a simple pattern
            import inspect

            source = inspect.getsource(cls.connect)
            if "NotImplementedError" in source:
                is_stub = True
        except Exception:
            logger.debug("Failed to inspect broker %s for stub detection", name, exc_info=True)

        brokers.append(
            {
                "name": name,
                "display_name": name.replace("_", " ").title(),
                "status": "coming_soon" if is_stub else "available",
            }
        )

    return brokers
