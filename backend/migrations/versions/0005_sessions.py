"""sessions, session_tracks, session_events

One Chime in and everything that followed it (SPEC section 4). ``session_tracks`` outlives
the Spotify playlist on purpose: the playlist is temporary, so our own rows are what
History reads and what "bring it back" recreates from.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-22 00:29:40.567929
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('type', sa.String(length=16), nullable=False),
    sa.Column('intent', sa.String(length=8), nullable=False),
    sa.Column('mood_in', sa.String(length=16), nullable=True),
    sa.Column('mood_out', sa.String(length=16), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('body_in', sa.JSON(), nullable=True),
    sa.Column('body_out', sa.JSON(), nullable=True),
    sa.Column('playlist_uri', sa.String(length=64), nullable=True),
    sa.Column('playlist_name', sa.String(length=255), nullable=True),
    sa.Column('kept', sa.Boolean(), nullable=False),
    sa.Column('playlist_removed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('target_profile', sa.JSON(), nullable=True),
    sa.Column('why_text', sa.Text(), nullable=True),
    sa.Column('summary', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sessions_started_at'), ['started_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_sessions_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_sessions_user_id'), ['user_id'], unique=False)

    op.create_table('session_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('type', sa.String(length=16), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('session_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_session_events_session_id'), ['session_id'], unique=False)

    op.create_table('session_tracks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('track_id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('played_ms', sa.Integer(), nullable=False),
    sa.Column('skipped', sa.Boolean(), nullable=False),
    sa.Column('score_breakdown', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['track_id'], ['tracks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('session_tracks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_session_tracks_session_id'), ['session_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_session_tracks_track_id'), ['track_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('session_tracks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_session_tracks_track_id'))
        batch_op.drop_index(batch_op.f('ix_session_tracks_session_id'))

    op.drop_table('session_tracks')
    with op.batch_alter_table('session_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_session_events_session_id'))

    op.drop_table('session_events')
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sessions_user_id'))
        batch_op.drop_index(batch_op.f('ix_sessions_status'))
        batch_op.drop_index(batch_op.f('ix_sessions_started_at'))

    op.drop_table('sessions')
