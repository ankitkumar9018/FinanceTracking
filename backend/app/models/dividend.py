"""Dividend model — dividend payments received for a holding."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Dividend(Base):
    __tablename__ = "dividends"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    holding_id: Mapped[int] = mapped_column(
        ForeignKey("holdings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ex_date: Mapped[date] = mapped_column(Date, nullable=False)
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    amount_per_share: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=4), nullable=False
    )
    total_amount: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=4), nullable=False
    )

    is_reinvested: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0"
    )
    reinvest_price: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=4), nullable=True
    )
    reinvest_shares: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=6), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )

    # ── Relationships ──────────────────────────────────────────────
    holding: Mapped[Holding] = relationship(back_populates="dividends")

    def __repr__(self) -> str:
        return (
            f"<Dividend id={self.id} ex_date={self.ex_date} "
            f"total={self.total_amount}>"
        )
