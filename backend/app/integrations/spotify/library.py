"""The read-only Spotify calls Phase 1 needs.

Only endpoints that are documented and allowed by CLAUDE.md appear here. In
particular there is no "Get Several Artists": that endpoint is deprecated, so unique
artists are fetched one at a time at low concurrency.
"""

from __future__ import annotations

from app.integrations.spotify.client import SpotifyClient
from app.integrations.spotify.schemas import (
    SavedTracksPage,
    SpotifyArtist,
    SpotifyProfile,
    parse,
)

MAX_SAVED_TRACKS_LIMIT = 50


async def get_current_profile(client: SpotifyClient) -> SpotifyProfile:
    return parse(SpotifyProfile, await client.get_json("/me"), "profile")


async def get_saved_tracks(
    client: SpotifyClient, *, limit: int = MAX_SAVED_TRACKS_LIMIT, offset: int = 0
) -> SavedTracksPage:
    limit = max(1, min(limit, MAX_SAVED_TRACKS_LIMIT))
    payload = await client.get_json("/me/tracks", params={"limit": limit, "offset": offset})
    return parse(SavedTracksPage, payload, "page of liked songs")


async def get_artist(client: SpotifyClient, artist_id: str) -> SpotifyArtist:
    return parse(SpotifyArtist, await client.get_json(f"/artists/{artist_id}"), "artist")
