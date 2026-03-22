"""BrokerConnection model — encrypted API credentials for broker integrations."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class BrokerConnection(Base):
    __tablename__ = "broker_connections"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    broker_name: Mapped[str] = mapped_column(String(100), nullable=False)

    encrypted_api_key: Mapped[str] = mapped_column(String(512), nullable=False)
    encrypted_api_secret: Mapped[str] = mapped_column(String(512), nullable=False)
    access_token_encrypted: Mapped[str | None] = mapped_column(
        String(1024), nullable=True
    )
    token_expiry: Mapped[datetime | None] = mapped_column(nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1"
    )
    last_synced: Mapped[datetime | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        onupdate=func.now(), server_default=func.now(), nullable=True
    )

    # ── Relationships ──────────────────────────────────────────────
    user: Mapped[User] = relationship(back_populates="broker_connections")

    def __repr__(self) -> str:
        return (
            f"<BrokerConnection id={self.id} broker={self.broker_name!r} "
            f"active={self.is_active}>"
        )
