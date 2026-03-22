"""add_unique_constraint_holding_portfolio_symbol_exchange

Revision ID: 8809e230b920
Revises: abf5040f074b
Create Date: 2026-02-12 16:47:25.028326

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8809e230b920'
down_revision: Union[str, None] = 'abf5040f074b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite requires batch mode for constraint changes (copy-and-move strategy)
    with op.batch_alter_table('holdings', schema=None) as batch_op:
        batch_op.create_unique_constraint('uq_holding_portfolio_symbol_exchange', ['portfolio_id', 'stock_symbol', 'exchange'])


def downgrade() -> None:
    with op.batch_alter_table('holdings', schema=None) as batch_op:
        batch_op.drop_constraint('uq_holding_portfolio_symbol_exchange', type_='unique')
