"""Pydantic schemas for goal endpoints."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class GoalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    target_amount: float = Field(gt=0)
    target_date: date | None = None
    category: str = Field(min_length=1, max_length=30)
    linked_portfolio_id: int | None = None


class GoalUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    target_amount: float | None = Field(default=None, gt=0)
    current_amount: float | None = Field(default=None, ge=0)
    target_date: date | None = None
    category: str | None = Field(default=None, min_length=1, max_length=30)
    linked_portfolio_id: int | None = None
    is_achieved: bool | None = None


class GoalResponse(BaseModel):
    id: int
    user_id: int
    name: str
    target_amount: float
    current_amount: float
    target_date: date | None
    category: str
    linked_portfolio_id: int | None
    monthly_sip_needed: float | None
    is_achieved: bool
    created_at: datetime
    updated_at: datetime | None
    progress_percent: float = 0.0

    model_config = {"from_attributes": True}

    @classmethod
    def from_goal(cls, goal: object) -> GoalResponse:
        """Build a GoalResponse from an ORM Goal, computing progress_percent."""
        target = float(goal.target_amount) if goal.target_amount else 0  # type: ignore[union-attr]
        current = float(goal.current_amount) if goal.current_amount else 0  # type: ignore[union-attr]
        progress = round((current / target) * 100, 2) if target > 0 else 0.0
        return cls(
            id=goal.id,  # type: ignore[union-attr]
            user_id=goal.user_id,  # type: ignore[union-attr]
            name=goal.name,  # type: ignore[union-attr]
            target_amount=target,
            current_amount=current,
            target_date=goal.target_date,  # type: ignore[union-attr]
            category=goal.category,  # type: ignore[union-attr]
            linked_portfolio_id=goal.linked_portfolio_id,  # type: ignore[union-attr]
            monthly_sip_needed=float(goal.monthly_sip_needed) if goal.monthly_sip_needed is not None else None,  # type: ignore[union-attr]
            is_achieved=goal.is_achieved,  # type: ignore[union-attr]
            created_at=goal.created_at,  # type: ignore[union-attr]
            updated_at=goal.updated_at,  # type: ignore[union-attr]
            progress_percent=progress,
        )


class GoalSummary(BaseModel):
    id: int
    name: str
    target_amount: float
    current_amount: float
    progress_percent: float
    category: str
    is_achieved: bool
    monthly_sip_needed: float | None

    model_config = {"from_attributes": True}
