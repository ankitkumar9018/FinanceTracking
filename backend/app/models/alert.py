"""Alert model — user-defined alert configurations."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    holding_id: Mapped[int | None] = mapped_column(
        ForeignKey("holdings.id", ondelete="SET NULL"), nullable=True, index=True
    )
    watchlist_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("watchlist_items.id", ondelete="SET NULL"), nullable=True, index=True
    )

    alert_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # PRICE_RANGE / RSI / CUSTOM
    condition: Mapped[dict] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1"
    )
    last_triggered: Mapped[datetime | None] = mapped_column(nullable=True)
    channels: Mapped[list] = mapped_column(
        JSON, default=lambda: ["in_app"], server_default='["in_app"]'
    )

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )

    # ── Relationships ──────────────────────────────────────────────
    user: Mapped[User] = relationship(back_populates="alerts")
    holding: Mapped[Holding | None] = relationship(back_populates="alerts")
    watchlist_item: Mapped[WatchlistItem | None] = relationship(
        back_populates="alerts"
    )

    def __repr__(self) -> str:
        return f"<Alert id={self.id} type={self.alert_type!r} active={self.is_active}>"
