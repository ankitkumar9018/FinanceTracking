"""MutualFund model — mutual fund holdings within a portfolio."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class MutualFund(Base):
    __tablename__ = "mutual_funds"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scheme_code: Mapped[str] = mapped_column(String(50), nullable=False)
    scheme_name: Mapped[str] = mapped_column(String(255), nullable=False)
    folio_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    units: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=6), nullable=False
    )
    nav: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=4), nullable=False
    )
    invested_amount: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=4), nullable=False
    )
    current_value: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=4), nullable=True
    )

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
            f"<MutualFund id={self.id} scheme={self.scheme_name!r} "
            f"units={self.units}>"
        )
