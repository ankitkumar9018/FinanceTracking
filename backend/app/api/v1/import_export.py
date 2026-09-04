"""Excel, CSV, JSON, PDF import / export, backup, and Account Aggregator endpoints."""

from __future__ import annotations

import csv
import io
import json
import logging
from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, verify_portfolio_ownership
from app.api.errors import map_value_error
from app.database import get_db
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
    export_everything_zip,
    export_holdings_csv,
    export_transactions_csv,
    export_workbook_xlsx,
    generate_portfolio_report_html,
)
from app.services.ofx_qif_import_service import (
    import_statement,
    parse_ofx,
    parse_qif,
    split_cash_rows,
)

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB
_UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1 MB
_EXCEL_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


async def _report_ai_summary(user_id: int, db: AsyncSession) -> str | None:
    """Best-effort AI summary text for the report/PDF routes.

    The service already handles provider absence, timeouts, and errors by
    returning None; the extra guard here guarantees the export itself can
    never fail because of the AI section.
    """
    try:
        from app.services.ai_digest_service import generate_report_summary

        return await generate_report_summary(user_id, db)
    except Exception:
        logger.warning("AI report summary failed — exporting without it", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _read_upload(file: UploadFile, allowed_exts: tuple[str, ...]) -> bytes:
    """Read and validate an uploaded file.

    Reads the upload in chunks and aborts with 413 as soon as the running total
    exceeds ``MAX_UPLOAD_SIZE`` — so an oversized upload is never fully buffered
    into memory before being rejected.
    """
    if file.filename and not file.filename.lower().endswith(allowed_exts):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only {', '.join(allowed_exts)} files are supported",
        )

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_UPLOAD_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File too large. Maximum size is {MAX_UPLOAD_SIZE // (1024 * 1024)} MB.",
            )
        chunks.append(chunk)

    file_bytes = b"".join(chunks)
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty",
        )
    return file_bytes


def _parse_upload(
    parser: Callable[[bytes], list[dict]], file_bytes: bytes, *, kind: str
) -> list[dict]:
    """Run an import parser, mapping any parse failure to an actionable 400.

    Parsers raise a spread of low-level errors on malformed input — ``_csv.Error``
    ("field larger than field limit") on an over-long quoted field, openpyxl's
    ``BadZipFile`` on a mis-named upload, ``AttributeError``/``TypeError`` deeper
    in — and the app registers no catch-all handler, so anything not caught here
    reaches the user as a bare 500 plus a traceback in the log.
    """
    try:
        return parser(file_bytes)
    except Exception as exc:
        logger.warning("%s parse failed: %s", kind, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse {kind} file. Please check the format.",
        ) from exc


def _count_csv_data_rows(file_bytes: bytes) -> int | None:
    """Count the non-empty data rows (header excluded) in an uploaded CSV.

    Used only to tell the user how many rows the parser dropped. Decoding is
    deliberately lossy (``errors="replace"``) because delimiters and quotes are
    ASCII in every encoding the importer accepts, so the row structure survives
    even when a byte does not. Returns ``None`` when the file cannot be counted
    at all — the caller then simply omits the skipped-row report.
    """
    try:
        reader = csv.reader(io.StringIO(file_bytes.decode("utf-8-sig", errors="replace")))
        if next(reader, None) is None:
            return 0
        return sum(
            1 for row in reader
            if any(str(cell).strip() for cell in row if cell is not None)
        )
    except Exception:
        logger.debug("Could not count CSV data rows for the skip report", exc_info=True)
        return None


def _row_report(rows_parsed: int, rows_read: int | None, *, noun: str = "rows") -> dict:
    """Build the row-accounting part of an import response.

    The parsers drop unusable rows with a log warning and return only the
    survivors, so ``rows_parsed`` alone cannot distinguish "imported all 400
    trades" from "imported 10 of 400". Reporting what was read and what was
    skipped — plus a plain-language warning — is what makes a partial import
    visible instead of a green "Import Successful".
    """
    report: dict = {"rows_parsed": rows_parsed}
    if rows_read is None or rows_read < rows_parsed:
        return report
    report["rows_read"] = rows_read
    report["rows_skipped"] = rows_read - rows_parsed
    if report["rows_skipped"]:
        report["warning"] = (
            f"{report['rows_skipped']} of {rows_read} {noun} could not be read "
            "and were skipped (missing required fields, an unrecognised date, "
            "or a non-numeric amount). Check the file against the template."
        )
    return report


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
    await verify_portfolio_ownership(portfolio_id, user, db)
    file_bytes = await _read_upload(file, (".xlsx",))

    parsed = _parse_upload(parse_excel, file_bytes, kind="Excel")

    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid data rows found in the uploaded file",
        )

    summary = await import_to_portfolio(parsed, portfolio_id, db, source="EXCEL")
    return {"status": "success", "rows_parsed": len(parsed), **summary}


@router.get("/export/excel/{portfolio_id}")
async def export_excel(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export a portfolio's holdings and transactions to an Excel file."""
    await verify_portfolio_ownership(portfolio_id, user, db)
    try:
        excel_bytes = await export_portfolio(portfolio_id, db)
    except ValueError as exc:
        raise map_value_error(exc) from exc

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


@router.get("/export/xlsx/{portfolio_id}")
async def export_xlsx_workbook(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export a multi-sheet workbook (Holdings, Transactions, Dividends, Summary)."""
    await verify_portfolio_ownership(portfolio_id, user, db)
    try:
        workbook_bytes = await export_workbook_xlsx(portfolio_id, db)
    except ValueError as exc:
        raise map_value_error(exc) from exc

    return Response(
        content=workbook_bytes,
        media_type=_EXCEL_CONTENT_TYPE,
        headers={
            "Content-Disposition": (
                f"attachment; filename=portfolio_{portfolio_id}_workbook.xlsx"
            )
        },
    )


@router.get("/export/bundle/{portfolio_id}")
async def export_bundle(
    portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export everything (CSVs, JSON backup, HTML report, XLSX, best-effort PDF) as a ZIP."""
    await verify_portfolio_ownership(portfolio_id, user, db)
    user_name = user.display_name or user.email
    try:
        zip_bytes = await export_everything_zip(portfolio_id, user_name, db)
    except ValueError as exc:
        raise map_value_error(exc) from exc

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f"attachment; filename=portfolio_{portfolio_id}_export.zip"
            )
        },
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
    await verify_portfolio_ownership(portfolio_id, user, db)
    file_bytes = await _read_upload(file, (".csv",))

    parsed = _parse_upload(parse_csv, file_bytes, kind="CSV")

    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid data rows found in the uploaded file",
        )

    summary = await import_to_portfolio(parsed, portfolio_id, db, source="CSV")
    return {
        "status": "success",
        **_row_report(len(parsed), _count_csv_data_rows(file_bytes)),
        **summary,
    }


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
    await verify_portfolio_ownership(portfolio_id, user, db)
    try:
        csv_content = await export_holdings_csv(portfolio_id, db)
    except ValueError as exc:
        raise map_value_error(exc) from exc

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
    await verify_portfolio_ownership(portfolio_id, user, db)
    try:
        csv_content = await export_transactions_csv(portfolio_id, db)
    except ValueError as exc:
        raise map_value_error(exc) from exc

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
    await verify_portfolio_ownership(portfolio_id, user, db)
    file_bytes = await _read_upload(file, (".csv",))

    parsed = _parse_upload(parse_csv_dividends, file_bytes, kind="dividend CSV")
    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid dividend rows found in the uploaded file",
        )

    summary = await import_dividends(parsed, portfolio_id, db)
    return {
        "status": "success",
        **_row_report(
            len(parsed), _count_csv_data_rows(file_bytes), noun="dividend rows"
        ),
        **summary,
    }


@router.post("/csv/mutual-funds")
async def upload_csv_mutual_funds(
    file: UploadFile, portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload a CSV file to import mutual fund records."""
    await verify_portfolio_ownership(portfolio_id, user, db)
    file_bytes = await _read_upload(file, (".csv",))

    parsed = _parse_upload(
        parse_csv_mutual_funds, file_bytes, kind="mutual fund CSV"
    )
    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid mutual fund rows found in the uploaded file",
        )

    summary = await import_mutual_funds(parsed, portfolio_id, db)
    return {
        "status": "success",
        **_row_report(
            len(parsed), _count_csv_data_rows(file_bytes), noun="mutual fund rows"
        ),
        **summary,
    }


@router.post("/csv/tax-records")
async def upload_csv_tax_records(
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload a CSV file to import tax records (user-level, no portfolio needed)."""
    file_bytes = await _read_upload(file, (".csv",))

    parsed = _parse_upload(
        parse_csv_tax_records, file_bytes, kind="tax record CSV"
    )
    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid tax record rows found in the uploaded file",
        )

    summary = await import_tax_records(parsed, user.id, db)
    return {
        "status": "success",
        **_row_report(
            len(parsed), _count_csv_data_rows(file_bytes), noun="tax record rows"
        ),
        **summary,
    }


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
# OFX / QIF / CAS STATEMENT IMPORT
# ===========================================================================

async def _import_statement_upload(
    parsed: list[dict], portfolio_id: int, db: AsyncSession, *, fmt: str
) -> dict:
    """Import parsed OFX/QIF rows, refusing a statement that is all cash.

    Bank lines carry a payee, not a security (see
    ``ofx_qif_import_service.split_cash_rows``). A file with nothing else is a
    bank statement, not a broker statement: importing it would create one junk
    holding per payee, so it is rejected with an explanation instead.
    """
    investment_rows, cash_rows = split_cash_rows(parsed)
    if not investment_rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"This {fmt} file contains only bank/cash transactions "
                f"({len(cash_rows)} line(s)) and no investment trades. A cash "
                "movement is a payee, not a position — importing it would add one "
                "holding per payee and inflate Total Invested. Upload a broker "
                "statement with buy/sell transactions instead."
            ),
        )

    summary = await import_statement(parsed, portfolio_id, db, source=fmt)
    result = {
        "status": "success",
        "rows_parsed": len(investment_rows),
        "rows_read": len(parsed),
        **summary,
    }
    if cash_rows:
        result["warning"] = (
            f"{len(cash_rows)} bank/cash line(s) were read but not imported — a "
            "cash movement is a payee, not a security, so it is not a holding."
        )
    return result


@router.post("/import/ofx")
async def import_ofx_statement(
    file: UploadFile, portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Import an OFX/QFX broker or bank statement into a portfolio."""
    await verify_portfolio_ownership(portfolio_id, user, db)
    file_bytes = await _read_upload(file, (".ofx", ".qfx"))

    parsed = _parse_upload(parse_ofx, file_bytes, kind="OFX")

    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid rows found in the OFX file",
        )

    return await _import_statement_upload(parsed, portfolio_id, db, fmt="OFX")


@router.post("/import/qif")
async def import_qif_statement(
    file: UploadFile, portfolio_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Import a QIF statement into a portfolio."""
    await verify_portfolio_ownership(portfolio_id, user, db)
    file_bytes = await _read_upload(file, (".qif",))

    parsed = _parse_upload(parse_qif, file_bytes, kind="QIF")

    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid rows found in the QIF file",
        )

    return await _import_statement_upload(parsed, portfolio_id, db, fmt="QIF")


@router.post("/import/cas")
async def import_cas_statement(
    file: UploadFile, portfolio_id: int, password: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Import a CAMS/KFintech CAS PDF (mutual funds) into a portfolio.

    Requires the optional ``casparser`` package (``mf`` extra). Missing package
    → 501; parse/decrypt failures → 400.
    """
    await verify_portfolio_ownership(portfolio_id, user, db)
    file_bytes = await _read_upload(file, (".pdf",))

    # casparser is optional — keep the import function-local so the app boots
    # without it (mirrors the PDF-export ImportError handling).
    try:
        from app.services.cas_import_service import parse_cas

        parsed = parse_cas(file_bytes, password)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)
        )
    except Exception as exc:
        logger.warning("CAS parse failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to parse CAS PDF. Please check the file and password.",
        )

    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No mutual fund holdings found in the CAS statement",
        )

    summary = await import_mutual_funds(parsed, portfolio_id, db)
    return {"status": "success", "rows_parsed": len(parsed), **summary}


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
    await verify_portfolio_ownership(portfolio_id, user, db)

    try:
        data = await export_portfolio_json(portfolio_id, user.id, db)
    except ValueError as exc:
        raise map_value_error(exc) from exc

    content = json.dumps(data, indent=2, ensure_ascii=False)
    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f"attachment; filename=portfolio_{portfolio_id}_backup.json"
            )
        },
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
        raise map_value_error(exc) from exc
    except KeyError as exc:
        # The restorer indexes required keys directly (h_data["stock_symbol"],
        # tx_data["price"], …), so a hand-edited or truncated backup would
        # otherwise surface as a bare 500.
        logger.warning("JSON backup is missing a required field: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Malformed backup file: missing required field {exc}.",
        ) from exc
    except TypeError as exc:
        logger.warning("JSON backup has a field of the wrong type: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Malformed backup file: a field has the wrong type "
                "(expected a number, date or object)."
            ),
        ) from exc

    return {"status": "success", **summary}


# ===========================================================================
# PDF EXPORT
# ===========================================================================

@router.get("/export/pdf/{portfolio_id}")
async def export_pdf(
    portfolio_id: int,
    ai_summary: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export a portfolio report as a PDF file.

    ``ai_summary=true`` adds a best-effort AI-generated summary section; any
    AI failure/timeout simply exports the PDF without it.
    """
    await verify_portfolio_ownership(portfolio_id, user, db)
    user_name = user.display_name or user.email

    ai_text = await _report_ai_summary(user.id, db) if ai_summary else None

    try:
        from app.services.export_service import generate_portfolio_pdf

        pdf_bytes = await generate_portfolio_pdf(
            portfolio_id, user_name, db, ai_summary=ai_text
        )
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="PDF export requires xhtml2pdf. Install with: pip install xhtml2pdf",
        )
    except ValueError as exc:
        raise map_value_error(exc) from exc

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f"attachment; filename=portfolio_{portfolio_id}_report.pdf"
            )
        },
    )


# ===========================================================================
# HTML REPORT
# ===========================================================================

@router.get("/export/report/{portfolio_id}")
async def export_report(
    portfolio_id: int,
    ai_summary: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Generate a styled HTML portfolio report (can be printed to PDF in browser).

    ``ai_summary=true`` adds a best-effort AI-generated summary section; any
    AI failure/timeout simply renders the report without it.
    """
    await verify_portfolio_ownership(portfolio_id, user, db)
    user_name = user.display_name or user.email

    ai_text = await _report_ai_summary(user.id, db) if ai_summary else None

    try:
        html = await generate_portfolio_report_html(
            portfolio_id, user_name, db, ai_summary=ai_text
        )
    except ValueError as exc:
        raise map_value_error(exc) from exc

    return HTMLResponse(content=html)


# ===========================================================================
# SQLITE DATABASE BACKUP
# ===========================================================================

@router.get("/export/backup/sqlite")
async def export_sqlite(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Download a copy of the SQLite database file (SQLite deployments only).

    The raw file contains every user's data (password hashes, TOTP secrets,
    encrypted broker credentials), so it is restricted to the instance owner —
    the first-registered account. Other users can use the scoped JSON export.
    """
    owner_id = (await db.execute(select(func.min(User.id)))).scalar()
    if owner_id is not None and user.id != owner_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Full-database backup is restricted to the instance owner. "
            "Use the JSON export for your own data.",
        )
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
