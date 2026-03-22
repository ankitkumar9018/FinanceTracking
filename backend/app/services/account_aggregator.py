"""Account Aggregator (AA) framework integration for India.

Supports consent-based data pull from banks and financial institutions
via AA providers like Finvu, OneMoney, CAMS Finserv.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class AAProvider(str, Enum):
    FINVU = "finvu"
    ONEMONEY = "onemoney"
    CAMS_FINSERV = "cams_finserv"


class ConsentStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"
    EXPIRED = "expired"


@dataclass
class ConsentRequest:
    provider: AAProvider
    user_id: int
    purpose: str = "Portfolio tracking"
    data_types: list[str] = field(default_factory=lambda: ["EQUITIES", "MUTUAL_FUNDS", "DEMAT"])
    from_date: datetime | None = None
    to_date: datetime | None = None


@dataclass
class ConsentResponse:
    consent_id: str
    status: ConsentStatus
    redirect_url: str | None = None
    expires_at: datetime | None = None


@dataclass
class AAHolding:
    symbol: str
    name: str
    exchange: str
    quantity: float
    average_price: float
    isin: str | None = None


@dataclass
class AAData:
    provider: AAProvider
    consent_id: str
    holdings: list[AAHolding] = field(default_factory=list)
    mutual_funds: list[dict] = field(default_factory=list)
    fetched_at: datetime | None = None


class AccountAggregatorService:
    """Abstract AA service. Concrete implementations per provider."""

    def __init__(self, provider: AAProvider):
        self.provider = provider
        self._available = False

    async def initiate_consent(self, request: ConsentRequest) -> ConsentResponse:
        """Initiate consent flow with AA provider. Returns redirect URL for user."""
        raise NotImplementedError(
            f"Account Aggregator integration with {self.provider.value} is coming soon. "
            "This feature requires registration with AA providers."
        )

    async def check_consent_status(self, consent_id: str) -> ConsentStatus:
        """Check if user has approved the consent."""
        raise NotImplementedError(f"{self.provider.value} consent check not implemented")

    async def fetch_data(self, consent_id: str) -> AAData:
        """Fetch financial data after consent is approved."""
        raise NotImplementedError(f"{self.provider.value} data fetch not implemented")

    def is_available(self) -> bool:
        return self._available


# Registry
AA_PROVIDERS = {
    AAProvider.FINVU: AccountAggregatorService(AAProvider.FINVU),
    AAProvider.ONEMONEY: AccountAggregatorService(AAProvider.ONEMONEY),
    AAProvider.CAMS_FINSERV: AccountAggregatorService(AAProvider.CAMS_FINSERV),
}


def get_aa_provider(provider: AAProvider) -> AccountAggregatorService:
    return AA_PROVIDERS.get(provider, AccountAggregatorService(provider))


async def get_available_providers() -> list[dict]:
    """Return list of AA providers with their availability status."""
    return [
        {
            "provider": p.value,
            "name": p.value.replace("_", " ").title(),
            "available": svc.is_available(),
            "description": _PROVIDER_DESCRIPTIONS.get(p, ""),
        }
        for p, svc in AA_PROVIDERS.items()
    ]


_PROVIDER_DESCRIPTIONS = {
    AAProvider.FINVU: "Finvu AA — access demat holdings, bank accounts, mutual funds via consent",
    AAProvider.ONEMONEY: "OneMoney AA — unified financial data aggregation with consent",
    AAProvider.CAMS_FINSERV: "CAMS Finserv AA — mutual fund and securities data aggregation",
}
