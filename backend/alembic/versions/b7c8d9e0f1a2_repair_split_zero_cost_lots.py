"""Repair splits that were applied as a zero-cost adjustment lot.

``corporate_actions_service.apply_corporate_action`` used to record a stock
split by appending a zero-price BUY dated at the ex-date. That gives the split
shares a NIL cost basis and the ex-date as their acquisition date, so the next
sale books a fabricated loss on the original lot and a fabricated short-term
gain on the phantom one. The service now re-bases the pre-ex-date rows instead
(a split is not an acquisition), but the bad rows are already persisted in
existing databases and no code change repairs them.

WHY THIS MIGRATION DOES NOT REPAIR THEM AUTOMATICALLY
-----------------------------------------------------
The repair rewrites historical, broker-reconcilable ledger rows (100 @ Rs 1000
becomes 200 @ Rs 500) and changes tax numbers for financial years the user may
already have FILED. It also has consequences this revision cannot discharge on
its own:

* Tax records computed from the old lots stay stale until an async backfill
  recomputes them (it needs the services, and the network for the 31-Jan-2018
  FMV); this revision reports exactly which sells need it.
* Re-importing the same broker statement no longer matches the importer's
  ``(holding, date, type, qty, price)`` dedup fingerprint, so a re-upload can
  duplicate the restated rows until the importer is made split-aware.
* A ledger that oversells at a point in time (reachable with a backdated SELL)
  has a shape where the two schemes genuinely disagree on quantity.

So the repair is OPT-IN and loudly logged, never silent. ``upgrade()`` always
scans and reports; it only mutates when ``FINANCE_TRACKER_REPAIR_SPLIT_LOTS``
is set to 1/true/yes/on. TAKE A DATABASE BACKUP FIRST.

WHAT THE REPAIR DOES, per (adjustment row, APPLIED SPLIT action), oldest
ex-date first so a holding with several splits sees the ledger the previous one
produced:

1. snapshot the holding's ledger-derived (quantity, cost basis);
2. delete the zero-price adjustment row;
3. re-base every remaining row dated on/before the ex-date — quantity * ratio,
   price = old consideration / new quantity — stashing the pre-restatement
   pairs in ``details.repaired.rebased`` so the change is auditable and
   reversible;
4. re-derive (quantity, cost basis) and require it to match the snapshot; a
   holding that drifts is ROLLED BACK to a savepoint and quarantined — one odd
   ledger must never block the repair for every other holding;
5. mark ``details.applied.adjustment_transaction = False`` and record a
   ``details.repaired`` block.

``action_type = 'BONUS'`` actions are deliberately excluded: an Indian bonus
issue really is a nil-cost acquisition dated at allotment, so the zero-cost row
is correct there and re-basing it would break it.

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
"""

from __future__ import annotations

import json
import logging
import os
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

from alembic import context, op

revision = "b7c8d9e0f1a2"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

#: Set to 1/true/yes/on to let ``upgrade()`` actually rewrite the ledger.
REPAIR_ENV_VAR = "FINANCE_TRACKER_REPAIR_SPLIT_LOTS"

# Column scales: transactions.quantity Numeric(18, 6), price Numeric(18, 4).
_QTY_QUANT = Decimal("0.000001")
_PRICE_QUANT = Decimal("0.0001")

# Parity tolerances. Quantity is exact to the column's scale; the cost basis
# carries the rounding drift of restating each row (a 3:2 split of 100 @ 1000
# lands on 150 @ 666.6667 = 100,000.005 — the zero-cost scheme has the same
# drift), which grows with the number of restated rows and the magnitude of
# the basis, so the tolerance is relative with an absolute floor.
_QTY_TOL = Decimal("0.000001")
_COST_TOL_ABS = Decimal("0.05")
_COST_TOL_REL = Decimal("0.0000012")

# Beyond this many restated rows the per-row snapshot is dropped from
# ``details`` (the count is kept) so a long ledger cannot bloat every API
# response that serializes the action.
_SNAPSHOT_CAP = 500

# Identifies an auto-written adjustment row: the service's own note text plus a
# zero price. The note filter is what keeps a user-entered zero-price BUY out.
_ADJUSTMENT_NOTE_LIKE = "%adjustment (ratio%"


def _dec(value: Any) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def _ledger_state(rows: list[dict]) -> tuple[Decimal, Decimal]:
    """``(quantity, cost basis)`` replayed from an in-memory ledger.

    Deliberately a transcription of ``portfolio_service.calculate_cumulative_holding``
    (weighted average, SELL reduces cost proportionally, clamped at zero) —
    a migration must not import service code that will keep changing under it.
    """
    qty = Decimal("0")
    cost = Decimal("0")
    for row in sorted(rows, key=lambda r: (r["date"], r["id"])):
        q = _dec(row["quantity"])
        p = _dec(row["price"])
        if row["transaction_type"] == "BUY":
            cost += q * p
            qty += q
        elif row["transaction_type"] == "SELL":
            if qty > 0:
                sell_qty = min(q, qty)
                avg = cost / qty
                qty -= sell_qty
                cost = avg * qty
            else:
                qty = Decimal("0")
                cost = Decimal("0")
    return qty, cost


def _quantity_at_ex(rows: list[dict], ex_date: Any) -> Decimal:
    qty = Decimal("0")
    for row in rows:
        if row["date"] > ex_date:
            continue
        if row["transaction_type"] == "BUY":
            qty += _dec(row["quantity"])
        elif row["transaction_type"] == "SELL":
            qty -= _dec(row["quantity"])
    return qty


def _load_ledger(conn: sa.Connection, holding_id: int) -> list[dict]:
    rows = conn.execute(
        sa.text(
            "SELECT id, transaction_type, date, quantity, price, notes "
            "FROM transactions WHERE holding_id = :h ORDER BY date, id"
        ),
        {"h": holding_id},
    ).mappings()
    return [dict(row) for row in rows]


def find_affected(conn: sa.Connection) -> list[dict]:
    """Every (adjustment row, APPLIED SPLIT action) pair still in the old shape."""
    rows = conn.execute(
        sa.text(
            "SELECT t.id AS txn_id, t.holding_id AS holding_id, "
            "       ca.id AS action_id, ca.ex_date AS ex_date, "
            "       ca.ratio AS ratio, ca.details AS details "
            "  FROM transactions t "
            "  JOIN corporate_actions ca "
            "    ON ca.holding_id = t.holding_id AND ca.ex_date = t.date "
            " WHERE t.transaction_type = 'BUY' "
            "   AND t.price = 0 "
            "   AND t.notes LIKE :note "
            "   AND ca.status = 'APPLIED' "
            "   AND UPPER(ca.action_type) = 'SPLIT' "
            " ORDER BY t.holding_id, ca.ex_date, ca.id"
        ),
        {"note": _ADJUSTMENT_NOTE_LIKE},
    ).mappings()
    seen: set[int] = set()
    out: list[dict] = []
    for row in rows:
        if row["action_id"] in seen:
            continue
        seen.add(row["action_id"])
        out.append(dict(row))
    return out


def _rebase_rows(rows: list[dict], ex_date: Any, ratio: Decimal) -> list[dict]:
    """Scale every in-memory row dated on/before *ex_date*, preserving its
    total consideration. Mutates *rows*; returns the pre-restatement
    ``(transaction_id, quantity, price)`` snapshot of the rows it changed.

    Only quantity and price move. ``notes`` is deliberately left alone:
    ``dividend_service`` finds a reinvestment BUY by an exact ``notes ==``
    match, so stamping an audit line there would orphan DRIP rows when their
    dividend is deleted. The snapshot goes into the action's ``details``
    instead, which is what makes the repair reversible.
    """
    snapshot: list[dict] = []
    for row in rows:
        if row["date"] > ex_date:
            continue
        q = _dec(row["quantity"])
        if q == 0:
            continue
        p = _dec(row["price"])
        consideration = q * p
        new_q = (q * ratio).quantize(_QTY_QUANT, rounding=ROUND_HALF_UP)
        if new_q == 0:
            logger.warning(
                "  txn=%s quantity %s x %s rounds to zero — left as-is",
                row["id"], q, ratio,
            )
            continue
        # Derive the price from the ROUNDED quantity so the STORED pair still
        # multiplies out to the original consideration.
        new_p = (consideration / new_q).quantize(_PRICE_QUANT, rounding=ROUND_HALF_UP)
        snapshot.append(
            {"transaction_id": row["id"], "quantity": float(q), "price": float(p)}
        )
        row["quantity"] = new_q
        row["price"] = new_p
        row["_dirty"] = True
    return snapshot


def _load_details(raw: Any) -> dict:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, (str, bytes)):
        try:
            loaded = json.loads(raw)
        except (ValueError, TypeError):
            return {}
        return dict(loaded) if isinstance(loaded, dict) else {}
    return {}


def _write_details(conn: sa.Connection, action_id: int, details: dict) -> None:
    stmt = sa.text(
        "UPDATE corporate_actions SET details = :details WHERE id = :id"
    ).bindparams(sa.bindparam("details", type_=sa.JSON()))
    conn.execute(stmt, {"details": details, "id": action_id})


def _sells_needing_tax_recompute(
    conn: sa.Connection, holding_ids: list[int]
) -> list[dict]:
    """SELLs on repaired holdings that already carry TaxRecords.

    Returned in ``(sale_date, transaction_id)`` order per holding — the order
    the FY exemption / Freibetrag netting in ``tax_service`` requires, since
    each compute nets only against the records that precede it and cascades
    over the later sells of the same FY.
    """
    if not holding_ids:
        return []
    rows = conn.execute(
        sa.text(
            "SELECT DISTINCT tr.user_id AS user_id, t.holding_id AS holding_id, "
            "       t.id AS transaction_id, t.date AS sale_date "
            "  FROM transactions t "
            "  JOIN tax_records tr ON tr.transaction_id = t.id "
            " WHERE t.transaction_type = 'SELL' "
            f"   AND t.holding_id IN ({','.join(str(int(h)) for h in holding_ids)}) "
            " ORDER BY t.holding_id, t.date, t.id"
        )
    ).mappings()
    return [dict(row) for row in rows]


def repair_applied_split_actions(
    conn: sa.Connection, dry_run: bool = True
) -> dict:
    """Re-base splits recorded as a zero-cost adjustment lot.

    Every holding is transformed IN MEMORY first and the result checked against
    the ledger it must reproduce; only a holding that passes is written. So a
    ledger shape this analysis does not cover is quarantined and reported —
    never half-rewritten, and never a reason to abort the repair for everyone
    else. With ``dry_run=True`` (the default) the checks run and nothing is
    written at all.
    """
    affected = find_affected(conn)
    report: dict = {
        "dry_run": dry_run,
        "scanned_actions": len(affected),
        "repaired_actions": [],
        "repaired_holdings": [],
        "quarantined": [],
        "tax_records_to_recompute": [],
    }
    if not affected:
        return report

    by_holding: dict[int, list[dict]] = {}
    for row in affected:
        by_holding.setdefault(row["holding_id"], []).append(row)

    delete_stmt = sa.text("DELETE FROM transactions WHERE id = :i")
    update_stmt = sa.text(
        "UPDATE transactions SET quantity = :q, price = :p WHERE id = :i"
    )

    for holding_id in sorted(by_holding):
        actions = by_holding[holding_id]
        # Oldest ex-date first: a later split must see the ledger the earlier
        # one produced. id breaks ties deterministically.
        actions.sort(key=lambda a: (a["ex_date"], a["action_id"]))

        rows = _load_ledger(conn, holding_id)
        removed: list[int] = []
        details_writes: list[tuple[int, dict]] = []
        quarantine: str | None = None

        for action in actions:
            ratio = _dec(action["ratio"])
            if ratio <= 0 or ratio == 1:
                quarantine = f"action {action['action_id']}: ratio {ratio}"
                break

            pre_qty, pre_cost = _ledger_state(rows)

            rows = [r for r in rows if r["id"] != action["txn_id"]]
            removed.append(action["txn_id"])

            qty_at_ex = _quantity_at_ex(rows, action["ex_date"])
            if qty_at_ex <= 0:
                # Nothing held on the ex-date once the synthetic row is gone:
                # the two schemes cannot agree on the quantity here.
                quarantine = (
                    f"action {action['action_id']}: quantity at ex-date "
                    f"{qty_at_ex} is not positive"
                )
                break

            snapshot = _rebase_rows(rows, action["ex_date"], ratio)
            changed = len(snapshot)

            post_qty, post_cost = _ledger_state(rows)
            cost_tol = max(_COST_TOL_ABS, abs(pre_cost) * _COST_TOL_REL)
            if abs(post_qty - pre_qty) > _QTY_TOL:
                quarantine = (
                    f"action {action['action_id']}: quantity {pre_qty} -> {post_qty}"
                )
                break
            if abs(post_cost - pre_cost) > cost_tol:
                quarantine = (
                    f"action {action['action_id']}: cost basis {pre_cost} -> "
                    f"{post_cost} (tolerance {cost_tol})"
                )
                break

            details = _load_details(action["details"])
            applied = dict(details.get("applied") or {})
            applied["adjustment_transaction"] = False
            applied["treatment"] = "REBASE"
            applied["rebased_transactions"] = changed
            details["applied"] = applied
            repaired: dict = {
                "revision": revision,
                "removed_transaction_id": action["txn_id"],
                "rebased_transactions": changed,
                "ratio": float(ratio),
            }
            # Pre-restatement values, so the repair is reversible without a
            # database restore. Capped: a very long ledger records the count
            # only rather than turning every API response into a trade blotter.
            if len(snapshot) <= _SNAPSHOT_CAP:
                repaired["rebased"] = snapshot
            else:
                repaired["rebased_truncated"] = True
            details["repaired"] = repaired
            details_writes.append((action["action_id"], details))

        if quarantine is not None:
            report["quarantined"].append(
                {"holding_id": holding_id, "reason": quarantine}
            )
            continue

        if not dry_run:
            for txn_id in removed:
                conn.execute(delete_stmt, {"i": txn_id})
            for row in rows:
                if not row.get("_dirty"):
                    continue
                conn.execute(
                    update_stmt,
                    {
                        "q": float(row["quantity"]),
                        "p": float(row["price"]),
                        "i": row["id"],
                    },
                )
            for action_id, details in details_writes:
                _write_details(conn, action_id, details)

        report["repaired_actions"].extend(a for a, _ in details_writes)
        report["repaired_holdings"].append(holding_id)

    report["tax_records_to_recompute"] = _sells_needing_tax_recompute(
        conn, report["repaired_holdings"]
    )
    return report


def _opt_in() -> bool:
    return os.environ.get(REPAIR_ENV_VAR, "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _log_report(report: dict, opt_in: bool) -> None:
    scanned = report["scanned_actions"]
    if not scanned:
        logger.info("Split-lot repair: no zero-cost split adjustments found.")
        return

    if not opt_in:
        logger.warning(
            "\n"
            "================================================================\n"
            "SPLIT REPAIR NEEDED — NOT APPLIED (opt-in)\n"
            "%d applied stock split(s) in this database were recorded as a\n"
            "zero-cost adjustment lot. Those split shares carry a NIL cost\n"
            "basis and the ex-date as their acquisition date, so sales after\n"
            "the split report a fabricated loss on the original lot and a\n"
            "fabricated short-term gain on the split shares.\n"
            "\n"
            "This repair restates historical ledger rows (100 @ 1000 becomes\n"
            "200 @ 500) and WILL change capital-gains figures for financial\n"
            "years you may already have filed. It is therefore opt-in:\n"
            "\n"
            "  1. back up the database\n"
            "  2. re-run the migration with %s=1\n"
            "  3. recompute the affected tax records (the run prints them in\n"
            "     the required (sale_date, transaction_id) order per holding)\n"
            "\n"
            "Dry-run result: %d action(s) would be repaired, %d holding(s)\n"
            "quarantined: %s\n"
            "================================================================",
            scanned,
            REPAIR_ENV_VAR,
            len(report["repaired_actions"]),
            len(report["quarantined"]),
            report["quarantined"] or "none",
        )
        return

    logger.warning(
        "Split-lot repair APPLIED: %d action(s) re-based across %d holding(s); "
        "%d holding(s) quarantined: %s",
        len(report["repaired_actions"]),
        len(report["repaired_holdings"]),
        len(report["quarantined"]),
        report["quarantined"] or "none",
    )
    pending = report["tax_records_to_recompute"]
    if pending:
        logger.warning(
            "Split-lot repair: %d sale(s) still hold tax records computed from "
            "the OLD lots. Recompute them with "
            "corporate_actions_service.recompute_tax_after_ledger_change (or "
            "tax_service.compute_tax_for_transaction) in this exact order, "
            "oldest financial year first: %s",
            len(pending),
            [
                (row["user_id"], row["holding_id"], row["transaction_id"],
                 str(row["sale_date"]))
                for row in pending
            ],
        )


def upgrade() -> None:
    # No schema change: this revision exists to detect and (opt-in) repair data.
    if context.is_offline_mode():
        logger.warning(
            "Split-lot repair skipped: --sql/offline mode cannot inspect data. "
            "Run the migration online against the database."
        )
        return

    conn = op.get_bind()
    opt_in = _opt_in()
    report = repair_applied_split_actions(conn, dry_run=not opt_in)
    _log_report(report, opt_in)


def downgrade() -> None:
    # Not reversed: re-introducing the zero-cost lot would restore the very
    # cost-basis error this repair removes. Each restated row carries its
    # pre-restatement quantity/price in its own ``notes`` if a manual rollback
    # is ever needed.
    pass
