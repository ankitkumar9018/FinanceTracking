"""ForexRate model — daily foreign exchange rates."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ForexRate(Base):
    __tablename__ = "forex_rates"
    __table_args__ = (
        UniqueConstraint(
            "from_currency", "to_currency", "date",
            name="uq_forex_from_to_date",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    from_currency: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    to_currency: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    rate: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=8), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<ForexRate {self.from_currency}/{self.to_currency} "
            f"rate={self.rate} date={self.date}>"
        )
