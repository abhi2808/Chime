"""Typed Spotify responses.

Every model ignores unknown keys and defaults anything optional, because Spotify has
been removing and deprecating fields (``genres``, ``popularity``, ``preview_url``,
``product``/``country``/``email`` on the profile) without changing endpoint paths.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.integrations.oauth import OAuthTokenResponse
from app.integrations.spotify.errors import SpotifyError


class SpotifyModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


ModelT = TypeVar("ModelT", bound=BaseModel)


def parse(model: type[ModelT], payload: Any, what: str) -> ModelT:
    """Turn an unusable body into a typed Spotify error.

    Callers already handle ``SpotifyError`` per item, so one malformed response costs one
    item instead of the whole job. A raw pydantic error would escape that handling.
    """
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise SpotifyError(f"Spotify returned a {what} we could not read") from exc


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


class SpotifyPlaylist(SpotifyModel):
    """``POST /me/playlists`` and ``GET /playlists/{id}``.

    Only the handful of fields a session needs. ``uri`` is what the player takes as a
    ``context_uri``; ``id`` is what the playlist endpoints take in their path.
    """

    id: str | None = None
    uri: str | None = None
    name: str | None = None
    public: bool | None = None
    snapshot_id: str | None = None
    external_urls: dict[str, str] = Field(default_factory=dict)

    @property
    def web_url(self) -> str | None:
        """Where to send a browser. The only link "Open in Spotify" can use."""
        return self.external_urls.get("spotify")


class SpotifyDevice(SpotifyModel):
    """One entry of ``GET /me/player/devices``."""

    id: str | None = None
    name: str | None = None
    type: str | None = None
    is_active: bool = False
    is_private_session: bool = False
    #: Documented as "no Web API commands will be accepted by this device".
    is_restricted: bool = False
    volume_percent: int | None = None
    supports_volume: bool = False

    @property
    def is_usable(self) -> bool:
        """Has an id we can target and will actually accept a command."""
        return bool(self.id) and not self.is_restricted


class DevicesResponse(SpotifyModel):
    devices: list[SpotifyDevice] = Field(default_factory=list)


class PlaybackContext(SpotifyModel):
    uri: str | None = None
    type: str | None = None


class PlaybackState(SpotifyModel):
    """``GET /me/player``, which answers 204 with no body when nothing is playing."""

    is_playing: bool = False
    progress_ms: int | None = None
    item: SpotifyTrack | None = None
    device: SpotifyDevice | None = None
    context: PlaybackContext | None = None
    shuffle_state: bool = False
    repeat_state: str | None = None

    @property
    def track_id(self) -> str | None:
        return self.item.id if self.item else None


class SpotifyArtist(SpotifyModel):
    """``GET /artists/{id}``.

    ``genres`` is flagged deprecated in the current docs, so ``None`` (absent) and
    ``[]`` (present but empty) are both expected and are stored differently.
    """

    id: str | None = None
    name: str | None = None
    genres: list[str] | None = None
