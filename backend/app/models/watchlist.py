"""WatchlistItem model — stocks the user is watching but does not hold."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stock_symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    stock_name: Mapped[str] = mapped_column(String(255), nullable=False)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)

    target_buy_price: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=4), nullable=True
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
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        onupdate=func.now(), server_default=func.now(), nullable=True
    )

    # ── Relationships ──────────────────────────────────────────────
    user: Mapped[User] = relationship(back_populates="watchlist_items")
    alerts: Mapped[list[Alert]] = relationship(
        back_populates="watchlist_item", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<WatchlistItem id={self.id} symbol={self.stock_symbol!r}>"
