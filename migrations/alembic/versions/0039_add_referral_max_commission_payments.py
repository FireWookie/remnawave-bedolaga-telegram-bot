"""add referral_max_commission_payments to users

Per-partner override for the global REFERRAL_MAX_COMMISSION_PAYMENTS setting.
NULL means use the global value.

Revision ID: 0039
Revises: 0038
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0039'
down_revision: Union[str, None] = '0038'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    return column in [c['name'] for c in inspector.get_columns(table)]


def upgrade() -> None:
    if not _has_column('users', 'referral_max_commission_payments'):
        op.add_column(
            'users',
            sa.Column('referral_max_commission_payments', sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column('users', 'referral_max_commission_payments')
