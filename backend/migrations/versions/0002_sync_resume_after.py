"""library_sync_state.resume_after

Records when Spotify said it would answer again (Retry-After on a 429), so a sync that
stopped early knows when it is worth resuming.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-20 03:40:48.181989
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('library_sync_state', schema=None) as batch_op:
        batch_op.add_column(sa.Column('resume_after', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('library_sync_state', schema=None) as batch_op:
        batch_op.drop_column('resume_after')
