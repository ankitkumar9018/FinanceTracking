"""add fund_type to holdings/mutual_funds, tax_settings to user_preferences,
and the corporate_actions table

Revision ID: d2e3f4a5b6c7
Revises: c1f2a3b4d5e6
Create Date: 2026-07-17

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d2e3f4a5b6c7"
down_revision = "c1f2a3b4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("holdings") as batch:
        batch.add_column(sa.Column("fund_type", sa.String(length=30), nullable=True))
    with op.batch_alter_table("mutual_funds") as batch:
        batch.add_column(sa.Column("fund_type", sa.String(length=30), nullable=True))
    with op.batch_alter_table("user_preferences") as batch:
        batch.add_column(
            sa.Column("tax_settings", sa.JSON(), server_default="{}", nullable=True)
        )

    op.create_table(
        "corporate_actions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("holding_id", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=30), nullable=False),
        sa.Column("ex_date", sa.Date(), nullable=False),
        sa.Column("ratio", sa.Float(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), server_default="DETECTED", nullable=False
        ),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("details", sa.JSON(), server_default="{}", nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["holding_id"], ["holdings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_corporate_actions_holding_id", "corporate_actions", ["holding_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_corporate_actions_holding_id", table_name="corporate_actions")
    op.drop_table("corporate_actions")
    with op.batch_alter_table("user_preferences") as batch:
        batch.drop_column("tax_settings")
    with op.batch_alter_table("mutual_funds") as batch:
        batch.drop_column("fund_type")
    with op.batch_alter_table("holdings") as batch:
        batch.drop_column("fund_type")
