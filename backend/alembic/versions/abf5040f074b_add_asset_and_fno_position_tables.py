"""add_asset_and_fno_position_tables

Revision ID: abf5040f074b
Revises: 9ec39aff1e92
Create Date: 2026-02-11 17:29:12.593147

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'abf5040f074b'
down_revision: Union[str, None] = '9ec39aff1e92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_type", sa.String(30), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("symbol", sa.String(50), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), server_default="0", nullable=True),
        sa.Column("purchase_price", sa.Numeric(precision=18, scale=4), server_default="0", nullable=True),
        sa.Column("current_value", sa.Numeric(precision=18, scale=4), server_default="0", nullable=True),
        sa.Column("currency", sa.String(10), server_default="INR", nullable=False),
        sa.Column("interest_rate", sa.Float(), nullable=True),
        sa.Column("maturity_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assets_user_id", "assets", ["user_id"])
    op.create_index("ix_assets_asset_type", "assets", ["asset_type"])

    op.create_table(
        "fno_positions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("portfolio_id", sa.Integer(), sa.ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("exchange", sa.String(20), server_default="NSE", nullable=False),
        sa.Column("instrument_type", sa.String(10), nullable=False),
        sa.Column("strike_price", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column("lot_size", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("entry_price", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("exit_price", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("current_price", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("side", sa.String(10), server_default="BUY", nullable=False),
        sa.Column("status", sa.String(20), server_default="OPEN", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fno_positions_portfolio_id", "fno_positions", ["portfolio_id"])
    op.create_index("ix_fno_positions_symbol", "fno_positions", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_fno_positions_symbol", "fno_positions")
    op.drop_index("ix_fno_positions_portfolio_id", "fno_positions")
    op.drop_table("fno_positions")
    op.drop_index("ix_assets_asset_type", "assets")
    op.drop_index("ix_assets_user_id", "assets")
    op.drop_table("assets")
