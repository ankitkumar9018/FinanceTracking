"""ChatSession model — AI chat history for the finance assistant."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    messages: Mapped[list] = mapped_column(
        JSON, default=list, server_default="[]"
    )  # [{role, content, timestamp}, ...]
    context: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        onupdate=func.now(), server_default=func.now(), nullable=True
    )

    # ── Relationships ──────────────────────────────────────────────
    user: Mapped[User] = relationship(back_populates="chat_sessions")

    def __repr__(self) -> str:
        msg_count = len(self.messages) if self.messages else 0
        return f"<ChatSession id={self.id} messages={msg_count}>"
