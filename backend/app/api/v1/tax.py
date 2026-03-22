"""Tax management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.tax_record import TaxRecord
from app.models.user import User
from app.schemas.tax import (
    TaxHarvestingSuggestion,
    TaxRecordCreate,
    TaxRecordResponse,
    TaxSummary,
)
from app.services.tax_service import (
    compute_tax_for_transaction,
    generate_tax_summary,
    get_harvesting_suggestions,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_user_tax_record(
    record_id: int,
    user: User,
    db: AsyncSession,
) -> TaxRecord:
    """Fetch a tax record ensuring it belongs to the current user."""
    result = await db.execute(
        select(TaxRecord).where(
            TaxRecord.id == record_id,
            TaxRecord.user_id == user.id,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tax record not found",
        )
    return record


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[TaxRecordResponse])
async def list_tax_records(
    financial_year: str | None = Query(default=None, description="Filter by financial year"),
    jurisdiction: str | None = Query(default=None, description="Filter by jurisdiction (IN/DE)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TaxRecord]:
    """List all tax records for the current user, with optional filters."""
    stmt = select(TaxRecord).where(TaxRecord.user_id == user.id)

    if financial_year is not None:
        stmt = stmt.where(TaxRecord.financial_year == financial_year)
    if jurisdiction is not None:
        stmt = stmt.where(TaxRecord.tax_jurisdiction == jurisdiction.upper())

    stmt = stmt.order_by(TaxRecord.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post(
    "/compute/{transaction_id}",
    response_model=TaxRecordResponse,
    status_code=status.HTTP_201_CREATED,
)
async def compute_transaction_tax(
    transaction_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaxRecord:
    """Compute tax for a specific SELL transaction and create a tax record."""
    try:
        tax_record = await compute_tax_for_transaction(
            transaction_id=transaction_id,
            user_id=user.id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return tax_record


@router.get("/summary", response_model=TaxSummary)
async def tax_summary(
    financial_year: str = Query(..., description="Financial year, e.g. '2024-25' or '2024'"),
    jurisdiction: str = Query(..., description="Tax jurisdiction: IN or DE"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get tax summary for a financial year and jurisdiction."""
    summary = await generate_tax_summary(
        user_id=user.id,
        financial_year=financial_year,
        jurisdiction=jurisdiction.upper(),
        db=db,
    )
    return summary


@router.get("/harvesting", response_model=list[TaxHarvestingSuggestion])
async def harvesting_suggestions(
    jurisdiction: str = Query(default="IN", description="Tax jurisdiction: IN or DE"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Get tax-loss harvesting suggestions for holdings with unrealized losses."""
    suggestions = await get_harvesting_suggestions(
        user_id=user.id,
        jurisdiction=jurisdiction.upper(),
        db=db,
    )
    return suggestions


@router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tax_record(
    record_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a tax record."""
    record = await _get_user_tax_record(record_id, user, db)
    await db.delete(record)
    await db.flush()
