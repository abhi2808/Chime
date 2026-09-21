"""Who is allowed in, and upserting them.

Dev Mode caps the app at 5 authorised Spotify users and there is no signup flow:
``ALLOWED_SPOTIFY_USER_IDS`` is the whole access model, and an empty value means the
first account to log in becomes the owner.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.spotify.schemas import SpotifyProfile
from app.models import User

logger = logging.getLogger(__name__)


class ProfileUnusable(Exception):
    """Spotify returned a profile with no usable identifier."""


class UserNotAllowed(Exception):
    """A real Spotify account that this install refuses to serve."""


def find_user(db: Session, profile: SpotifyProfile) -> User | None:
    candidates = [value for value in (profile.account_id, profile.id) if value]
    if not candidates:
        return None
    return db.scalar(
        select(User).where(
            or_(
                User.spotify_account_id.in_(candidates),
                User.spotify_user_id.in_(candidates),
            )
        )
    )


def upsert_user(db: Session, profile: SpotifyProfile) -> User:
    """Return the signed-in user, creating them if this install will have them.

    Raises :class:`UserNotAllowed` when the allowlist (or the first-user-is-owner rule)
    says no.
    """
    stable_id = profile.stable_id
    if not stable_id:
        raise ProfileUnusable("Spotify returned a profile without an id")

    user = find_user(db, profile)
    allowlist = settings.allowed_spotify_user_id_list

    if user is None:
        if allowlist:
            if not ({profile.account_id, profile.id} & set(allowlist)):
                raise UserNotAllowed(stable_id)
        else:
            existing = db.scalar(select(func.count()).select_from(User)) or 0
            if existing:
                raise UserNotAllowed(stable_id)
            logger.info("first login claims ownership of this install")
        user = User(spotify_account_id=stable_id)
        db.add(user)

    user.spotify_account_id = stable_id
    user.spotify_user_id = profile.id
    if profile.display_name:
        user.display_name = profile.display_name

    db.flush()
    return user
