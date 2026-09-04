"""Backfill Holding.currency from the exchange.

``currency`` defaulted to "INR" at every creation path and nothing derived it
from the exchange, so XETRA/FRA/NYSE/NASDAQ positions were stored as rupees and
then summed, FX-converted and taxed as rupees. ``markets.currency_for`` now
derives it going forward; this repairs rows already written.

Only rows that are UNAMBIGUOUSLY wrong are touched: currency = 'INR' on an
exchange that cannot be rupee-denominated. A deliberate non-INR value, or any
INR value on NSE/BSE, is left alone.

Revision ID: a1b2c3d4e5f6
Revises: f4a5b6c7d8e9
"""

from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None

# Exchange -> currency, for exchanges that are never INR.
_NON_INR = {"XETRA": "EUR", "FRA": "EUR", "NYSE": "USD", "NASDAQ": "USD"}


def upgrade() -> None:
    for exchange, ccy in _NON_INR.items():
        op.execute(
            f"UPDATE holdings SET currency = '{ccy}' "
            f"WHERE UPPER(exchange) = '{exchange}' AND (currency IS NULL OR currency = 'INR')"
        )


def downgrade() -> None:
    # Intentionally not reversed: restoring the incorrect 'INR' would
    # re-introduce the mis-valuation this migration exists to fix.
    pass
