"""Report tax records computed before the capital-gains fixes landed.

A ``TaxRecord`` is a SNAPSHOT of what the compute path believed at the moment
it ran, and both ``/tax/summary`` and the ITR-ready capital-gains export read
those stored figures. Seven defects have since been fixed in the compute path:

* purchase brokerage was left out of the cost of acquisition and sale
  brokerage out of the expenses of transfer, so every gain was overstated;
* the annual intra-head loss set-off (ss.70/71 IN, §20(6) EStG DE) was never
  applied — each sale was taxed in isolation, so a December loss never
  relieved a September gain;
* Finance (No. 2) Act 2024 rates (20 % / 12.5 %) were applied to transfers
  made BEFORE 23-Jul-2024, which are still taxed at 15 % / 10 %;
* a stock split recorded as a zero-cost adjustment lot gave the split shares a
  nil basis and the ex-date as their acquisition date, fabricating a loss on
  the original lot and a short-term gain on the phantom one.

Records written before those fixes still hold the OLD numbers, and nothing
re-derives them: the compute path only re-derives when the LEDGER changes, and
these records' ledgers did not change.

WHY THIS MIGRATION DOES NOT RECOMPUTE THEM
------------------------------------------
Recomputing rewrites capital-gains figures for financial years the user may
already have FILED. Doing that inside ``alembic upgrade head`` — where nobody
is watching and there is no report — is worse than leaving the records alone:
the user would open the app to a different tax bill with no explanation and no
way to see what moved. A correct recompute also needs the services themselves
(FIFO replay, the FY allocators, and the network for the 31-Jan-2018 FMV),
which a migration must not import: they will keep changing under it.

So this revision SCANS and REPORTS, per (user, financial year, jurisdiction),
and points at the endpoint that does the repair with the user's consent and a
before/after answer:

    POST /api/v1/tax/recompute[?financial_year=2024-25]

The one class it will repair — and only when explicitly opted in with
``FINANCE_TRACKER_DROP_ORPHAN_TAX_RECORDS=1`` — is PROVABLY ORPHANED records:
a record that still names a ``transaction_id`` whose row is gone, is no longer
a SELL, or no longer hangs off any portfolio of the record's own user. Such a
record cannot be re-derived by anything, and while it stands it keeps
consuming that year's s.112A exemption / Sparer-Pauschbetrag and overtaxes
every record that is still real. Even that stays opt-in, because dropping it
changes the year's total.

Records with a NULL ``transaction_id`` are NEVER touched, not even under the
opt-in. That is exactly the shape of a CSV-imported or backup-restored record
(``csv_import_service`` and ``backup_service`` both create them without a
transaction link) whose figures are the user's own filed data — the FY
allocators already refuse to rewrite them. A ghost left by a deletion made
before the ledger-invalidation fix has the same shape, and destroying filed
statement data to remove a possible ghost is a far worse trade than reporting
it, so unlinked records are counted and left alone.

Revision ID: c1d2e3f4a5b6
Revises: b7c8d9e0f1a2
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime
from typing import Any

import sqlalchemy as sa

from alembic import context, op

revision = "c1d2e3f4a5b6"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

#: Set to 1/true/yes/on to let ``upgrade()`` delete provably-orphaned records.
DROP_ORPHANS_ENV_VAR = "FINANCE_TRACKER_DROP_ORPHAN_TAX_RECORDS"

#: Transfers on or after this date are taxed at the Finance (No. 2) Act 2024
#: rates; earlier ones keep 15 % STCG / 10 % LTCG.
FINANCE_ACT_2024_CUTOVER = date(2024, 7, 23)
INDIA_RATES_PRE_2024 = {"STCG": 0.15, "LTCG": 0.10}

#: Rounding slack before calling a stored figure provably above the old-law
#: ceiling. Amounts are Numeric(18, 4); a paisa of drift is not a defect.
_TAX_TOL = 0.01

#: Same signature the split-lot repair (b7c8d9e0f1a2) uses to recognise an
#: auto-written zero-cost split adjustment row.
_ADJUSTMENT_NOTE_LIKE = "%adjustment (ratio%"

#: Cap on how many groups are listed in the log before it summarises.
_MAX_GROUPS_LOGGED = 50


def _as_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _as_date(value: Any) -> date | None:
    """SQLite hands back a string for a DATE column read through raw SQL."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _tables(conn: sa.Connection) -> set[str]:
    return set(sa.inspect(conn).get_table_names())


def _holdings_with_brokerage(conn: sa.Connection) -> set[int]:
    rows = conn.execute(
        sa.text(
            "SELECT DISTINCT holding_id FROM transactions "
            "WHERE brokerage IS NOT NULL AND brokerage <> 0"
        )
    )
    return {int(r[0]) for r in rows if r[0] is not None}


def _holdings_with_zero_cost_split(conn: sa.Connection, tables: set[str]) -> set[int]:
    if "corporate_actions" not in tables:
        return set()
    rows = conn.execute(
        sa.text(
            "SELECT DISTINCT t.holding_id "
            "  FROM transactions t "
            "  JOIN corporate_actions ca "
            "    ON ca.holding_id = t.holding_id AND ca.ex_date = t.date "
            " WHERE t.transaction_type = 'BUY' "
            "   AND t.price = 0 "
            "   AND t.notes LIKE :note "
            "   AND ca.status = 'APPLIED' "
            "   AND UPPER(ca.action_type) = 'SPLIT'"
        ),
        {"note": _ADJUSTMENT_NOTE_LIKE},
    )
    return {int(r[0]) for r in rows if r[0] is not None}


def _orphan_reason(row: dict) -> str | None:
    """Why this record can never be re-derived, or ``None`` if it still can.

    Only records that still NAME a transaction are judged here: a NULL link is
    a CSV/backup import (or a pre-fix ghost wearing the same clothes) and is
    left alone by design.
    """
    if row["transaction_id"] is None:
        return None
    if row["txn_id"] is None:
        return "linked transaction no longer exists"
    if (row["txn_type"] or "").upper() != "SELL":
        return f"linked transaction is a {row['txn_type']}, not a SELL"
    if row["owner_id"] is None:
        return "linked holding or portfolio no longer exists"
    if int(row["owner_id"]) != int(row["user_id"]):
        return "linked transaction belongs to a different user"
    return None


def _overtaxed_reason(row: dict) -> str | None:
    """Stored tax above the maximum the law allowed on that transfer date.

    Provable, not a guess: for an Indian transfer made before 23-Jul-2024 the
    ceiling is the whole gain at the OLD rate, and the annual exemption can
    only ever push the real figure BELOW that. Anything above it was computed
    under the post-cutover rates.
    """
    if (row["jurisdiction"] or "").upper() != "IN":
        return None
    sale_date = _as_date(row["sale_date"])
    if sale_date is None or sale_date >= FINANCE_ACT_2024_CUTOVER:
        return None
    rate = INDIA_RATES_PRE_2024.get((row["gain_type"] or "").upper())
    if rate is None:
        return None
    gain = _as_float(row["gain_amount"])
    tax = _as_float(row["tax_amount"])
    if gain <= 0:
        return None
    ceiling = gain * rate
    if tax > ceiling + _TAX_TOL:
        return (
            f"tax {tax:.2f} exceeds the pre-23-Jul-2024 ceiling "
            f"{ceiling:.2f} ({rate:.0%} of the gain)"
        )
    return None


def scan_stale_tax_records(conn: sa.Connection) -> dict:
    """Group every stored tax record by (user, financial year, jurisdiction).

    Returns ``{"groups": [...], "orphan_record_ids": [...], "totals": {...}}``.
    Each group carries the counts a user needs to decide whether to run the
    recompute:

    ``orphans``            provably un-derivable (see :func:`_orphan_reason`);
    ``overtaxed``          provably taxed above the old-law ceiling;
    ``brokerage_suspect``  the sale's ledger carries brokerage, which a
                           pre-fix computation ignored on both sides;
    ``split_suspect``      the holding still has a zero-cost split lot;
    ``loss_suspect``       the year holds a realised LOSS while another record
                           in it still carries tax — the shape left behind
                           when the annual set-off never ran;
    ``unlinked``           imported/restored rows, reported and never touched.
    """
    tables = _tables(conn)
    if "tax_records" not in tables:
        return {"groups": [], "orphan_record_ids": [], "totals": {}}

    brokered = _holdings_with_brokerage(conn)
    split_holdings = _holdings_with_zero_cost_split(conn, tables)

    rows = conn.execute(
        sa.text(
            "SELECT tr.id AS id, tr.user_id AS user_id, "
            "       tr.financial_year AS financial_year, "
            "       tr.tax_jurisdiction AS jurisdiction, "
            "       tr.gain_type AS gain_type, tr.gain_amount AS gain_amount, "
            "       tr.tax_amount AS tax_amount, tr.sale_date AS sale_date, "
            "       tr.transaction_id AS transaction_id, "
            "       t.id AS txn_id, t.transaction_type AS txn_type, "
            "       t.holding_id AS holding_id, p.user_id AS owner_id "
            "  FROM tax_records tr "
            "  LEFT JOIN transactions t ON t.id = tr.transaction_id "
            "  LEFT JOIN holdings h ON h.id = t.holding_id "
            "  LEFT JOIN portfolios p ON p.id = h.portfolio_id "
            " ORDER BY tr.user_id, tr.financial_year, tr.tax_jurisdiction, tr.id"
        )
    ).mappings()

    groups: dict[tuple, dict] = {}
    orphan_record_ids: list[int] = []

    for raw in rows:
        row = dict(raw)
        key = (row["user_id"], row["financial_year"], row["jurisdiction"])
        group = groups.setdefault(
            key,
            {
                "user_id": row["user_id"],
                "financial_year": row["financial_year"],
                "jurisdiction": row["jurisdiction"],
                "records": 0,
                "unlinked": 0,
                "orphans": 0,
                "rewritable": 0,
                "overtaxed": 0,
                "brokerage_suspect": 0,
                "split_suspect": 0,
                "loss_suspect": False,
                "total_tax": 0.0,
                "_has_loss": False,
                "_has_owned_tax": False,
                "_flagged": set(),
                "reasons": [],
            },
        )
        group["records"] += 1
        gain = _as_float(row["gain_amount"])
        tax = _as_float(row["tax_amount"])
        group["total_tax"] += tax
        if gain < 0:
            # An imported row's loss still feeds the year's set-off pools, so
            # it counts here even though its own figure is never rewritten.
            group["_has_loss"] = True

        if row["transaction_id"] is None:
            group["unlinked"] += 1
            continue

        orphan = _orphan_reason(row)
        if orphan is not None:
            group["orphans"] += 1
            group["_flagged"].add(row["id"])
            orphan_record_ids.append(int(row["id"]))
            if orphan not in group["reasons"]:
                group["reasons"].append(orphan)
            # An orphan's own figures say nothing about the compute path that
            # produced them, so it is not also counted as a rate/brokerage
            # defect — it simply must not stand.
            continue

        # From here on the record is one the recompute could actually rewrite.
        group["rewritable"] += 1
        if tax > 0:
            group["_has_owned_tax"] = True

        overtaxed = _overtaxed_reason(row)
        if overtaxed is not None:
            group["overtaxed"] += 1
            group["_flagged"].add(row["id"])
            if "pre-23-Jul-2024 rates" not in group["reasons"]:
                group["reasons"].append("pre-23-Jul-2024 rates")

        holding_id = row["holding_id"]
        if holding_id is not None and int(holding_id) in brokered:
            group["brokerage_suspect"] += 1
            group["_flagged"].add(row["id"])
            if "brokerage on the ledger" not in group["reasons"]:
                group["reasons"].append("brokerage on the ledger")
        if holding_id is not None and int(holding_id) in split_holdings:
            group["split_suspect"] += 1
            group["_flagged"].add(row["id"])
            if "zero-cost split lot" not in group["reasons"]:
                group["reasons"].append("zero-cost split lot")

    out: list[dict] = []
    for key in sorted(groups):
        group = groups[key]
        # The set-off marker is a property of the YEAR, not of one record: a
        # realised loss sitting next to a record that still carries tax is the
        # shape left behind when the annual netting never ran. It only counts
        # when the taxed record is one the recompute may rewrite — a year made
        # entirely of imported rows has nothing for the repair to change, and
        # reporting it would be crying wolf.
        group["loss_suspect"] = bool(
            group.pop("_has_loss") and group.pop("_has_owned_tax")
        )
        if group["loss_suspect"] and "loss not set off" not in group["reasons"]:
            group["reasons"].append("loss not set off")
        flagged = group.pop("_flagged")
        # An un-netted loss makes the whole year's rewritable rows suspect, not
        # just the ones that carry another marker.
        group["stale_records"] = max(
            len(flagged), group["rewritable"] if group["loss_suspect"] else 0
        )
        group["total_tax"] = round(group["total_tax"], 2)
        out.append(group)

    stale_groups = [g for g in out if g["stale_records"] or g["orphans"]]
    return {
        "groups": out,
        "orphan_record_ids": orphan_record_ids,
        "totals": {
            "users": len({g["user_id"] for g in out}),
            "groups": len(out),
            "stale_groups": len(stale_groups),
            "records": sum(g["records"] for g in out),
            "stale_records": sum(g["stale_records"] for g in out),
            "orphans": sum(g["orphans"] for g in out),
            "overtaxed": sum(g["overtaxed"] for g in out),
            "unlinked": sum(g["unlinked"] for g in out),
        },
    }


def drop_orphaned_tax_records(conn: sa.Connection, record_ids: list[int]) -> int:
    """Delete the given provably-orphaned records. Returns how many went."""
    for record_id in record_ids:
        conn.execute(
            sa.text("DELETE FROM tax_records WHERE id = :i"), {"i": int(record_id)}
        )
    return len(record_ids)


def _opt_in() -> bool:
    return os.environ.get(DROP_ORPHANS_ENV_VAR, "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _log_report(report: dict, dropped: int, opt_in: bool) -> None:
    totals = report["totals"]
    if not totals or not totals["records"]:
        logger.info("Stale-tax scan: no tax records in this database.")
        return

    stale_groups = [
        g for g in report["groups"] if g["stale_records"] or g["orphans"]
    ]
    if not stale_groups:
        logger.info(
            "Stale-tax scan: %d tax record(s) across %d (user, FY, jurisdiction) "
            "group(s); none show a pre-fix signature.",
            totals["records"],
            totals["groups"],
        )
        return

    listed = stale_groups[:_MAX_GROUPS_LOGGED]
    lines = [
        "  user={} FY={} ({}): {}/{} record(s) suspect{} — {}".format(
            g["user_id"],
            g["financial_year"],
            g["jurisdiction"],
            g["stale_records"],
            g["records"],
            f", {g['orphans']} ORPHANED" if g["orphans"] else "",
            ", ".join(g["reasons"]) or "unclassified",
        )
        for g in listed
    ]
    if len(stale_groups) > len(listed):
        lines.append(f"  ...and {len(stale_groups) - len(listed)} more group(s)")

    logger.warning(
        "\n"
        "================================================================\n"
        "STALE TAX RECORDS FOUND — NOT RECOMPUTED\n"
        "%d of %d stored tax record(s), in %d of %d (user, FY, jurisdiction)\n"
        "group(s), were computed before the capital-gains fixes and still\n"
        "hold the old figures. /tax/summary and the ITR-ready export read\n"
        "those stored figures, so they are what the user still sees.\n"
        "\n"
        "This migration does NOT recompute them: that rewrites capital-gains\n"
        "numbers for years that may already have been FILED, and doing so\n"
        "unattended and unreported is worse than leaving them. Each user\n"
        "repairs their own, with a before/after answer, via:\n"
        "\n"
        "    POST /api/v1/tax/recompute[?financial_year=<FY>]\n"
        "\n"
        "%s\n"
        "%d record(s) carry no transaction link (CSV-imported or restored\n"
        "from a backup) and are never rewritten by either path.\n"
        "%s\n"
        "================================================================",
        totals["stale_records"],
        totals["records"],
        totals["stale_groups"],
        totals["groups"],
        "\n".join(lines),
        totals["unlinked"],
        (
            f"{dropped} provably-orphaned record(s) were DELETED "
            f"({DROP_ORPHANS_ENV_VAR} is set)."
            if opt_in
            else (
                f"{totals['orphans']} record(s) are provably orphaned — their "
                f"sale is gone,\nso nothing can ever re-derive them while they "
                f"keep consuming the\nyear's exemption. Re-run with "
                f"{DROP_ORPHANS_ENV_VAR}=1 to delete just those\n(back up "
                f"first), or let the recompute endpoint remove them."
            )
        ),
    )


def upgrade() -> None:
    # No schema change: this revision exists to detect and report stale data,
    # and (opt-in) to delete records that can never be re-derived.
    if context.is_offline_mode():
        logger.warning(
            "Stale-tax scan skipped: --sql/offline mode cannot inspect data. "
            "Run the migration online against the database."
        )
        return

    conn = op.get_bind()
    report = scan_stale_tax_records(conn)
    opt_in = _opt_in()
    dropped = (
        drop_orphaned_tax_records(conn, report["orphan_record_ids"]) if opt_in else 0
    )
    _log_report(report, dropped, opt_in)


def downgrade() -> None:
    # Nothing to reverse by default. Deleted orphans are not restored: they
    # named a sale that no longer exists, so there is nothing to restore them
    # to. Restore from the backup the opt-in run told you to take.
    pass
