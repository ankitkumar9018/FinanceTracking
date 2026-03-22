"""PriceHistory model — OHLCV + RSI daily price data."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, Float, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PriceHistory(Base):
    __tablename__ = "price_history"
    __table_args__ = (
        UniqueConstraint(
            "stock_symbol", "exchange", "date", name="uq_price_symbol_exchange_date"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stock_symbol: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    open: Mapped[float] = mapped_column(Numeric(precision=18, scale=4), nullable=False)
    high: Mapped[float] = mapped_column(Numeric(precision=18, scale=4), nullable=False)
    low: Mapped[float] = mapped_column(Numeric(precision=18, scale=4), nullable=False)
    close: Mapped[float] = mapped_column(Numeric(precision=18, scale=4), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)

    rsi_14: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<PriceHistory symbol={self.stock_symbol!r} "
            f"date={self.date} close={self.close}>"
        )
