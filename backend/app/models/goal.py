"""Goal model — financial goals tracked by the user."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_amount: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=4), nullable=False
    )
    current_amount: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=4), default=0, server_default="0"
    )

    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    category: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # RETIREMENT / HOUSE / EDUCATION / EMERGENCY / CUSTOM

    linked_portfolio_id: Mapped[int | None] = mapped_column(
        ForeignKey("portfolios.id", ondelete="SET NULL"), nullable=True
    )
    monthly_sip_needed: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=4), nullable=True
    )
    is_achieved: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0"
    )

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        onupdate=func.now(), server_default=func.now(), nullable=True
    )

    # ── Relationships ──────────────────────────────────────────────
    user: Mapped[User] = relationship(back_populates="goals")
    linked_portfolio: Mapped[Portfolio | None] = relationship()

    def __repr__(self) -> str:
        return f"<Goal id={self.id} name={self.name!r} target={self.target_amount}>"
