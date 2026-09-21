"""whoop_daily and whoop_workouts

The two tables WHOOP data lands in. Only the figures the engine reads are stored; raw
payloads are not. Every score column is nullable because WHOOP fills a day in over time.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-21 14:48:53.636311
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'whoop_daily',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('cycle_id', sa.String(length=64), nullable=True),
        sa.Column('timezone_offset', sa.String(length=16), nullable=True),
        sa.Column('recovery', sa.Float(), nullable=True),
        sa.Column('hrv_ms', sa.Float(), nullable=True),
        sa.Column('rhr', sa.Float(), nullable=True),
        sa.Column('sleep_performance', sa.Float(), nullable=True),
        sa.Column('day_strain', sa.Float(), nullable=True),
        sa.Column('spo2', sa.Float(), nullable=True),
        sa.Column('skin_temp_c', sa.Float(), nullable=True),
        sa.Column('calibrating', sa.Boolean(), nullable=False),
        sa.Column('cycle_open', sa.Boolean(), nullable=False),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'date', name='uq_whoop_daily_user_date'),
    )
    with op.batch_alter_table('whoop_daily', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_whoop_daily_date'), ['date'], unique=False)
        batch_op.create_index(batch_op.f('ix_whoop_daily_user_id'), ['user_id'], unique=False)

    op.create_table(
        'whoop_workouts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('whoop_id', sa.String(length=64), nullable=False),
        sa.Column('start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('strain', sa.Float(), nullable=True),
        sa.Column('avg_hr', sa.Integer(), nullable=True),
        sa.Column('max_hr', sa.Integer(), nullable=True),
        sa.Column('sport', sa.String(length=64), nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'whoop_id', name='uq_whoop_workouts_user_whoop_id'),
    )
    with op.batch_alter_table('whoop_workouts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_whoop_workouts_start'), ['start'], unique=False)
        batch_op.create_index(batch_op.f('ix_whoop_workouts_user_id'), ['user_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('whoop_workouts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_whoop_workouts_user_id'))
        batch_op.drop_index(batch_op.f('ix_whoop_workouts_start'))
    op.drop_table('whoop_workouts')

    with op.batch_alter_table('whoop_daily', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_whoop_daily_user_id'))
        batch_op.drop_index(batch_op.f('ix_whoop_daily_date'))
    op.drop_table('whoop_daily')
