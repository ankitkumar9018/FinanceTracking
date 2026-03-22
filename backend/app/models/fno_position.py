"""FnoPosition model — Futures & Options position tracking."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FnoPosition(Base):
    __tablename__ = "fno_positions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="NSE"
    )  # NSE / BSE

    instrument_type: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # FUT / CE / PE
    strike_price: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=4), nullable=True
    )  # NULL for futures
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False)
    lot_size: Mapped[int] = mapped_column(nullable=False, default=1)
    quantity: Mapped[int] = mapped_column(nullable=False, default=1)  # number of lots

    entry_price: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=4), nullable=False
    )  # premium for options, price for futures
    exit_price: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=4), nullable=True
    )
    current_price: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=4), nullable=True
    )

    side: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="BUY"
    )  # BUY / SELL (long or short)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="OPEN"
    )  # OPEN / CLOSED / EXPIRED

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        onupdate=func.now(), server_default=func.now(), nullable=True
    )

    # ── Relationships ──────────────────────────────────────────────
    portfolio: Mapped[Portfolio] = relationship()

    def __repr__(self) -> str:
        return (
            f"<FnoPosition id={self.id} symbol={self.symbol!r} "
            f"type={self.instrument_type!r} strike={self.strike_price}>"
        )
