from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base

SYNC_IDLE = "idle"
SYNC_RUNNING = "running"
SYNC_COMPLETE = "complete"
# Everything that got through is stored and usable; the rest waits for the next run.
# Used when Spotify rate limits us or the artist phase runs out of its time budget.
SYNC_PARTIAL = "partial"
SYNC_ERROR = "error"

PHASE_TRACKS = "tracks"
PHASE_ARTISTS = "artists"


class LibrarySyncState(Base):
    """Durable progress for the library sync, one row per user.

    Not in SPEC section 4: the status endpoint and "resumable if interrupted" both
    need progress to survive a restart, which in-memory state cannot do.
    """

    __tablename__ = "library_sync_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    state: Mapped[str] = mapped_column(String(16), default=SYNC_IDLE)
    phase: Mapped[str | None] = mapped_column(String(16), default=None)
    mode: Mapped[str | None] = mapped_column(String(16), default=None)  # incremental | full
    next_offset: Mapped[int] = mapped_column(Integer, default=0)
    tracks_total: Mapped[int | None] = mapped_column(Integer, default=None)
    tracks_synced: Mapped[int] = mapped_column(Integer, default=0)
    artists_total: Mapped[int] = mapped_column(Integer, default=0)
    artists_fetched: Mapped[int] = mapped_column(Integer, default=0)
    artists_failed: Mapped[int] = mapped_column(Integer, default=0)
    stopped_early: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # When Spotify said it would answer again, taken from Retry-After on a 429.
    resume_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
