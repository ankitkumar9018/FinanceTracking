"""Holding model — an individual stock position within a portfolio."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Float, ForeignKey, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Holding(Base):
    __tablename__ = "holdings"
    __table_args__ = (
        UniqueConstraint(
            "portfolio_id", "stock_symbol", "exchange",
            name="uq_holding_portfolio_symbol_exchange",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stock_symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    stock_name: Mapped[str] = mapped_column(String(255), nullable=False)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)  # NSE/BSE/XETRA
    currency: Mapped[str] = mapped_column(String(10), default="INR", server_default="INR")

    cumulative_quantity: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=6), nullable=False
    )
    average_price: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=4), nullable=False
    )

    # ── Range / zone fields ────────────────────────────────────────
    lower_mid_range_1: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=4), nullable=True
    )
    lower_mid_range_2: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=4), nullable=True
    )
    upper_mid_range_1: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=4), nullable=True
    )
    upper_mid_range_2: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=4), nullable=True
    )
    base_level: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=4), nullable=True
    )
    top_level: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=4), nullable=True
    )

    # ── Live / computed fields ─────────────────────────────────────
    current_price: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=4), nullable=True
    )
    current_rsi: Mapped[float | None] = mapped_column(Float, nullable=True)
    action_needed: Mapped[str] = mapped_column(
        String(30), default="N", server_default="N"
    )  # N / Y_LOWER_MID / Y_UPPER_MID / Y_DARK_RED / Y_DARK_GREEN

    custom_fields: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_price_update: Mapped[datetime | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        onupdate=func.now(), server_default=func.now(), nullable=True
    )

    # ── Relationships ──────────────────────────────────────────────
    portfolio: Mapped[Portfolio] = relationship(back_populates="holdings")
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="holding", cascade="all, delete-orphan"
    )
    dividends: Mapped[list[Dividend]] = relationship(
        back_populates="holding", cascade="all, delete-orphan"
    )
    alerts: Mapped[list[Alert]] = relationship(
        back_populates="holding", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<Holding id={self.id} symbol={self.stock_symbol!r} "
            f"qty={self.cumulative_quantity}>"
        )
