from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base


class Track(Base):
    """Shared, minimal Spotify track cache (SPEC section 4).

    Deliberately no popularity/preview_url/available_markets: all three are deprecated
    in Spotify's docs and none of them feed the engine.
    """

    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(primary_key=True)
    spotify_track_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(512))
    artist_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    artist_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    album_name: Mapped[str | None] = mapped_column(String(512), default=None)
    image_url: Mapped[str | None] = mapped_column(String(1024), default=None)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    explicit: Mapped[bool] = mapped_column(Boolean, default=False)
    cached_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
