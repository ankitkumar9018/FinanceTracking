"""add phone + telegram_chat_id to users, and password_resets table

Revision ID: c1f2a3b4d5e6
Revises: 8809e230b920
Create Date: 2026-07-17

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c1f2a3b4d5e6"
down_revision = "8809e230b920"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("phone", sa.String(length=32), nullable=True))
        batch.add_column(
            sa.Column("telegram_chat_id", sa.String(length=64), nullable=True)
        )

    op.create_table(
        "password_resets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_password_resets_user_id", "password_resets", ["user_id"], unique=False
    )
    op.create_index(
        "ix_password_resets_token_hash",
        "password_resets",
        ["token_hash"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_password_resets_token_hash", table_name="password_resets")
    op.drop_index("ix_password_resets_user_id", table_name="password_resets")
    op.drop_table("password_resets")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("telegram_chat_id")
        batch.drop_column("phone")
