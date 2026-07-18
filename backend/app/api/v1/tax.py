"""Tax management endpoints."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.database import get_db
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.tax_record import TaxRecord
from app.models.user import User
from app.models.user_preferences import UserPreferences
from app.schemas.tax import (
    TaxHarvestingSuggestion,
    TaxRecordResponse,
    TaxSummary,
)
from app.services.export_service import (
    export_tax_report_csv,
    generate_tax_report_html,
)
from app.services.tax_service import (
    EXCHANGE_JURISDICTION_MAP,
    INDIA_LTCG_RATE,
    INDIA_STCG_RATE,
    _add_months,
    build_open_lots,
    compute_german_allowance,
    compute_tax_for_transaction,
    estimate_portfolio_vorabpauschale,
    generate_tax_summary,
    get_harvesting_suggestions,
)

router = APIRouter()

# STCG lots within this many days of the 12-month mark get a best-effort estimate
# of the tax saved by waiting for LTCG treatment (20 % -> 12.5 %).
_LTCG_SOON_DAYS = 30


# ---------------------------------------------------------------------------
# Request schemas for the German advanced-tax settings
# ---------------------------------------------------------------------------

FundType = Literal["STOCK", "EQUITY_ETF", "MIXED_ETF", "BOND_ETF", "REAL_ESTATE_ETF"]


class TaxSettingsUpdate(BaseModel):
    """German tax election written to ``user_preferences.tax_settings``."""

    filing: Literal["single", "joint"] | None = None
    church_tax: bool | None = None


class FundTypeUpdate(BaseModel):
    """Set a holding's fund class for German Teilfreistellung. ``None`` clears it."""

    fund_type: FundType | None = None


class HoldingPeriodLot(BaseModel):
    """One still-open FIFO buy lot and its LTCG-eligibility timing (India)."""

    stock_symbol: str
    purchase_date: date
    quantity: float
    ltcg_date: date
    days_remaining: int
    status: Literal["STCG", "LTCG"]
    potential_tax_saving: float | None = None


class HoldingPeriodSummary(BaseModel):
    """Roll-up counts for the holding-period timer."""

    stcg_lots: int
    ltcg_lots: int
    next_eligible_date: date | None = None


class HoldingPeriodTimer(BaseModel):
    """Response for the Indian LTCG holding-period timer."""

    portfolio_id: int
    lots: list[HoldingPeriodLot]
    summary: HoldingPeriodSummary


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


async def _get_or_create_prefs(user_id: int, db: AsyncSession) -> UserPreferences:
    """Fetch (or lazily create) the user's UserPreferences row."""
    result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == user_id)
    )
    prefs = result.scalar_one_or_none()
    if prefs is None:
        prefs = UserPreferences(user_id=user_id)
        db.add(prefs)
        await db.flush()
    return prefs


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
    response_model=list[TaxRecordResponse],
    status_code=status.HTTP_201_CREATED,
)
async def compute_transaction_tax(
    transaction_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TaxRecord]:
    """Compute per-lot FIFO tax for a SELL transaction and create tax records.

    A single SELL can straddle the STCG/LTCG boundary (India) and so yield
    multiple records, hence the list response.
    """
    try:
        tax_records = await compute_tax_for_transaction(
            transaction_id=transaction_id,
            user_id=user.id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return tax_records


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


@router.get("/report/{financial_year}")
async def download_tax_report(
    financial_year: str,
    jurisdiction: str = Query(default="IN", description="Tax jurisdiction: IN or DE"),
    format: str = Query(default="csv", description="Report format: csv or html"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Download a consolidated, ITR-ready capital-gains tax report.

    Returns a per-record capital-gains statement plus a totals summary for the
    given financial year and jurisdiction, scoped to the current user, as a CSV
    or a self-contained printable HTML file (``format=csv`` | ``format=html``).
    """
    fmt = format.lower()
    if fmt not in ("csv", "html"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="format must be 'csv' or 'html'",
        )

    jur = jurisdiction.upper()
    # Filename-safe financial year (e.g. "2024-25" -> stays, but strip anything odd)
    safe_fy = "".join(c for c in financial_year if c.isalnum() or c in "-_") or "report"

    if fmt == "csv":
        content = await export_tax_report_csv(
            user_id=user.id,
            financial_year=financial_year,
            jurisdiction=jur,
            db=db,
        )
        return Response(
            content=content,
            media_type="text/csv",
            headers={
                "Content-Disposition": (
                    f"attachment; filename=tax_report_{safe_fy}_{jur}.csv"
                )
            },
        )

    html = await generate_tax_report_html(
        user_id=user.id,
        user_name=user.display_name or user.email,
        financial_year=financial_year,
        jurisdiction=jur,
        db=db,
    )
    return Response(
        content=html,
        media_type="text/html",
        headers={
            "Content-Disposition": (
                f"attachment; filename=tax_report_{safe_fy}_{jur}.html"
            )
        },
    )


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


# ---------------------------------------------------------------------------
# German advanced tax: Sparer-Pauschbetrag allowance, Vorabpauschale, settings
# ---------------------------------------------------------------------------

@router.get("/allowance")
async def german_allowance(
    jurisdiction: str = Query(default="DE", description="Only DE is supported"),
    financial_year: str | None = Query(
        default=None, description="Calendar year, e.g. '2024'. Defaults to current year."
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Sparer-Pauschbetrag usage for a German financial (calendar) year.

    Returns ``{total_allowance, used, remaining, filing}``. The saver's allowance
    is EUR 1000 (single) / EUR 2000 (joint), read from the user's tax settings.
    """
    if jurisdiction.upper() != "DE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The Sparer-Pauschbetrag allowance tracker applies to Germany (DE) only",
        )
    fy = financial_year or str(date.today().year)
    return await compute_german_allowance(
        user_id=user.id, financial_year=fy, db=db
    )


@router.get("/vorabpauschale/{portfolio_id}")
async def portfolio_vorabpauschale(
    portfolio_id: int,
    year: int | None = Query(default=None, description="Tax year; defaults to current year"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Estimated German Vorabpauschale per German fund holding in a portfolio.

    Uses current holding values as a proxy for the start/end values (exact fund
    values are not stored), so the result is an ESTIMATE (``is_estimate=True``).
    """
    port_result = await db.execute(
        select(Portfolio).where(
            Portfolio.id == portfolio_id,
            Portfolio.user_id == user.id,
        )
    )
    if port_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portfolio not found",
        )
    return await estimate_portfolio_vorabpauschale(
        portfolio_id=portfolio_id, db=db, year=year
    )


@router.get("/holding-period/{portfolio_id}", response_model=HoldingPeriodTimer)
async def holding_period_timer(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """LTCG holding-period timer for Indian (NSE/BSE) holdings in a portfolio.

    For every still-open FIFO buy lot of each Indian holding, report when the lot
    crosses the 12-calendar-month mark and becomes LTCG-eligible (taxed at 12.5 %
    instead of the 20 % STCG rate). ``days_remaining`` counts down to
    ``ltcg_date`` (0 or negative = already LTCG). German/other-jurisdiction
    holdings are skipped — the short-/long-term split is India-specific.

    Where a current price is available, STCG lots within ``_LTCG_SOON_DAYS`` of
    eligibility carry a best-effort ``potential_tax_saving`` = unrealized gain ×
    (20 % − 12.5 %) — the tax saved by waiting for LTCG treatment.
    """
    port_result = await db.execute(
        select(Portfolio).where(
            Portfolio.id == portfolio_id,
            Portfolio.user_id == user.id,
        )
    )
    if port_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portfolio not found",
        )

    indian_exchanges = [
        ex for ex, jur in EXCHANGE_JURISDICTION_MAP.items() if jur == "IN"
    ]
    result = await db.execute(
        select(Holding)
        .options(selectinload(Holding.transactions))
        .where(
            Holding.portfolio_id == portfolio_id,
            Holding.exchange.in_(indian_exchanges),
        )
    )
    holdings = list(result.scalars().all())

    today = date.today()
    lots: list[dict] = []
    for holding in holdings:
        current_price = (
            float(holding.current_price) if holding.current_price is not None else None
        )
        for lot in build_open_lots(list(holding.transactions)):
            purchase_date = lot["date"]
            quantity = lot["qty"]
            ltcg_date = _add_months(purchase_date, 12)
            days_remaining = (ltcg_date - today).days
            is_ltcg = days_remaining <= 0

            potential_tax_saving: float | None = None
            # Best-effort: only for still-STCG lots close to the 12-month mark
            # that have a live price and an unrealized gain to save tax on.
            if (
                not is_ltcg
                and 0 < days_remaining <= _LTCG_SOON_DAYS
                and current_price is not None
            ):
                unrealized_gain = (current_price - lot["price"]) * quantity
                if unrealized_gain > 0:
                    potential_tax_saving = round(
                        unrealized_gain * (INDIA_STCG_RATE - INDIA_LTCG_RATE), 2
                    )

            lots.append(
                {
                    "stock_symbol": holding.stock_symbol,
                    "purchase_date": purchase_date,
                    "quantity": round(quantity, 6),
                    "ltcg_date": ltcg_date,
                    "days_remaining": days_remaining,
                    "status": "LTCG" if is_ltcg else "STCG",
                    "potential_tax_saving": potential_tax_saving,
                }
            )

    # Soonest-to-become-LTCG first: STCG lots by ascending days remaining, then
    # already-eligible lots.
    lots.sort(key=lambda x: (x["status"] != "STCG", x["days_remaining"]))

    stcg_lots = sum(1 for x in lots if x["status"] == "STCG")
    stcg_dates = [x["ltcg_date"] for x in lots if x["status"] == "STCG"]

    return {
        "portfolio_id": portfolio_id,
        "lots": lots,
        "summary": {
            "stcg_lots": stcg_lots,
            "ltcg_lots": len(lots) - stcg_lots,
            "next_eligible_date": min(stcg_dates) if stcg_dates else None,
        },
    }


@router.put("/settings")
async def update_tax_settings(
    body: TaxSettingsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update the German filing election / church-tax flag in tax settings.

    Only the fields provided are changed; others are preserved.
    """
    prefs = await _get_or_create_prefs(user.id, db)
    # Reassign a new dict so SQLAlchemy detects the JSON column change.
    settings = dict(prefs.tax_settings or {})
    if body.filing is not None:
        settings["filing"] = body.filing
    if body.church_tax is not None:
        settings["church_tax"] = body.church_tax
    prefs.tax_settings = settings
    await db.flush()
    return {"tax_settings": settings}


@router.put("/fund-type/{holding_id}")
async def update_holding_fund_type(
    holding_id: int,
    body: FundTypeUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Set a holding's fund class (used for German Teilfreistellung)."""
    result = await db.execute(
        select(Holding)
        .join(Portfolio, Holding.portfolio_id == Portfolio.id)
        .where(
            Holding.id == holding_id,
            Portfolio.user_id == user.id,
        )
    )
    holding = result.scalar_one_or_none()
    if holding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Holding not found",
        )
    holding.fund_type = body.fund_type
    await db.flush()
    return {"holding_id": holding_id, "fund_type": body.fund_type}


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
