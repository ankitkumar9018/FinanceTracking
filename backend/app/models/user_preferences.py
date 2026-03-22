"""UserPreferences model — UI/UX preferences per user (one-to-one)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserPreferences(Base):
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    column_order: Mapped[list] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    custom_columns: Mapped[list] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    table_density: Mapped[str] = mapped_column(
        String(20), default="comfortable", server_default="comfortable"
    )
    default_chart_days: Mapped[int] = mapped_column(
        Integer, default=30, server_default="30"
    )
    theme: Mapped[str] = mapped_column(
        String(20), default="dark", server_default="dark"
    )

    updated_at: Mapped[datetime | None] = mapped_column(
        onupdate=func.now(), server_default=func.now(), nullable=True
    )

    # ── Relationships ──────────────────────────────────────────────
    user: Mapped[User] = relationship()

    def __repr__(self) -> str:
        return f"<UserPreferences id={self.id} user_id={self.user_id}>"
