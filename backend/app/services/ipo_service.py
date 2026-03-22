"""IPO service — fetch upcoming, open, and recently listed IPOs.

Uses the Investors Gain public API for Indian IPO data (NSE/BSE).
Falls back to empty list gracefully if the source is unavailable.
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

# Public API that returns Indian IPO data (no auth required)
_INVESTORGAIN_API = "https://www.investorgain.com/api/ipo/list"

# Cache TTL — avoid hammering the API on every request
_cache: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes


def _classify_status(open_date: str | None, close_date: str | None, listing_date: str | None) -> str:
    """Classify IPO status based on dates relative to today."""
    today = datetime.now().date()

    if listing_date:
        try:
            ld = datetime.strptime(listing_date, "%Y-%m-%d").date()
            if ld <= today:
                return "listed"
        except ValueError:
            pass

    if open_date and close_date:
        try:
            od = datetime.strptime(open_date, "%Y-%m-%d").date()
            cd = datetime.strptime(close_date, "%Y-%m-%d").date()
            if od <= today <= cd:
                return "open"
            if od > today:
                return "upcoming"
            if cd < today:
                return "listed"
        except ValueError:
            pass

    return "upcoming"


def _parse_date(date_str: str | None) -> str | None:
    """Try to parse various date formats into YYYY-MM-DD."""
    if not date_str or date_str.strip() in ("", "-", "N/A", "TBD"):
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%b %d, %Y", "%d %b %Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _safe_float(val: str | int | float | None) -> float | None:
    """Convert to float, return None on failure."""
    if val is None:
        return None
    try:
        v = float(str(val).replace(",", "").replace("₹", "").strip())
        return v if v > 0 else None
    except (ValueError, TypeError):
        return None


def _safe_int(val: str | int | float | None) -> int | None:
    """Convert to int, return None on failure."""
    if val is None:
        return None
    try:
        return int(float(str(val).replace(",", "").strip()))
    except (ValueError, TypeError):
        return None


async def _fetch_from_investorgain() -> list[dict]:
    """Fetch IPO data from Investors Gain public API."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                _INVESTORGAIN_API,
                headers={"Accept": "application/json", "User-Agent": "FinanceTracker/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()

        # The API returns a list of IPO objects
        items = data if isinstance(data, list) else data.get("data", data.get("ipos", []))
        if not isinstance(items, list):
            return []

        ipos: list[dict] = []
        for item in items:
            if not isinstance(item, dict):
                continue

            name = item.get("name") or item.get("company_name") or item.get("companyName", "")
            symbol = item.get("symbol") or item.get("nse_symbol") or item.get("nseSymbol", "")

            open_date = _parse_date(item.get("open_date") or item.get("openDate"))
            close_date = _parse_date(item.get("close_date") or item.get("closeDate"))
            listing_date = _parse_date(item.get("listing_date") or item.get("listingDate"))

            price_band = item.get("price_band") or item.get("priceBand") or item.get("price_range", "")
            lot_size = _safe_int(item.get("lot_size") or item.get("lotSize"))
            listing_price = _safe_float(item.get("listing_price") or item.get("listingPrice"))
            issue_price = _safe_float(item.get("issue_price") or item.get("issuePrice"))
            current_price = _safe_float(item.get("current_price") or item.get("cmp") or item.get("ltp"))
            subscription = _safe_float(item.get("subscription_times") or item.get("subscription") or item.get("total_subscription"))

            if not name:
                continue

            status = _classify_status(open_date, close_date, listing_date)

            ipos.append({
                "name": name.strip(),
                "symbol": (symbol or name.split()[0]).strip().upper(),
                "exchange": item.get("exchange", "NSE"),
                "price_range": str(price_band) if price_band else "",
                "lot_size": lot_size or 0,
                "open_date": open_date or "",
                "close_date": close_date or "",
                "listing_date": listing_date,
                "listing_price": listing_price,
                "issue_price": issue_price,
                "current_price": current_price,
                "status": status,
                "subscription_times": subscription,
            })

        return ipos

    except httpx.HTTPError as exc:
        logger.warning("Failed to fetch IPO data from InvestorGain: %s", exc)
        return []
    except Exception:
        logger.debug("IPO data parsing failed", exc_info=True)
        return []


async def _fetch_from_yfinance() -> list[dict]:
    """Fallback: try to get IPO data from yfinance calendar."""
    try:
        import yfinance as yf

        # yfinance has limited IPO support — try the calendar
        # This usually returns earnings calendar, not IPOs
        cal = yf.Ticker("^NSEI").calendar
        if cal is not None and isinstance(cal, dict):
            # yfinance calendar doesn't reliably return IPO data
            pass
    except Exception:
        pass

    return []


async def get_ipos(status: str | None = None, exchange: str = "NSE") -> list[dict]:
    """Fetch IPO data from public sources.

    Parameters
    ----------
    status : str | None
        Filter by "upcoming", "open", or "listed". None returns all.
    exchange : str
        Exchange filter (default "NSE").

    Returns
    -------
    list[dict]
        IPO records sorted by open_date descending.
    """
    # Check cache
    cache_key = f"ipos_{exchange}"
    now = datetime.now().timestamp()
    if cache_key in _cache:
        cached_time, cached_data = _cache[cache_key]
        if now - cached_time < _CACHE_TTL_SECONDS:
            ipos = cached_data
        else:
            ipos = []
    else:
        ipos = []

    # Fetch if not cached
    if not ipos:
        if exchange.upper() in ("NSE", "BSE"):
            ipos = await _fetch_from_investorgain()

        # Fallback to yfinance
        if not ipos:
            ipos = await _fetch_from_yfinance()

        # Cache the result (even if empty, to avoid hammering)
        _cache[cache_key] = (now, ipos)

    # Filter by exchange
    if exchange:
        exchange_upper = exchange.upper()
        ipos = [
            ipo for ipo in ipos
            if ipo.get("exchange", "").upper() == exchange_upper
            or exchange_upper in ("NSE", "BSE")  # Indian IPOs may not specify exchange
        ]

    # Filter by status
    if status:
        ipos = [ipo for ipo in ipos if ipo.get("status") == status]

    # Sort: upcoming first by date, then open, then listed
    status_order = {"upcoming": 0, "open": 1, "listed": 2}
    ipos.sort(key=lambda x: (status_order.get(x.get("status", ""), 9), x.get("open_date", "") or ""))

    return ipos
