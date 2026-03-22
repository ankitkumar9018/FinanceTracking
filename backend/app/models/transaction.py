"""Transaction model — BUY / SELL records for a holding."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    holding_id: Mapped[int] = mapped_column(
        ForeignKey("holdings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transaction_type: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # BUY / SELL
    date: Mapped[date] = mapped_column(Date, nullable=False)

    quantity: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=6), nullable=False
    )
    price: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=4), nullable=False
    )
    brokerage: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=4), default=0, server_default="0"
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(
        String(20), default="MANUAL", server_default="MANUAL"
    )  # MANUAL / EXCEL / BROKER

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )

    # ── Relationships ──────────────────────────────────────────────
    holding: Mapped[Holding] = relationship(back_populates="transactions")

    def __repr__(self) -> str:
        return (
            f"<Transaction id={self.id} type={self.transaction_type!r} "
            f"qty={self.quantity} price={self.price}>"
        )
