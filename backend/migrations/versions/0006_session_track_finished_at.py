"""session_tracks.finished_at

The live loop's one new column (phase 6). A poller sees snapshots, so it needs somewhere to
record that a row's fate has been decided: ``skipped = False`` on its own cannot be told
apart from "still playing, nothing judged yet".

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-22 18:05:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0006'
down_revision: str | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('session_tracks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('session_tracks', schema=None) as batch_op:
        batch_op.drop_column('finished_at')
