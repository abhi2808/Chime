"""Importing this package registers every table on ``Base.metadata``."""

from app.models.artist import Artist
from app.models.library_sync import (
    PHASE_ARTISTS,
    PHASE_TRACKS,
    SYNC_COMPLETE,
    SYNC_ERROR,
    SYNC_IDLE,
    SYNC_PARTIAL,
    SYNC_RUNNING,
    LibrarySyncState,
)
from app.models.oauth_token import OAuthToken
from app.models.track import Track
from app.models.user import User
from app.models.user_track import UserTrack
from app.models.whoop import WhoopDaily, WhoopWorkout

__all__ = [
    "PHASE_ARTISTS",
    "PHASE_TRACKS",
    "SYNC_COMPLETE",
    "SYNC_ERROR",
    "SYNC_IDLE",
    "SYNC_PARTIAL",
    "SYNC_RUNNING",
    "Artist",
    "LibrarySyncState",
    "OAuthToken",
    "Track",
    "User",
    "UserTrack",
    "WhoopDaily",
    "WhoopWorkout",
]
