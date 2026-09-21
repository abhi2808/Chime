from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base


class User(Base):
    """A person allowed to use this Chime install.

    Spotify's profile now documents ``account_id`` as the stable identifier and warns
    against using ``id`` for account linking, so ``spotify_account_id`` is the key we
    match on. ``spotify_user_id`` keeps the public id for profile links and for
    allowlist entries, since that is the value visible in a Spotify profile URL.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    spotify_account_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    spotify_user_id: Mapped[str | None] = mapped_column(String(128), index=True, default=None)
    display_name: Mapped[str | None] = mapped_column(String(255), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
