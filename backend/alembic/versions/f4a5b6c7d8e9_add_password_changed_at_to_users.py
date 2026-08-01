"""add password_changed_at to users

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-08-01

Adds ``users.password_changed_at``. The column is nullable with no server-side
default: existing rows stay NULL (treated as "epoch 0" for the JWT ``pcat``
claim), and new rows get a value from the model's Python-side default. A
CURRENT_TIMESTAMP server default is deliberately avoided because SQLite rejects
non-constant defaults on ``ALTER TABLE ADD COLUMN``.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f4a5b6c7d8e9"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("password_changed_at", sa.DateTime(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("password_changed_at")
