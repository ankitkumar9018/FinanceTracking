"""Tests for the shared utility modules extracted from duplicated service code.

Covers:
- ``app.utils.numbers`` — locale-aware ``parse_number`` (must stay
  behavior-identical to ``csv_import_service._safe_float``) and the plain
  ``coerce_float``.
- ``app.utils.dates`` — ``parse_date`` (ISO / day-first / month-first /
  datetime / pandas.Timestamp) and ``infer_dayfirst``.
- ``app.utils.concurrency`` — ``bounded_thread_map`` / ``gather_bounded``
  ordering, error swallowing, and the timeout-starts-after-acquire fix.
- ``app.services.valuation`` — ``market_value`` fallback semantics,
  ``invested_value``.
- ``app.core.markets`` — ``ticker_symbol`` behavior parity and the
  value-identical-superset guarantee versus every service-local map.
"""

from __future__ import annotations

import asyncio
import time
from datetime import date, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from app.core import markets
from app.services import forex_service, tax_service
from app.services.csv_import_service import _parse_date as csv_parse_date
from app.services.csv_import_service import _safe_float as csv_safe_float
from app.services.market_data_service import _EXCHANGE_SUFFIX, _ticker_symbol
from app.services.valuation import invested_value, market_value
from app.utils.concurrency import bounded_thread_map, gather_bounded
from app.utils.dates import infer_dayfirst, parse_date
from app.utils.numbers import coerce_float, parse_number

# ---------------------------------------------------------------------------
# parse_number
# ---------------------------------------------------------------------------

PARSE_NUMBER_CASES = [
    # US format
    ("2500.00", 2500.00),
    ("1,234.56", 1234.56),
    ("1,234", 1234.0),
    ("1234.56", 1234.56),
    # European format
    ("1234,56", 1234.56),
    ("2.500,00", 2500.00),
    ("1.234.567,89", 1234567.89),
    ("1,5", 1.5),
    ("1.234.567", 1234567.0),
    # Currency symbols
    ("₹1,234.56", 1234.56),
    ("€1.234,56", 1234.56),
    ("$99.99", 99.99),
    ("£1 234,56", 1234.56),
    # Non-breaking space thousands separator
    ("1\xa0234,56", 1234.56),
    # Signs and plain values
    ("-1.234,56", -1234.56),
    ("-42", -42.0),
    ("0", 0.0),
]

PARSE_NUMBER_NONE_CASES = ["", "   ", "-", "N/A", "abc", "1.2.3,4,5", None]


class TestParseNumber:
    @pytest.mark.parametrize(("raw", "expected"), PARSE_NUMBER_CASES)
    def test_parses_locale_formats(self, raw, expected):
        assert parse_number(raw) == pytest.approx(expected)

    @pytest.mark.parametrize("raw", PARSE_NUMBER_NONE_CASES)
    def test_unparseable_returns_none(self, raw):
        assert parse_number(raw) is None

    def test_numeric_passthrough(self):
        assert parse_number(5) == 5.0
        assert parse_number(2.5) == 2.5
        assert parse_number(-3) == -3.0

    @pytest.mark.parametrize(
        "raw", [case[0] for case in PARSE_NUMBER_CASES] + PARSE_NUMBER_NONE_CASES
    )
    def test_matches_csv_import_behavior(self, raw):
        """parse_number must be drop-in identical to csv_import._safe_float."""
        assert parse_number(raw) == csv_safe_float(raw)


class TestCoerceFloat:
    def test_valid_values(self):
        assert coerce_float(3.14) == pytest.approx(3.14)
        assert coerce_float("3.14") == pytest.approx(3.14)
        assert coerce_float(7) == 7.0
        assert coerce_float("0") == 0.0

    def test_nan_and_inf_return_none(self):
        assert coerce_float(float("nan")) is None
        assert coerce_float(float("inf")) is None
        assert coerce_float(float("-inf")) is None
        assert coerce_float("nan") is None
        assert coerce_float("inf") is None

    def test_invalid_returns_none(self):
        assert coerce_float(None) is None
        assert coerce_float("abc") is None
        assert coerce_float("") is None
        assert coerce_float([1]) is None

    def test_no_locale_logic(self):
        # Unlike parse_number, grouped strings are rejected.
        assert coerce_float("1,234.56") is None
        assert coerce_float("1.234,56") is None


# ---------------------------------------------------------------------------
# parse_date / infer_dayfirst
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_iso(self):
        assert parse_date("2024-01-15") == date(2024, 1, 15)

    def test_dayfirst_slash_and_dash(self):
        assert parse_date("15/01/2024") == date(2024, 1, 15)
        assert parse_date("15-01-2024") == date(2024, 1, 15)

    def test_dayfirst_toggle(self):
        assert parse_date("03/04/2024", dayfirst=True) == date(2024, 4, 3)
        assert parse_date("03/04/2024", dayfirst=False) == date(2024, 3, 4)

    def test_other_order_fallback(self):
        # Day-first fails (no month 15) → month-first fallback kicks in.
        assert parse_date("01/15/2024", dayfirst=True) == date(2024, 1, 15)
        # Month-first fails → day-first fallback.
        assert parse_date("15/01/2024", dayfirst=False) == date(2024, 1, 15)

    def test_textual_format(self):
        assert parse_date("Jan 15, 2024") == date(2024, 1, 15)

    def test_datetime_and_date_passthrough(self):
        assert parse_date(datetime(2024, 1, 15, 10, 30)) == date(2024, 1, 15)
        assert parse_date(date(2024, 1, 15)) == date(2024, 1, 15)

    def test_pandas_timestamp(self):
        assert parse_date(pd.Timestamp("2024-01-15 09:15:00")) == date(2024, 1, 15)

    @pytest.mark.parametrize("raw", [None, "", "  ", "-", "N/A", "not a date", "32/01/2024"])
    def test_unparseable_returns_none(self, raw):
        assert parse_date(raw) is None

    @pytest.mark.parametrize("raw", ["2024-01-15", "15-01-2024", "15/01/2024", "Jan 15, 2024"])
    def test_matches_csv_import_on_its_formats(self, raw):
        assert parse_date(raw) == csv_parse_date(raw)


class TestInferDayfirst:
    def test_day_first_evidence(self):
        assert infer_dayfirst(["15/01/2024", "20/02/2024"]) is True
        assert infer_dayfirst(["13-05-2024"]) is True

    def test_month_first_evidence(self):
        assert infer_dayfirst(["01/15/2024"]) is False
        assert infer_dayfirst(["05-31-2024"]) is False

    def test_ambiguous(self):
        assert infer_dayfirst(["05/06/2024", "01/02/2024"]) is None
        assert infer_dayfirst([]) is None

    def test_iso_strings_carry_no_signal(self):
        assert infer_dayfirst(["2024-05-13"]) is None

    def test_garbage_ignored(self):
        assert infer_dayfirst(["abc", "??", "15/01/2024"]) is True

    def test_first_component_evidence_wins(self):
        # Inconsistent batch: any first component > 12 → day-first.
        assert infer_dayfirst(["05/13/2024", "13/05/2024"]) is True


# ---------------------------------------------------------------------------
# bounded_thread_map / gather_bounded
# ---------------------------------------------------------------------------

class TestBoundedThreadMap:
    async def test_ordering_preserved(self):
        def work(x: int) -> int:
            # Later items finish first to prove order comes from input.
            time.sleep(0.01 * (4 - x))
            return x * 10

        assert await bounded_thread_map(work, [1, 2, 3], limit=3) == [10, 20, 30]

    async def test_exception_becomes_none(self):
        def work(x: int) -> int:
            if x == 2:
                raise ValueError("boom")
            return x * 10

        assert await bounded_thread_map(work, [1, 2, 3], limit=2) == [10, None, 30]

    async def test_timeout_becomes_none(self):
        def work(x: str) -> str:
            if x == "slow":
                time.sleep(0.5)
            return x

        results = await bounded_thread_map(work, ["fast", "slow"], limit=2, timeout=0.1)
        assert results == ["fast", None]

    async def test_timeout_starts_after_semaphore_acquisition(self):
        """With limit=1, item 2 queues behind item 1.  Each item runs well
        under the timeout, but queue+run for item 2 exceeds it — under the
        buggy pattern (timer covering queue time) item 2 would time out.
        """
        def work(x: int) -> int:
            time.sleep(0.2)
            return x

        start = time.monotonic()
        results = await bounded_thread_map(work, [1, 2], limit=1, timeout=0.35)
        elapsed = time.monotonic() - start

        assert results == [1, 2]  # both succeed despite serialized execution
        # Sanity: execution really was serialized past the timeout window,
        # i.e. item 2's queue+run time exceeded 0.35s yet it did not time out.
        assert elapsed >= 0.35

    async def test_empty_input(self):
        assert await bounded_thread_map(lambda x: x, []) == []


class TestGatherBounded:
    async def test_ordering_preserved(self):
        def make(i: int):
            async def _coro() -> int:
                await asyncio.sleep(0.01 * (3 - i))
                return i

            return _coro

        assert await gather_bounded([make(0), make(1), make(2)], limit=3) == [0, 1, 2]

    async def test_exception_becomes_none(self):
        async def boom() -> str:
            raise RuntimeError("nope")

        async def ok() -> str:
            return "ok"

        assert await gather_bounded([boom, ok], limit=2) == [None, "ok"]

    async def test_timeout_becomes_none(self):
        async def slow() -> int:
            await asyncio.sleep(0.5)
            return 1

        async def fast() -> int:
            return 2

        assert await gather_bounded([slow, fast], limit=2, timeout=0.05) == [None, 2]

    async def test_no_timeout_by_default(self):
        async def slowish() -> str:
            await asyncio.sleep(0.05)
            return "done"

        assert await gather_bounded([slowish]) == ["done"]

    async def test_timeout_starts_after_semaphore_acquisition(self):
        async def work() -> bool:
            await asyncio.sleep(0.2)
            return True

        start = time.monotonic()
        results = await gather_bounded([work, work], limit=1, timeout=0.35)
        elapsed = time.monotonic() - start

        assert results == [True, True]
        assert elapsed >= 0.35

    async def test_limit_respected(self):
        active = 0
        peak = 0

        async def work() -> bool:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1
            return True

        assert await gather_bounded([work] * 6, limit=2) == [True] * 6
        assert peak <= 2


# ---------------------------------------------------------------------------
# valuation
# ---------------------------------------------------------------------------

def _holding(qty, current, avg):
    return SimpleNamespace(
        cumulative_quantity=qty, current_price=current, average_price=avg
    )


class TestMarketValue:
    def test_uses_current_price(self):
        assert market_value(_holding(10, 100.0, 90.0)) == pytest.approx(1000.0)

    def test_falls_back_to_average_price(self):
        # Matches drift_service/concentration_service._market_value semantics.
        assert market_value(_holding(10, None, 90.0)) == pytest.approx(900.0)

    def test_no_fallback_returns_none(self):
        assert market_value(_holding(10, None, 90.0), fallback_to_avg=False) is None

    def test_no_fallback_with_live_price_still_works(self):
        assert market_value(_holding(10, 100.0, 90.0), fallback_to_avg=False) == pytest.approx(
            1000.0
        )

    def test_zero_quantity(self):
        assert market_value(_holding(0, 100.0, 90.0)) == 0.0

    def test_missing_quantity_returns_none(self):
        assert market_value(_holding(None, 100.0, 90.0)) is None

    def test_all_prices_missing_returns_none(self):
        assert market_value(_holding(10, None, None)) is None


class TestInvestedValue:
    def test_basic(self):
        assert invested_value(_holding(10, 100.0, 90.0)) == pytest.approx(900.0)

    def test_zero_quantity(self):
        assert invested_value(_holding(0, 100.0, 90.0)) == 0.0

    def test_missing_fields_return_zero(self):
        assert invested_value(_holding(None, 100.0, 90.0)) == 0.0
        assert invested_value(_holding(10, 100.0, None)) == 0.0


# ---------------------------------------------------------------------------
# markets
# ---------------------------------------------------------------------------

class TestTickerSymbol:
    @pytest.mark.parametrize(
        ("symbol", "exchange", "expected"),
        [
            ("RELIANCE", "NSE", "RELIANCE.NS"),
            ("TCS", "BSE", "TCS.BO"),
            ("SAP", "XETRA", "SAP.DE"),
            ("AAPL", "NASDAQ", "AAPL"),
            ("JPM", "NYSE", "JPM"),
            ("TCS", "bse", "TCS.BO"),  # case-insensitive exchange
            ("FOO", "LSE", "FOO"),  # unknown exchange → no suffix
        ],
    )
    def test_suffix_mapping(self, symbol, exchange, expected):
        assert markets.ticker_symbol(symbol, exchange) == expected

    def test_none_exchange_passthrough(self):
        assert markets.ticker_symbol("AAPL", None) == "AAPL"
        assert markets.ticker_symbol("AAPL", "") == "AAPL"

    @pytest.mark.parametrize("index", ["^NSEI", "^BSESN", "^GDAXI", "^GSPC"])
    def test_index_symbols_pass_through(self, index):
        assert markets.ticker_symbol(index, None) == index
        assert markets.ticker_symbol(index, "NSE") == index

    @pytest.mark.parametrize(
        ("symbol", "exchange"),
        [
            ("RELIANCE", "NSE"),
            ("TCS", "BSE"),
            ("SAP", "XETRA"),
            ("AAPL", "NASDAQ"),
            ("JPM", "NYSE"),
            ("FOO", "LSE"),
            ("TCS", "nse"),
        ],
    )
    def test_parity_with_market_data_service(self, symbol, exchange):
        """Exact same behavior as the original for every stock-symbol input."""
        assert markets.ticker_symbol(symbol, exchange) == _ticker_symbol(symbol, exchange)


class TestExchangeMaps:
    def test_currency_superset_of_tax_service(self):
        for exchange, currency in tax_service.EXCHANGE_CURRENCY_MAP.items():
            assert markets.CURRENCY[exchange] == currency

    def test_currency_superset_of_forex_service(self):
        for exchange, currency in forex_service.EXCHANGE_CURRENCY_MAP.items():
            assert markets.CURRENCY[exchange] == currency

    def test_suffix_superset_of_market_data_service(self):
        for exchange, suffix in _EXCHANGE_SUFFIX.items():
            assert markets.YF_SUFFIX[exchange] == suffix

    def test_suffix_superset_of_tax_service(self):
        for exchange, suffix in tax_service._EXCHANGE_YF_SUFFIX.items():
            assert markets.YF_SUFFIX[exchange] == suffix

    def test_jurisdiction_superset_of_tax_service(self):
        for exchange, jurisdiction in tax_service.EXCHANGE_JURISDICTION_MAP.items():
            assert markets.JURISDICTION[exchange] == jurisdiction

    def test_jurisdiction_expected_values(self):
        assert markets.JURISDICTION["NSE"] == "IN"
        assert markets.JURISDICTION["BSE"] == "IN"
        assert markets.JURISDICTION["XETRA"] == "DE"
        assert markets.JURISDICTION["FRA"] == "DE"

    def test_fra_extension_is_consistent(self):
        assert markets.CURRENCY["FRA"] == "EUR"
