"""Follow-ups the audit remediation left as handoff notes.

Three defects, one per section:

1. ``import_tax_records`` grew an ``allow_duplicates`` escape hatch for the two
   brokers whose genuinely distinct disposals carry identical numbers — but the
   HTTP endpoint had no way to set it, so the hatch was unreachable from the
   app and such a file could only ever be half-imported.
2. The natural key for ``tax_records`` was defined twice with different
   rounding: the importer's tie-aware pair of scale-4 variants, and
   ``backup_service``'s plain ``round(float(x), 4)``.  The plain form misses a
   value stored by PostgreSQL (which rounds a tie half away from zero), so a
   restore silently re-inserted goals and tax records it had already seen —
   and a duplicated gain consumes the per-year s.112A / Sparer-Pauschbetrag
   allowance a later, real disposal then has to pay tax on.
3. Price updates were keyed on the TICKER ALONE.  A symbol listed on two
   exchanges (same ticker on NSE and on XETRA, different instruments in
   different currencies) therefore had one listing's update dropped by the
   dedup and the *other* listing's price fanned out to its holders — a wrong
   number on screen, not a redundant one.

Run with:
    cd backend && uv run pytest tests/test_wave4_followups.py -q
"""

from __future__ import annotations

from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketState

from app.api.ws.connection_manager import (
    ConnectionManager,
    format_subscription,
    parse_subscription,
)
from app.models.goal import Goal
from app.models.portfolio import Portfolio
from app.models.tax_record import TaxRecord
from app.models.user import User
from app.services.backup_service import export_portfolio_json, import_portfolio_json
from app.tasks import fetch_prices as fp
from app.utils.numbers import round4, round4_variants

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

HEADER = (
    "financial_year,tax_jurisdiction,gain_type,purchase_date,sale_date,"
    "purchase_price,sale_price,gain_amount,tax_amount,currency"
)
# One LTCG disposal.  Two brokers reporting two *different* sales with these
# same numbers is exactly what allow_duplicates exists for.
ROW = "2024-25,IN,LTCG,2023-01-15,2024-08-20,25000.00,35000.00,10000.00,1250.00,INR"

TAX_CSV = ("\n".join([HEADER, ROW]) + "\n").encode()
TAX_URL = "/api/v1/import-export/csv/tax-records"


def _tax_file() -> dict:
    """A fresh multipart payload (the bytes are consumed by each upload)."""
    return {"file": ("tax.csv", TAX_CSV, "text/csv")}


async def _make_user(db: AsyncSession, email: str) -> User:
    user = User(email=email, password_hash="x", display_name="Follow-up")
    db.add(user)
    await db.flush()
    return user


# ===========================================================================
# 1. The allow_duplicates escape hatch is reachable over HTTP
# ===========================================================================


class TestAllowDuplicatesIsWiredToTheEndpoint:
    async def test_upload_defaults_to_deduping(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        """Nothing changes for the ordinary caller: a re-upload is still a no-op."""
        first = await client.post(TAX_URL, files=_tax_file(), headers=auth_headers)
        second = await client.post(TAX_URL, files=_tax_file(), headers=auth_headers)

        assert first.json()["tax_records_created"] == 1
        assert second.json()["tax_records_created"] == 0
        assert second.json()["tax_records_skipped"] == 1

    async def test_allow_duplicates_true_imports_the_coincident_row(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        """The hatch has to be openable from the app, not just from Python."""
        first = await client.post(TAX_URL, files=_tax_file(), headers=auth_headers)
        assert first.json()["tax_records_created"] == 1

        second = await client.post(
            f"{TAX_URL}?allow_duplicates=true",
            files=_tax_file(),
            headers=auth_headers,
        )
        assert second.status_code == 200
        body = second.json()
        assert body["tax_records_created"] == 1
        assert body["tax_records_skipped"] == 0

        records = await client.get("/api/v1/tax/", headers=auth_headers)
        assert len(records.json()) == 2

    async def test_allow_duplicates_false_is_explicitly_honoured(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        """Passing the flag off must dedup, not merely be ignored."""
        await client.post(TAX_URL, files=_tax_file(), headers=auth_headers)
        second = await client.post(
            f"{TAX_URL}?allow_duplicates=false",
            files=_tax_file(),
            headers=auth_headers,
        )
        assert second.json()["tax_records_created"] == 0
        assert second.json()["tax_records_skipped"] == 1

    def test_flag_is_documented_as_a_query_parameter(self):
        """It is in the OpenAPI schema, so the UI can discover and send it."""
        from app.main import app

        params = app.openapi()["paths"][TAX_URL]["post"]["parameters"]
        flag = next(p for p in params if p["name"] == "allow_duplicates")
        assert flag["in"] == "query"
        assert flag["required"] is False
        assert flag["schema"]["default"] is False


# ===========================================================================
# 2. One tie-aware definition of the scale-4 natural key, shared by both
#    write paths into tax_records
# ===========================================================================


class TestSharedRound4:
    def test_a_tie_yields_both_backends_roundings(self):
        """2.50005 is 2.5001 on PostgreSQL and 2.5000 on SQLite — offer both."""
        variants = round4_variants(2.50005)
        assert [str(v) for v in variants] == ["2.5001", "2.5000"]
        # The canonical (first) form is the half-up one.
        assert str(round4(2.50005)) == "2.5001"

    def test_a_non_tie_yields_exactly_one_form(self):
        """No tie, no ambiguity — one variant, so lookups stay cheap."""
        assert round4_variants(1234.56789) == (round4(1234.56789),)
        assert len(round4_variants(1250.0)) == 1

    def test_none_and_unparseable_values_are_preserved(self):
        """A non-number must not collapse to None and collide with another."""
        assert round4_variants(None) == (None,)
        assert round4_variants("not a number") == ("not a number",)
        assert round4_variants("also not") != round4_variants("not a number")

    def test_a_stored_value_round_trips_to_itself(self):
        """Re-quantizing a scale-4 column value is the identity."""
        for stored in ("2.5001", "2.5000", "0.0000", "-3.7500"):
            assert str(round4(float(stored))) == stored

    def test_the_two_definitions_have_not_drifted_apart(self):
        """``csv_import_service`` still keys on exactly what the shared helper says.

        The two write paths dedup the same table; the moment their rounding
        disagrees, a row one path skips is a row the other duplicates.
        """
        from app.services import csv_import_service as cis

        for value in (
            None, 0, 1250.0, 2.50005, -2.50005, 1234.56789, 1e9 + 0.00005,
            "1250.50005", "not a number",
        ):
            assert cis._round4_variants(value) == round4_variants(value)
            assert cis._round4(value) == round4(value)


class TestBackupRestoreDedupsARoundingTie:
    """A restore must not re-insert a row PostgreSQL stored on the other side
    of a tie.  The stored value here is what ``numeric(18, 4)`` would hold for
    an incoming ``…0.50005`` (half away from zero); the backup carries the
    full-precision figure, as an export from the other backend does.
    """

    async def test_goal_on_a_tie_is_skipped_not_duplicated(self, db: AsyncSession):
        user = await _make_user(db, "tie-goal@example.com")
        portfolio = Portfolio(user_id=user.id, name="P", currency="INR")
        db.add(portfolio)
        await db.flush()
        db.add(Goal(
            user_id=user.id, name="Retirement", target_amount=1250.5001,
            current_amount=0.0, category="RETIREMENT",
        ))
        await db.flush()

        backup = await export_portfolio_json(portfolio.id, user.id, db)
        backup["goals"][0]["target_amount"] = 1250.50005

        summary = await import_portfolio_json(backup, user.id, db)

        assert summary["goals"] == 0
        assert summary["goals_skipped"] == 1
        goals = (await db.execute(
            select(Goal).where(Goal.user_id == user.id)
        )).scalars().all()
        assert len(goals) == 1

    async def test_tax_record_on_a_tie_is_skipped_not_duplicated(
        self, db: AsyncSession
    ):
        user = await _make_user(db, "tie-tax@example.com")
        portfolio = Portfolio(user_id=user.id, name="P", currency="INR")
        db.add(portfolio)
        await db.flush()
        db.add(TaxRecord(
            user_id=user.id, financial_year="2024-25", tax_jurisdiction="IN",
            gain_type="LTCG", purchase_date=date(2023, 1, 15),
            sale_date=date(2024, 8, 20), purchase_price=25000.5001,
            sale_price=35000.0, gain_amount=9999.5001, tax_amount=1250.0,
            currency="INR",
        ))
        await db.flush()

        backup = await export_portfolio_json(portfolio.id, user.id, db)
        backup["tax_records"][0]["purchase_price"] = 25000.50005
        backup["tax_records"][0]["gain_amount"] = 9999.50005

        summary = await import_portfolio_json(backup, user.id, db)

        assert summary["tax_records"] == 0
        assert summary["tax_records_skipped"] == 1
        records = (await db.execute(
            select(TaxRecord).where(TaxRecord.user_id == user.id)
        )).scalars().all()
        assert len(records) == 1

    async def test_a_genuinely_different_amount_still_restores(
        self, db: AsyncSession
    ):
        """Widening the match must not start swallowing real new rows."""
        user = await _make_user(db, "tie-distinct@example.com")
        portfolio = Portfolio(user_id=user.id, name="P", currency="INR")
        db.add(portfolio)
        await db.flush()
        db.add(Goal(
            user_id=user.id, name="Retirement", target_amount=1250.5001,
            current_amount=0.0, category="RETIREMENT",
        ))
        await db.flush()

        backup = await export_portfolio_json(portfolio.id, user.id, db)
        backup["goals"][0]["target_amount"] = 1250.7500

        summary = await import_portfolio_json(backup, user.id, db)
        assert summary["goals"] == 1
        assert summary["goals_skipped"] == 0


# ===========================================================================
# 3. Price fan-out is keyed on (symbol, exchange), not the ticker alone
# ===========================================================================


class _FakeWebSocket:
    """Minimal stand-in for a starlette WebSocket in manager unit tests."""

    def __init__(self) -> None:
        self.client_state = WebSocketState.CONNECTED
        self.sent: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.client_state = WebSocketState.DISCONNECTED


def _register(mgr: ConnectionManager, user_id: int, *symbols: object):
    """Register a connected socket subscribed to *symbols*."""
    from app.api.ws.connection_manager import ConnectionInfo

    ws = _FakeWebSocket()
    mgr._connections[ws] = ConnectionInfo(user_id=user_id)  # type: ignore[index]
    mgr.subscribe(ws, list(symbols))  # type: ignore[arg-type]
    return ws


class TestSubscriptionKeyParsing:
    @pytest.mark.parametrize(
        ("entry", "expected"),
        [
            ("RELIANCE", ("RELIANCE", None)),
            ("  reliance  ", ("RELIANCE", None)),
            ("RELIANCE:NSE", ("RELIANCE", "NSE")),
            ("reliance:xetra", ("RELIANCE", "XETRA")),
            ("RELIANCE:", ("RELIANCE", None)),
            ({"symbol": "RELIANCE", "exchange": "NSE"}, ("RELIANCE", "NSE")),
            ({"symbol": "reliance"}, ("RELIANCE", None)),
        ],
    )
    def test_entries_normalise_to_a_symbol_exchange_pair(self, entry, expected):
        assert parse_subscription(entry) == expected

    @pytest.mark.parametrize("entry", ["", "   ", ":NSE", {"exchange": "NSE"}, {}])
    def test_an_entry_without_a_symbol_is_dropped(self, entry):
        """An unmatchable key would sit in the registry forever."""
        assert parse_subscription(entry) is None

    def test_the_wire_form_round_trips(self):
        for text in ("RELIANCE", "RELIANCE:NSE"):
            assert format_subscription(parse_subscription(text)) == text


class TestBroadcastIsPerListing:
    async def test_one_exchanges_price_never_reaches_the_others_holders(self):
        """The bug: same ticker, two exchanges, one (wrong) price for both."""
        mgr = ConnectionManager()
        nse = _register(mgr, 1, "ACME:NSE")
        xetra = _register(mgr, 2, "ACME:XETRA")

        await mgr.broadcast_price_update("ACME", {"current_price": 1500.0}, "NSE")

        assert len(nse.sent) == 1
        assert nse.sent[0]["symbol"] == "ACME"
        assert nse.sent[0]["exchange"] == "NSE"
        assert nse.sent[0]["data"]["current_price"] == 1500.0
        assert xetra.sent == []

        await mgr.broadcast_price_update("ACME", {"current_price": 42.0}, "XETRA")
        assert len(xetra.sent) == 1
        assert xetra.sent[0]["data"]["current_price"] == 42.0
        assert len(nse.sent) == 1  # unchanged

    async def test_a_bare_symbol_subscription_still_gets_every_listing(self):
        """Back-compat: an unqualified subscription means "any exchange"."""
        mgr = ConnectionManager()
        anywhere = _register(mgr, 1, "ACME")

        await mgr.broadcast_price_update("ACME", {"current_price": 1.0}, "NSE")
        await mgr.broadcast_price_update("ACME", {"current_price": 2.0}, "XETRA")

        assert [m["exchange"] for m in anywhere.sent] == ["NSE", "XETRA"]

    async def test_an_update_with_no_exchange_reaches_qualified_subscribers(self):
        """Nothing to filter on — delivering to nobody would be worse."""
        mgr = ConnectionManager()
        qualified = _register(mgr, 1, "ACME:NSE")
        bare = _register(mgr, 2, "ACME")
        other = _register(mgr, 3, "OTHER:NSE")

        await mgr.broadcast_price_update("ACME", {"current_price": 1.0})

        assert len(qualified.sent) == 1
        assert qualified.sent[0]["exchange"] is None
        assert len(bare.sent) == 1
        assert other.sent == []

    async def test_symbol_and_exchange_are_matched_case_insensitively(self):
        mgr = ConnectionManager()
        ws = _register(mgr, 1, "acme:nse")
        await mgr.broadcast_price_update(" acme ", {"current_price": 1.0}, "nse")
        assert len(ws.sent) == 1

    async def test_a_different_symbol_on_the_same_exchange_is_not_delivered(self):
        mgr = ConnectionManager()
        ws = _register(mgr, 1, "ACME:NSE")
        await mgr.broadcast_price_update("OTHER", {"current_price": 1.0}, "NSE")
        assert ws.sent == []


class TestSubscriptionBookkeeping:
    def test_confirmations_stay_sortable_strings(self):
        """price_stream echoes ``sorted(get_subscriptions(...))`` back to the client."""
        mgr = ConnectionManager()
        ws = _register(mgr, 1, "ACME:NSE", "ACME", "ZETA:XETRA")

        names = mgr.get_subscriptions(ws)  # type: ignore[arg-type]
        assert names == {"ACME", "ACME:NSE", "ZETA:XETRA"}
        assert sorted(names) == ["ACME", "ACME:NSE", "ZETA:XETRA"]
        assert mgr.get_subscription_keys(ws) == {  # type: ignore[arg-type]
            ("ACME", None), ("ACME", "NSE"), ("ZETA", "XETRA"),
        }

    def test_unsubscribe_is_exact(self):
        """Dropping the any-exchange watch must leave the qualified one alone."""
        mgr = ConnectionManager()
        ws = _register(mgr, 1, "ACME", "ACME:NSE")

        mgr.unsubscribe(ws, ["ACME"])  # type: ignore[arg-type]
        assert mgr.get_subscriptions(ws) == {"ACME:NSE"}  # type: ignore[arg-type]

        mgr.unsubscribe(ws, ["ACME:NSE"])  # type: ignore[arg-type]
        assert mgr.get_subscriptions(ws) == set()  # type: ignore[arg-type]

    def test_subscriptions_on_an_unknown_socket_are_ignored(self):
        mgr = ConnectionManager()
        stranger = _FakeWebSocket()
        mgr.subscribe(stranger, ["ACME"])  # type: ignore[arg-type]
        assert mgr.get_subscriptions(stranger) == set()  # type: ignore[arg-type]


class TestFetchPricesFanOutDedup:
    async def _record(self, monkeypatch, updates: list[dict]) -> list[tuple]:
        seen: list[tuple] = []

        class _Recorder:
            async def broadcast_price_update(
                self, symbol: str, data: dict, exchange: str | None = None
            ) -> None:
                seen.append((symbol, exchange, data))

        monkeypatch.setattr(fp, "manager", _Recorder())
        self.sent = await fp._broadcast_updates(updates)
        return seen

    async def test_a_cross_listed_ticker_broadcasts_once_per_exchange(
        self, monkeypatch
    ):
        """Keying dedup on the symbol threw the second listing's price away."""
        seen = await self._record(monkeypatch, [
            {"symbol": "ACME", "exchange": "NSE", "current_price": 1500.0},
            {"symbol": "ACME", "exchange": "XETRA", "current_price": 42.0},
        ])

        assert self.sent == 2
        assert [(s, e) for s, e, _ in seen] == [("ACME", "NSE"), ("ACME", "XETRA")]
        assert [d["current_price"] for _, _, d in seen] == [1500.0, 42.0]

    async def test_the_same_listing_twice_is_still_sent_once(self, monkeypatch):
        """Held *and* watchlisted is one listing — it must not double-send."""
        seen = await self._record(monkeypatch, [
            {"symbol": "ACME", "exchange": "NSE", "current_price": 1500.0},
            {"symbol": "ACME", "exchange": "NSE", "current_price": 1500.0},
        ])
        assert self.sent == 1
        assert len(seen) == 1

    async def test_an_update_without_an_exchange_still_goes_out(self, monkeypatch):
        seen = await self._record(
            monkeypatch, [{"symbol": "ACME", "current_price": 1.0}]
        )
        assert self.sent == 1
        assert seen[0][1] is None

    async def test_the_private_action_zone_is_still_stripped(self, monkeypatch):
        """The per-listing key must not have widened what a payload carries."""
        seen = await self._record(monkeypatch, [{
            "symbol": "ACME", "exchange": "NSE", "current_price": 1.0,
            "rsi": 61.2, "action_needed": "Y_DARK_GREEN",
        }])
        assert "action_needed" not in seen[0][2]
        assert seen[0][2]["exchange"] == "NSE"
