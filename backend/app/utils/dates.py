"""Shared date parsing helpers.

:func:`parse_date` is the flexible single-value parser extracted from
``app.services.csv_import_service._parse_date`` (same format list), extended
with an explicit ``dayfirst`` toggle plus a month-first fallback so callers
that know their file's convention (see :func:`infer_dayfirst`) can parse
unambiguously.
"""

from __future__ import annotations

import re
from datetime import date, datetime

__all__ = ["infer_dayfirst", "parse_date"]

_ISO_FMT = "%Y-%m-%d"
_DAYFIRST_FMTS = ("%d/%m/%Y", "%d-%m-%Y")
_MONTHFIRST_FMTS = ("%m/%d/%Y", "%m-%d-%Y")
# Textual month, e.g. "Jan 15, 2024" (ported from csv_import_service).
_TEXTUAL_FMTS = ("%b %d, %Y",)

_COMPONENT_SPLIT = re.compile(r"[/-]")


def parse_date(value: object, *, dayfirst: bool = True) -> date | None:
    """Parse a date from a string, ``datetime``, ``pandas.Timestamp``, or
    ``date``; return ``None`` on failure.

    Strings are tried against ISO (``%Y-%m-%d``) first, then the day-first
    formats (``%d/%m/%Y``, ``%d-%m-%Y``) when ``dayfirst`` is true (the
    month-first equivalents otherwise), then the other order as a fallback,
    and finally textual forms like ``"Jan 15, 2024"``.

    ``pandas.Timestamp`` is a ``datetime`` subclass, so it is handled by the
    ``datetime`` branch without importing pandas here.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    s = str(value).strip()
    if not s or s in ("-", "N/A"):
        return None
    preferred, fallback = (
        (_DAYFIRST_FMTS, _MONTHFIRST_FMTS)
        if dayfirst
        else (_MONTHFIRST_FMTS, _DAYFIRST_FMTS)
    )
    for fmt in (_ISO_FMT, *preferred, *fallback, *_TEXTUAL_FMTS):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def infer_dayfirst(date_strings: list[str]) -> bool | None:
    """Infer whether a batch of slash/dash-delimited date strings is
    day-first, so one convention can be applied per file (e.g. QIF import).

    Returns ``True`` if any string's *first* component exceeds 12 (must be a
    day), ``False`` if any *second* component exceeds 12, and ``None`` when
    every string is ambiguous.  First-component evidence wins over
    second-component evidence when a batch is internally inconsistent.
    Components above 31 (years, as in ISO ``2024-05-13``) carry no
    day-vs-month signal and are ignored.
    """
    saw_day_first = False
    saw_month_first = False
    for raw in date_strings:
        parts = _COMPONENT_SPLIT.split(str(raw).strip())
        if len(parts) < 2:
            continue
        try:
            first, second = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        if first > 31:
            # Year-first (ISO-style) — no positional day/month information.
            continue
        if 12 < first <= 31:
            saw_day_first = True
        if 12 < second <= 31:
            saw_month_first = True
    if saw_day_first:
        return True
    if saw_month_first:
        return False
    return None
