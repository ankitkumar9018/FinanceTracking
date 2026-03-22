"""Excel, CSV, JSON, PDF import / export, backup, and Account Aggregator endpoints."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.portfolio import Portfolio
from app.models.user import User
from app.services.account_aggregator import (
    AAProvider,
    ConsentRequest,
    get_aa_provider,
    get_available_providers,
)
from app.services.backup_service import (
    export_portfolio_json,
    export_sqlite_backup,
    import_portfolio_json,
)
from app.services.csv_import_service import (
    generate_csv_template,
    generate_dividend_template,
    generate_mutual_fund_template,
    generate_tax_record_template,
    import_dividends,
    import_mutual_funds,
    import_tax_records,
    parse_csv,
    parse_csv_dividends,
    parse_csv_mutual_funds,
    parse_csv_tax_records,
)
from app.services.excel_service import (
    export_portfolio,
    generate_template,
    import_to_portfolio,
    parse_excel,
)
from app.services.export_service import (
    export_holdings_csv,
    export_transactions_csv,
    generate_portfolio_report_html,
)

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB
_EXCEL_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _verify_portfolio_ownership(
    portfolio_id: int, user: User, db: AsyncSession,
) -> Portfolio:
    """Ensure the portfolio exists and belongs to the user."""
    result = await db.execute(
        select(Portfolio).where(
            Portfolio.id == portfolio_id,
            Portfolio.user_id == user.id,
        )
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portfolio not found or does not belong to the current user",
        )
    return portfolio


async def _read_upload(file: UploadFile, allowed_exts: tuple[str, ...]) -> bytes:
    """Read and validate an uploaded file."""
    if file.filename and not file.filename.lower().endswith(allowed_exts):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only {', '.join(allowed_exts)} files are supported",
        )
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty",
        )
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size is {MAX_UPLOAD_SIZE // (1024 * 1024)} MB.",
        )
    return file_bytes


# ===========================================================================
# EXCEL IMPORT / EXPORT
# ===========================================================================

@router.post("/excel")
async def upload_excel(
    file: UploadFile, portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload and parse an Excel file, creating holdings and transactions."""
    await _verify_portfolio_ownership(portfolio_id, user, db)
    file_bytes = await _read_upload(file, (".xlsx",))

    try:
        parsed = parse_excel(file_bytes)
    except Exception as exc:
        logger.warning("Excel parse failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to parse Excel file. Please check the format.",
        )

    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid data rows found in the uploaded file",
        )

    summary = await import_to_portfolio(parsed, portfolio_id, db)
    return {"status": "success", "rows_parsed": len(parsed), **summary}


@router.get("/export/excel/{portfolio_id}")
async def export_excel(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export a portfolio's holdings and transactions to an Excel file."""
    await _verify_portfolio_ownership(portfolio_id, user, db)
    try:
        excel_bytes = await export_portfolio(portfolio_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return Response(
        content=excel_bytes,
        media_type=_EXCEL_CONTENT_TYPE,
        headers={"Content-Disposition": f"attachment; filename=portfolio_{portfolio_id}.xlsx"},
    )


@router.get("/export/template")
async def download_template(user: User = Depends(get_current_user)) -> Response:
    """Download a blank Excel template for importing data."""
    return Response(
        content=generate_template(),
        media_type=_EXCEL_CONTENT_TYPE,
        headers={"Content-Disposition": "attachment; filename=finance_tracker_template.xlsx"},
    )


# ===========================================================================
# CSV IMPORT / EXPORT
# ===========================================================================

@router.post("/csv")
async def upload_csv(
    file: UploadFile, portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload a CSV file to import holdings and transactions."""
    await _verify_portfolio_ownership(portfolio_id, user, db)
    file_bytes = await _read_upload(file, (".csv",))

    try:
        parsed = parse_csv(file_bytes)
    except Exception as exc:
        logger.warning("CSV parse failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to parse CSV file. Please check the format.",
        )

    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid data rows found in the uploaded file",
        )

    summary = await import_to_portfolio(parsed, portfolio_id, db)
    return {"status": "success", "rows_parsed": len(parsed), **summary}


@router.get("/export/template/csv")
async def download_csv_template(user: User = Depends(get_current_user)) -> Response:
    """Download a blank CSV template for importing holdings/transactions."""
    return Response(
        content=generate_csv_template(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=finance_tracker_template.csv"},
    )


@router.get("/export/csv/{portfolio_id}")
async def export_csv(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export portfolio holdings as a CSV file."""
    await _verify_portfolio_ownership(portfolio_id, user, db)
    try:
        csv_content = await export_holdings_csv(portfolio_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=holdings_{portfolio_id}.csv"},
    )


@router.get("/export/csv/{portfolio_id}/transactions")
async def export_transactions_csv_route(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export all transactions for a portfolio as a CSV file."""
    await _verify_portfolio_ownership(portfolio_id, user, db)
    try:
        csv_content = await export_transactions_csv(portfolio_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=transactions_{portfolio_id}.csv"},
    )


# ===========================================================================
# CSV IMPORT — DIVIDENDS, MUTUAL FUNDS, TAX RECORDS
# ===========================================================================

@router.post("/csv/dividends")
async def upload_csv_dividends(
    file: UploadFile, portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload a CSV file to import dividend records."""
    await _verify_portfolio_ownership(portfolio_id, user, db)
    file_bytes = await _read_upload(file, (".csv",))

    parsed = parse_csv_dividends(file_bytes)
    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid dividend rows found in the uploaded file",
        )

    summary = await import_dividends(parsed, portfolio_id, db)
    return {"status": "success", "rows_parsed": len(parsed), **summary}


@router.post("/csv/mutual-funds")
async def upload_csv_mutual_funds(
    file: UploadFile, portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload a CSV file to import mutual fund records."""
    await _verify_portfolio_ownership(portfolio_id, user, db)
    file_bytes = await _read_upload(file, (".csv",))

    parsed = parse_csv_mutual_funds(file_bytes)
    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid mutual fund rows found in the uploaded file",
        )

    summary = await import_mutual_funds(parsed, portfolio_id, db)
    return {"status": "success", "rows_parsed": len(parsed), **summary}


@router.post("/csv/tax-records")
async def upload_csv_tax_records(
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload a CSV file to import tax records (user-level, no portfolio needed)."""
    file_bytes = await _read_upload(file, (".csv",))

    parsed = parse_csv_tax_records(file_bytes)
    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid tax record rows found in the uploaded file",
        )

    summary = await import_tax_records(parsed, user.id, db)
    return {"status": "success", "rows_parsed": len(parsed), **summary}


@router.get("/export/template/dividends")
async def download_dividend_template(user: User = Depends(get_current_user)) -> Response:
    """Download a blank CSV template for importing dividends."""
    return Response(
        content=generate_dividend_template(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=dividend_template.csv"},
    )


@router.get("/export/template/mutual-funds")
async def download_mutual_fund_template(user: User = Depends(get_current_user)) -> Response:
    """Download a blank CSV template for importing mutual funds."""
    return Response(
        content=generate_mutual_fund_template(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=mutual_fund_template.csv"},
    )


@router.get("/export/template/tax-records")
async def download_tax_record_template(user: User = Depends(get_current_user)) -> Response:
    """Download a blank CSV template for importing tax records."""
    return Response(
        content=generate_tax_record_template(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=tax_record_template.csv"},
    )


# ===========================================================================
# JSON BACKUP / RESTORE
# ===========================================================================

@router.get("/export/json/{portfolio_id}")
async def export_json(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export a full portfolio backup as JSON (includes all related data)."""
    await _verify_portfolio_ownership(portfolio_id, user, db)

    try:
        data = await export_portfolio_json(portfolio_id, user.id, db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    content = json.dumps(data, indent=2, ensure_ascii=False)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=portfolio_{portfolio_id}_backup.json"},
    )


@router.post("/json")
async def upload_json(
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Restore a portfolio from a JSON backup file."""
    file_bytes = await _read_upload(file, (".json",))

    try:
        data = json.loads(file_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON file: {exc}",
        )

    try:
        summary = await import_portfolio_json(data, user.id, db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return {"status": "success", **summary}


# ===========================================================================
# PDF EXPORT
# ===========================================================================

@router.get("/export/pdf/{portfolio_id}")
async def export_pdf(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export a portfolio report as a PDF file."""
    await _verify_portfolio_ownership(portfolio_id, user, db)
    user_name = user.display_name or user.email

    try:
        from app.services.export_service import generate_portfolio_pdf

        pdf_bytes = await generate_portfolio_pdf(portfolio_id, user_name, db)
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="PDF export requires xhtml2pdf. Install with: pip install xhtml2pdf",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=portfolio_{portfolio_id}_report.pdf"},
    )


# ===========================================================================
# HTML REPORT
# ===========================================================================

@router.get("/export/report/{portfolio_id}")
async def export_report(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Generate a styled HTML portfolio report (can be printed to PDF in browser)."""
    await _verify_portfolio_ownership(portfolio_id, user, db)
    user_name = user.display_name or user.email

    try:
        html = await generate_portfolio_report_html(portfolio_id, user_name, db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return HTMLResponse(content=html)


# ===========================================================================
# SQLITE DATABASE BACKUP
# ===========================================================================

@router.get("/export/backup/sqlite")
async def export_sqlite(user: User = Depends(get_current_user)) -> Response:
    """Download a copy of the SQLite database file (SQLite deployments only)."""
    db_bytes = await export_sqlite_backup()
    if db_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="SQLite backup is only available when using SQLite. "
            "For PostgreSQL, use pg_dump.",
        )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(
        content=db_bytes,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename=finance_tracker_backup_{ts}.db"},
    )


# ===========================================================================
# ACCOUNT AGGREGATOR (AA) ENDPOINTS
# ===========================================================================

class AAConsentBody(BaseModel):
    """Request body for initiating AA consent."""
    provider: str


@router.get("/aa/providers")
async def list_aa_providers(user: User = Depends(get_current_user)) -> list[dict]:
    """List available Account Aggregator providers and their status."""
    return await get_available_providers()


@router.post("/aa/consent")
async def initiate_aa_consent(
    body: AAConsentBody, user: User = Depends(get_current_user),
) -> dict:
    """Initiate consent flow with an Account Aggregator provider."""
    try:
        provider = AAProvider(body.provider)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown AA provider: {body.provider}. "
            f"Available: {[p.value for p in AAProvider]}",
        )

    svc = get_aa_provider(provider)
    if not svc.is_available():
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Account Aggregator integration with {provider.value} is coming soon.",
        )

    request = ConsentRequest(provider=provider, user_id=user.id)
    try:
        response = await svc.initiate_consent(request)
    except NotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc))

    return {
        "consent_id": response.consent_id,
        "status": response.status.value,
        "redirect_url": response.redirect_url,
        "expires_at": response.expires_at.isoformat() if response.expires_at else None,
    }


@router.get("/aa/consent/{consent_id}/status")
async def check_aa_consent_status(
    consent_id: str, user: User = Depends(get_current_user),
) -> dict:
    """Check AA consent status (stub — requires provider registration)."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Consent status checking is not yet implemented.",
    )
