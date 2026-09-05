"""add condition_was_true to alerts

Revision ID: d2e3f4a5b6c8
Revises: c1d2e3f4a5b6
Create Date: 2026-09-05

Persists the alert edge-trigger latch. Alerts notify only on a false -> true
transition of their condition, but the previous truth value lived in a
process-local dict in ``alert_service``: restarting the backend forgot it, so
every alert whose threshold was still crossed sent one more notification on
the next cycle — and the desktop shell, which kills the backend on window
close, turned that into a re-send on every launch.

Existing rows are backfilled to ``false`` (not "true where last_triggered is
set"): the condition may well have gone false while the column did not exist,
and a false latch can at worst cost one extra notification, whereas a wrongly
true one silently swallows the next real crossing.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d2e3f4a5b6c8"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default is a plain literal, not ``sa.text("0")``: a ClauseElement
    # default makes alembic's SQLite batch mode rebuild the whole table, and
    # the rebuild's column reordering both breaks on this table and hides the
    # "duplicate column" error that ``_run_migrations`` relies on to recover a
    # schema that already ran ahead of its stamp.
    with op.batch_alter_table("alerts") as batch:
        batch.add_column(
            sa.Column(
                "condition_was_true",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("alerts") as batch:
        batch.drop_column("condition_was_true")
