from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base

#: Where the energy/affinity numbers came from, worst to best.
SOURCE_UNKNOWN = "unknown"  # nothing matched; energy 3 at low confidence
SOURCE_MAP = "map"  # Spotify artist genres run through tag_map
SOURCE_EXTERNAL = "external"  # a TagSource (MusicBrainz) supplied the tags
SOURCE_MANUAL = "manual"  # a human set it; never overwritten by a re-tag

SOURCES = (SOURCE_UNKNOWN, SOURCE_MAP, SOURCE_EXTERNAL, SOURCE_MANUAL)


class TrackTag(Base):
    """Deterministic energy/affinity tags for a track, shared across users.

    Per-user taste lives in ``user_tracks`` (``energy_override``, behavior counters);
    this table is the objective half, so one lookup serves every user.

    ``raw_tags`` keeps the ``[[tag, weight], ...]`` pairs the source gave us so the
    mapping table can be re-tuned and re-applied offline, without spending a second
    round of external requests on a library we have already fetched.
    """

    __tablename__ = "track_tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    track_id: Mapped[int] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), unique=True, index=True
    )
    #: 1-5, fractional because it is a weighted average of several tags.
    energy: Mapped[float] = mapped_column(Float, default=3.0)
    #: {"calm": 0.9, "focus": 0.8, ...}, each 0-1. Absent key means no affinity.
    affinities: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(16), default=SOURCE_UNKNOWN)
    #: 0-1. Drives how much ranking trusts ``energy`` over a neutral assumption.
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    raw_tags: Mapped[list[list] | None] = mapped_column(JSON, default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
