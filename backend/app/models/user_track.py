from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserTrack(Base):
    """One row per (user, track, source). Phase 1 only writes source='liked'."""

    __tablename__ = "user_tracks"
    __table_args__ = (
        UniqueConstraint("user_id", "track_id", "source", name="uq_user_tracks_user_track_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(16))  # liked | playlist | top | recent
    liked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    plays: Mapped[int] = mapped_column(Integer, default=0)
    completes: Mapped[int] = mapped_column(Integer, default=0)
    fast_skips: Mapped[int] = mapped_column(Integer, default=0)
    kept_count: Mapped[int] = mapped_column(Integer, default=0)
    energy_override: Mapped[float | None] = mapped_column(Float, default=None)
    last_played_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
