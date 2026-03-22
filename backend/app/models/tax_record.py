"""TaxRecord model — capital gains and tax liability records."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TaxRecord(Base):
    __tablename__ = "tax_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    financial_year: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # e.g. "2024-25"

    tax_jurisdiction: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # IN / DE
    gain_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # STCG / LTCG / ABGELTUNGSSTEUER / VORABPAUSCHALE

    purchase_date: Mapped[date] = mapped_column(Date, nullable=False)
    sale_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    purchase_price: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=4), nullable=False
    )
    sale_price: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=4), nullable=True
    )
    gain_amount: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=4), nullable=True
    )
    tax_amount: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=4), nullable=True
    )

    holding_period_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )

    # ── Relationships ──────────────────────────────────────────────
    user: Mapped[User] = relationship()
    transaction: Mapped[Transaction | None] = relationship()

    def __repr__(self) -> str:
        return (
            f"<TaxRecord id={self.id} fy={self.financial_year!r} "
            f"type={self.gain_type!r}>"
        )
