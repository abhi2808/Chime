"""Creating, filling, renaming and disposing of a session's playlist.

Verified against the current docs (2026-09-22), because three of these four have moved:

* ``POST /me/playlists`` — ``public`` defaults to **true**, so private must be explicit.
* ``POST /playlists/{id}/items`` — ``/items``, not the deprecated ``/tracks``. Max 100 per
  request, and the URIs go in the body: as a query string a full playlist would exceed the
  maximum request URI length.
* ``DELETE /playlists/{id}/items`` — take tracks back out, used by mid-session adaptation.
  The body key is ``items``, **not** ``tracks``: the deprecated ``/tracks`` route wanted
  ``tracks``, and sending that here is a 400. Checked against the official schema
  (``remove-items-playlist``, 2026-09-22), which also shows no support for a ``positions``
  array any more, so a removal takes out *every* occurrence of a URI.
* ``PUT /playlists/{id}`` — rename, used when a session is kept.
* ``DELETE /playlists/{id}/followers`` — there is no true playlist delete. Dropping it out
  of the library is the closest thing, and it answers 200 with an empty body.

Why not ``DELETE /me/library?uris=``, which CLAUDE.md rule 2 named: it does accept
``spotify:playlist:`` URIs, but the official schema asks for ``user-library-modify`` **and**
``user-follow-modify`` **and** ``playlist-modify-public`` together, and live it answers
``403 Insufficient client scope`` on a grant holding the first of those. Measured on a real
account (2026-09-22), not inferred. ``DELETE /playlists/{id}/followers`` is documented in
the same schema, asks only for ``playlist-modify-public`` *or* ``-private``, and removed the
playlist for real: ``GET /me/library/contains`` went from ``[true]`` to ``[false]``. So this
route needs no extra consent, and "remove the playlist unless the user keeps it" is a
promise Chime can actually keep. Decided with the owner; rule 2 amended to match.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.integrations.spotify.client import SpotifyClient
from app.integrations.spotify.schemas import SpotifyPlaylist, parse

#: ``POST /playlists/{id}/items`` takes at most 100 URIs at a time.
MAX_ITEMS_PER_REQUEST = 100

#: ``GET /me/library/contains`` takes at most 40 URIs at a time.
MAX_LIBRARY_URIS = 40


async def create_playlist(
    client: SpotifyClient,
    *,
    name: str,
    description: str = "",
    public: bool = False,
) -> SpotifyPlaylist:
    """Create an empty playlist owned by the signed-in user.

    Private by default and by intent: a session playlist is scratch space, and Spotify
    would otherwise publish it on the user's profile.
    """
    payload: dict[str, object] = {"name": name, "public": public}
    if description:
        payload["description"] = description
    response = await client.request("POST", "/me/playlists", json=payload)
    return parse(SpotifyPlaylist, response.json(), "new playlist")


async def add_items(
    client: SpotifyClient, playlist_id: str, uris: Sequence[str]
) -> list[str]:
    """Append tracks in order, in chunks of 100. Returns each chunk's snapshot id.

    Chunked even though a session is ~25 tracks, because "bring it back" in History can
    recreate a much longer one and the limit is the endpoint's, not ours.
    """
    snapshots: list[str] = []
    for start in range(0, len(uris), MAX_ITEMS_PER_REQUEST):
        chunk = list(uris[start : start + MAX_ITEMS_PER_REQUEST])
        if not chunk:
            continue
        response = await client.request(
            "POST", f"/playlists/{playlist_id}/items", json={"uris": chunk}
        )
        try:
            body = response.json()
        except ValueError:
            body = {}
        snapshot = body.get("snapshot_id") if isinstance(body, dict) else None
        if snapshot:
            snapshots.append(str(snapshot))
    return snapshots


async def remove_items(
    client: SpotifyClient, playlist_id: str, uris: Sequence[str]
) -> list[str]:
    """Take tracks out of a playlist, in chunks of 100. Returns each chunk's snapshot id.

    Every occurrence of a URI goes, since the endpoint no longer takes positions. Chime only
    ever calls this for tracks it is about to stop offering, so a duplicate disappearing with
    its twin is what we want anyway.

    No ``snapshot_id`` is sent on purpose. It would make the edit conditional on the playlist
    not having changed since we read it, and the one thing that edits a session playlist
    besides us is the user — whose change we should not be undoing on a stale snapshot.
    """
    snapshots: list[str] = []
    for start in range(0, len(uris), MAX_ITEMS_PER_REQUEST):
        chunk = [{"uri": uri} for uri in uris[start : start + MAX_ITEMS_PER_REQUEST]]
        if not chunk:
            continue
        response = await client.request(
            "DELETE", f"/playlists/{playlist_id}/items", json={"items": chunk}
        )
        try:
            body = response.json()
        except ValueError:
            body = {}
        snapshot = body.get("snapshot_id") if isinstance(body, dict) else None
        if snapshot:
            snapshots.append(str(snapshot))
    return snapshots


async def rename_playlist(
    client: SpotifyClient, playlist_id: str, *, name: str, description: str | None = None
) -> None:
    """Change the details of a playlist the user has decided to keep."""
    payload: dict[str, object] = {"name": name}
    if description is not None:
        payload["description"] = description
    await client.request("PUT", f"/playlists/{playlist_id}", json=payload)


async def remove_playlist(client: SpotifyClient, playlist_id: str) -> None:
    """Drop a playlist out of the user's library.

    As close to delete as the API gets: the playlist still exists at its URI, it is simply
    no longer in the library and no longer on the profile. Anyone holding the link can still
    open it, which is why History can bring a session back at all.
    """
    await client.request("DELETE", f"/playlists/{playlist_id}/followers")


async def is_in_library(client: SpotifyClient, uris: Sequence[str]) -> list[bool]:
    """``GET /me/library/contains``: one boolean per URI, in the order asked."""
    if not uris:
        return []
    payload = await client.get_json("/me/library/contains", params={"uris": ",".join(uris)})
    if not isinstance(payload, list):
        return [False] * len(uris)
    return [bool(value) for value in payload]
