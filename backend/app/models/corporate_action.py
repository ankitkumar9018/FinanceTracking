"""Corporate-action model — stock splits, bonus issues, etc.

Detected corporate actions are recorded here so quantity/cost-basis
adjustments are auditable and applied exactly once per holding.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Float, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CorporateAction(Base):
    __tablename__ = "corporate_actions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    holding_id: Mapped[int] = mapped_column(
        ForeignKey("holdings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # SPLIT, BONUS, MERGER, SPINOFF, ...
    action_type: Mapped[str] = mapped_column(String(30), nullable=False)
    ex_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Multiplicative ratio applied to quantity (price is divided by it).
    # e.g. a 2:1 split -> ratio 2.0; a 1:1 bonus -> ratio 2.0; 3:2 -> 1.5
    ratio: Mapped[float] = mapped_column(Float, nullable=False)
    # DETECTED (awaiting user confirmation), APPLIED, DISMISSED
    status: Mapped[str] = mapped_column(
        String(20), default="DETECTED", server_default="DETECTED", nullable=False
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<CorporateAction {self.action_type} holding={self.holding_id} ratio={self.ratio} status={self.status}>"
