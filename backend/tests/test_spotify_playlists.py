"""The playlist endpoints, against fixtures.

These exist mostly to pin the things about them that are easy to get wrong and that
CLAUDE.md calls out: ``public`` must be sent explicitly false, items go to ``/items`` and
not the deprecated ``/tracks``, the URIs go in the *body* there but in the *query* for
``GET /me/library/contains``, batches have a maximum size, and removing a playlist means
unfollowing it rather than ``DELETE /me/library`` (see :mod:`app.integrations.spotify.playlists`
for the measurement behind that).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from app.integrations.spotify import playlists
from app.integrations.spotify.client import SpotifyClient
from app.integrations.spotify.errors import SpotifyError

API = "https://api.spotify.com/v1"


class FakeTokens:
    async def get_access_token(self, *, force_refresh: bool = False) -> str:
        return "access-token"


@pytest.fixture
async def spotify() -> AsyncIterator[SpotifyClient]:
    async with SpotifyClient(FakeTokens()) as client:
        yield client


def playlist_body(playlist_id: str = "p1", name: str = "Chime · Focus · 9:20 am") -> dict:
    return {
        "id": playlist_id,
        "uri": f"spotify:playlist:{playlist_id}",
        "name": name,
        "public": False,
        "snapshot_id": "snap0",
        "external_urls": {"spotify": f"https://open.spotify.com/playlist/{playlist_id}"},
    }


@respx.mock
async def test_create_playlist_asks_for_a_private_one(spotify: SpotifyClient) -> None:
    """``public`` defaults to true at Spotify's end, so silence would publish it."""
    route = respx.post(f"{API}/me/playlists").mock(
        return_value=httpx.Response(201, json=playlist_body())
    )

    playlist = await playlists.create_playlist(
        spotify, name="Chime · Focus · 9:20 am", description="why"
    )

    assert playlist.id == "p1"
    assert playlist.uri == "spotify:playlist:p1"
    assert playlist.web_url == "https://open.spotify.com/playlist/p1"
    sent = respx.calls.last.request
    assert route.called
    assert json.loads(sent.content) == {
        "name": "Chime · Focus · 9:20 am",
        "public": False,
        "description": "why",
    }


@respx.mock
async def test_create_playlist_omits_an_empty_description(spotify: SpotifyClient) -> None:
    respx.post(f"{API}/me/playlists").mock(return_value=httpx.Response(201, json=playlist_body()))

    await playlists.create_playlist(spotify, name="Chime")

    body = json.loads(respx.calls.last.request.content)
    assert "description" not in body


@respx.mock
async def test_create_playlist_needs_a_body_it_can_read(spotify: SpotifyClient) -> None:
    respx.post(f"{API}/me/playlists").mock(return_value=httpx.Response(201, json=[1, 2, 3]))

    with pytest.raises(SpotifyError):
        await playlists.create_playlist(spotify, name="Chime")


@respx.mock
async def test_add_items_posts_to_items_with_the_uris_in_the_body(
    spotify: SpotifyClient,
) -> None:
    route = respx.post(f"{API}/playlists/p1/items").mock(
        return_value=httpx.Response(201, json={"snapshot_id": "snap1"})
    )
    tracks = respx.post(f"{API}/playlists/p1/tracks")

    snapshots = await playlists.add_items(
        spotify, "p1", ["spotify:track:t1", "spotify:track:t2"]
    )

    assert snapshots == ["snap1"]
    assert tracks.call_count == 0  # /tracks is deprecated for us
    assert route.call_count == 1
    body = json.loads(respx.calls.last.request.content)
    assert body == {"uris": ["spotify:track:t1", "spotify:track:t2"]}


@respx.mock
async def test_add_items_chunks_at_a_hundred_and_keeps_the_order(
    spotify: SpotifyClient,
) -> None:
    respx.post(f"{API}/playlists/p1/items").mock(
        side_effect=[
            httpx.Response(201, json={"snapshot_id": "snap1"}),
            httpx.Response(201, json={"snapshot_id": "snap2"}),
        ]
    )
    uris = [f"spotify:track:t{index}" for index in range(150)]

    snapshots = await playlists.add_items(spotify, "p1", uris)

    assert snapshots == ["snap1", "snap2"]
    sent = [json.loads(call.request.content)["uris"] for call in respx.calls]
    assert [len(chunk) for chunk in sent] == [100, 50]
    assert sent[0] + sent[1] == uris  # order survives the chunking


@respx.mock
async def test_add_items_tolerates_a_response_with_no_snapshot(spotify: SpotifyClient) -> None:
    respx.post(f"{API}/playlists/p1/items").mock(return_value=httpx.Response(201))

    assert await playlists.add_items(spotify, "p1", ["spotify:track:t1"]) == []


@respx.mock
async def test_add_items_does_nothing_when_there_is_nothing_to_add(
    spotify: SpotifyClient,
) -> None:
    route = respx.post(f"{API}/playlists/p1/items")

    assert await playlists.add_items(spotify, "p1", []) == []
    assert route.call_count == 0


@respx.mock
async def test_remove_items_sends_items_not_tracks(spotify: SpotifyClient) -> None:
    """The body key is ``items``. The deprecated ``/tracks`` route wanted ``tracks``.

    Checked against the official schema (``remove-items-playlist``, 2026-09-22) rather than
    inferred from the add endpoint, because the two are not symmetrical: adding takes a bare
    list of URIs under ``uris``, removing takes objects under ``items``. Sending ``tracks``
    here is a 400, and a 400 mid-session would silently leave a mix unadapted.
    """
    route = respx.delete(f"{API}/playlists/p1/items").mock(
        return_value=httpx.Response(200, json={"snapshot_id": "snap1"})
    )
    tracks = respx.delete(f"{API}/playlists/p1/tracks")

    snapshots = await playlists.remove_items(
        spotify, "p1", ["spotify:track:t1", "spotify:track:t2"]
    )

    assert snapshots == ["snap1"]
    assert tracks.call_count == 0
    assert route.call_count == 1
    body = json.loads(respx.calls.last.request.content)
    assert body == {"items": [{"uri": "spotify:track:t1"}, {"uri": "spotify:track:t2"}]}
    # No snapshot_id: the edit must not be conditional on the playlist being untouched, since
    # the only other thing editing it is the user.
    assert "snapshot_id" not in body


@respx.mock
async def test_remove_items_chunks_at_a_hundred(spotify: SpotifyClient) -> None:
    respx.delete(f"{API}/playlists/p1/items").mock(
        side_effect=[
            httpx.Response(200, json={"snapshot_id": "snap1"}),
            httpx.Response(200, json={"snapshot_id": "snap2"}),
        ]
    )
    uris = [f"spotify:track:t{index}" for index in range(150)]

    snapshots = await playlists.remove_items(spotify, "p1", uris)

    assert snapshots == ["snap1", "snap2"]
    sent = [json.loads(call.request.content)["items"] for call in respx.calls]
    assert [len(chunk) for chunk in sent] == [100, 50]
    assert [item["uri"] for item in sent[0] + sent[1]] == uris


@respx.mock
async def test_remove_items_does_nothing_when_there_is_nothing_to_remove(
    spotify: SpotifyClient,
) -> None:
    route = respx.delete(f"{API}/playlists/p1/items")

    assert await playlists.remove_items(spotify, "p1", []) == []
    assert route.call_count == 0


@respx.mock
async def test_rename_playlist_puts_the_new_details(spotify: SpotifyClient) -> None:
    route = respx.put(f"{API}/playlists/p1").mock(return_value=httpx.Response(200))

    await playlists.rename_playlist(spotify, "p1", name="Focus · 22 Sep")

    assert route.called
    body = json.loads(respx.calls.last.request.content)
    assert body == {"name": "Focus · 22 Sep"}


@respx.mock
async def test_remove_playlist_unfollows_it(spotify: SpotifyClient) -> None:
    """Not ``DELETE /me/library``, which wants two scopes we do not hold (see the module)."""
    route = respx.delete(f"{API}/playlists/p1/followers").mock(return_value=httpx.Response(200))

    await playlists.remove_playlist(spotify, "p1")

    assert route.call_count == 1
    assert not respx.calls.last.request.content


@respx.mock
async def test_remove_playlist_raises_when_spotify_refuses(spotify: SpotifyClient) -> None:
    """A refusal has to reach the caller: Chime out reports it instead of claiming success."""
    respx.delete(f"{API}/playlists/p1/followers").mock(
        return_value=httpx.Response(403, json={"error": {"status": 403, "message": "nope"}})
    )

    with pytest.raises(SpotifyError):
        await playlists.remove_playlist(spotify, "p1")


@respx.mock
async def test_is_in_library_answers_one_boolean_per_uri(spotify: SpotifyClient) -> None:
    respx.get(f"{API}/me/library/contains").mock(
        return_value=httpx.Response(200, json=[True, False])
    )

    asked = ["spotify:playlist:p1", "spotify:playlist:p2"]

    assert await playlists.is_in_library(spotify, asked) == [True, False]
    assert respx.calls.last.request.url.params["uris"] == (
        "spotify:playlist:p1,spotify:playlist:p2"
    )


@respx.mock
async def test_is_in_library_does_not_call_out_for_an_empty_list(
    spotify: SpotifyClient,
) -> None:
    route = respx.get(f"{API}/me/library/contains")

    assert await playlists.is_in_library(spotify, []) == []
    assert route.call_count == 0


@respx.mock
async def test_is_in_library_falls_back_to_false_on_an_unreadable_body(
    spotify: SpotifyClient,
) -> None:
    respx.get(f"{API}/me/library/contains").mock(
        return_value=httpx.Response(200, json={"unexpected": True})
    )

    assert await playlists.is_in_library(spotify, ["spotify:playlist:p1"]) == [False]
