"""Typed Spotify responses.

Every model ignores unknown keys and defaults anything optional, because Spotify has
been removing and deprecating fields (``genres``, ``popularity``, ``preview_url``,
``product``/``country``/``email`` on the profile) without changing endpoint paths.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.integrations.oauth import OAuthTokenResponse


class SpotifyModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


#: Spotify's token body has no Spotify-specific fields. Under PKCE the refresh response
#: may omit ``refresh_token``; the shared model keeps it optional for that reason.
TokenResponse = OAuthTokenResponse


class SpotifyProfile(SpotifyModel):
    """``GET /me``.

    ``account_id`` is documented as the stable identifier; ``id`` now carries an
    explicit "do not use for account linking" warning but is the value a user can read
    off their own profile URL, so we keep both.
    """

    id: str | None = None
    account_id: str | None = None
    display_name: str | None = None

    @property
    def stable_id(self) -> str | None:
        return self.account_id or self.id


class SpotifyImage(SpotifyModel):
    url: str
    height: int | None = None
    width: int | None = None


class SpotifyArtistRef(SpotifyModel):
    id: str | None = None
    name: str | None = None


class SpotifyAlbumRef(SpotifyModel):
    id: str | None = None
    name: str | None = None
    images: list[SpotifyImage] = Field(default_factory=list)


class SpotifyTrack(SpotifyModel):
    id: str | None = None
    name: str | None = None
    artists: list[SpotifyArtistRef] = Field(default_factory=list)
    album: SpotifyAlbumRef | None = None
    duration_ms: int = 0
    explicit: bool = False
    is_local: bool = False

    @property
    def artist_ids(self) -> list[str]:
        return [artist.id for artist in self.artists if artist.id]

    @property
    def artist_names(self) -> list[str]:
        return [artist.name for artist in self.artists if artist.name]

    @property
    def image_url(self) -> str | None:
        if not self.album or not self.album.images:
            return None
        # Keep the largest: session artwork is big, list rows can scale down.
        return max(self.album.images, key=lambda image: image.width or 0).url


class SavedTrackItem(SpotifyModel):
    added_at: datetime | None = None
    track: SpotifyTrack | None = None


class SavedTracksPage(SpotifyModel):
    """``GET /me/tracks`` — limit is documented as 0-50, default 20."""

    items: list[SavedTrackItem] = Field(default_factory=list)
    next: str | None = None
    total: int = 0
    limit: int = 0
    offset: int = 0


class SpotifyArtist(SpotifyModel):
    """``GET /artists/{id}``.

    ``genres`` is flagged deprecated in the current docs, so ``None`` (absent) and
    ``[]`` (present but empty) are both expected and are stored differently.
    """

    id: str | None = None
    name: str | None = None
    genres: list[str] | None = None
