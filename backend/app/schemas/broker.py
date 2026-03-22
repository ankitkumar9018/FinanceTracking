"""Broker-related Pydantic schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class BrokerConnectRequest(BaseModel):
    """Request body for connecting a new broker."""

    broker_name: str
    api_key: str
    api_secret: str
    additional_params: dict | None = None


class BrokerConnectionResponse(BaseModel):
    """Response for a broker connection record."""

    id: int
    broker_name: str
    is_active: bool
    last_synced: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class BrokerSyncResponse(BaseModel):
    """Response from a holdings sync operation."""

    holdings_synced: int
    new_holdings: int
    updated_holdings: int
    errors: list[str]


class BrokerStatusResponse(BaseModel):
    """Response for a connection status/health check."""

    connection_id: int
    broker_name: str
    is_active: bool
    is_connected: bool
    last_synced: datetime | None
