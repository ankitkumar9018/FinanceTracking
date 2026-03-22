"""AppSetting model — per-user key-value application settings (encrypted)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AppSetting(Base):
    __tablename__ = "app_settings"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_app_setting_user_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str] = mapped_column(String(1024), nullable=False)  # encrypted
    category: Mapped[str] = mapped_column(String(50), nullable=False)

    updated_at: Mapped[datetime | None] = mapped_column(
        onupdate=func.now(), server_default=func.now(), nullable=True
    )

    # ── Relationships ──────────────────────────────────────────────
    user: Mapped[User] = relationship()

    def __repr__(self) -> str:
        return f"<AppSetting id={self.id} key={self.key!r} category={self.category!r}>"
