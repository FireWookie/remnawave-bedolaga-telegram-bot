"""add yookassa recurring payments

Revision ID: 0005
Revises: 0004
Create Date: 2026-02-22

Adds yookassa_saved_payment_methods table and extends yookassa_payments
with recurring payment fields.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table: str) -> bool:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    return table in inspector.get_table_names()


def _has_column(table: str, column: str) -> bool:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if table not in inspector.get_table_names():
        return False
    columns = [c['name'] for c in inspector.get_columns(table)]
    return column in columns


def upgrade() -> None:
    # --- Создание таблицы yookassa_saved_payment_methods ---
    if not _has_table('yookassa_saved_payment_methods'):
        op.create_table(
            'yookassa_saved_payment_methods',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
            sa.Column('payment_method_id', sa.String(255), unique=True, nullable=False, index=True),
            sa.Column('payment_method_type', sa.String(50), nullable=True),
            sa.Column('card_first_six', sa.String(6), nullable=True),
            sa.Column('card_last_four', sa.String(4), nullable=True),
            sa.Column('card_type', sa.String(50), nullable=True),
            sa.Column('card_expiry_month', sa.String(2), nullable=True),
            sa.Column('card_expiry_year', sa.String(4), nullable=True),
            sa.Column('title', sa.String(255), nullable=True),
            sa.Column('is_active', sa.Boolean(), server_default=sa.text('true')),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column(
                'source_payment_id',
                sa.Integer(),
                sa.ForeignKey('yookassa_payments.id'),
                nullable=True,
            ),
        )
        # Composite index for fast lookup of active methods per user
        op.create_index(
            'ix_yookassa_saved_pm_user_active',
            'yookassa_saved_payment_methods',
            ['user_id', 'is_active'],
        )

    # --- Расширение таблицы yookassa_payments ---
    if not _has_column('yookassa_payments', 'payment_method_id'):
        op.add_column(
            'yookassa_payments',
            sa.Column('payment_method_id', sa.String(255), nullable=True, index=True),
        )

    if not _has_column('yookassa_payments', 'payment_method_saved'):
        op.add_column(
            'yookassa_payments',
            sa.Column('payment_method_saved', sa.Boolean(), server_default=sa.text('false')),
        )

    if not _has_column('yookassa_payments', 'is_recurring'):
        op.add_column(
            'yookassa_payments',
            sa.Column('is_recurring', sa.Boolean(), server_default=sa.text('false')),
        )

    if not _has_column('yookassa_payments', 'saved_payment_method_id'):
        op.add_column(
            'yookassa_payments',
            sa.Column(
                'saved_payment_method_id',
                sa.Integer(),
                sa.ForeignKey('yookassa_saved_payment_methods.id'),
                nullable=True,
            ),
        )


def downgrade() -> None:
    # --- Удаление колонок из yookassa_payments ---
    if _has_column('yookassa_payments', 'saved_payment_method_id'):
        op.drop_column('yookassa_payments', 'saved_payment_method_id')

    if _has_column('yookassa_payments', 'is_recurring'):
        op.drop_column('yookassa_payments', 'is_recurring')

    if _has_column('yookassa_payments', 'payment_method_saved'):
        op.drop_column('yookassa_payments', 'payment_method_saved')

    if _has_column('yookassa_payments', 'payment_method_id'):
        op.drop_column('yookassa_payments', 'payment_method_id')

    # --- Удаление таблицы ---
    if _has_table('yookassa_saved_payment_methods'):
        op.drop_index('ix_yookassa_saved_pm_user_active', table_name='yookassa_saved_payment_methods')
        op.drop_table('yookassa_saved_payment_methods')
