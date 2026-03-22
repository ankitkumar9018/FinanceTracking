"""Asset model — non-stock assets for net worth tracking (crypto, gold, FD, bond, real estate)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, Float, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_type: Mapped[str] = mapped_column(
        String(30), nullable=False, index=True
    )  # CRYPTO / GOLD / FIXED_DEPOSIT / BOND / REAL_ESTATE

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    symbol: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # e.g. BTC-USD, ETH-USD, GC=F, GOLDBEES.NS
    quantity: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=6), default=0, server_default="0"
    )
    purchase_price: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=4), default=0, server_default="0"
    )
    current_value: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=4), default=0, server_default="0"
    )
    currency: Mapped[str] = mapped_column(
        String(10), default="INR", server_default="INR"
    )

    # Fixed deposit / bond specific fields
    interest_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    maturity_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        onupdate=func.now(), server_default=func.now(), nullable=True
    )

    # ── Relationships ──────────────────────────────────────────────
    user: Mapped[User] = relationship()

    def __repr__(self) -> str:
        return (
            f"<Asset id={self.id} type={self.asset_type!r} "
            f"name={self.name!r}>"
        )
