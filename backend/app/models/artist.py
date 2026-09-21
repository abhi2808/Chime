from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base


class Artist(Base):
    """Shared Spotify artist cache.

    ``genres`` is marked deprecated in Spotify's current docs and may arrive empty or
    absent, so it stays nullable: ``None`` means we have not fetched it (or the field
    was missing), ``[]`` means Spotify returned no genres.
    """

    __tablename__ = "artists"

    id: Mapped[int] = mapped_column(primary_key=True)
    spotify_artist_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(512), default=None)
    genres: Mapped[list[str] | None] = mapped_column(JSON, default=None)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
