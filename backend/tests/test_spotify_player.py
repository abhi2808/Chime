"""Playback control, against fixtures.

Two things here are worth more than the rest. Device picking, because it is the only
decision in the module and it runs before anything is created. And the refusal mapping:
"you are not Premium" and "nothing is open to play on" are the two failures we cannot
check for in advance (CLAUDE.md rule 5), so they have to arrive as types the UI can speak
about rather than as a generic 403.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import respx

from app.integrations.spotify import player
from app.integrations.spotify.client import SpotifyClient
from app.integrations.spotify.errors import (
    SpotifyError,
    SpotifyNoActiveDeviceError,
    SpotifyNotFoundError,
    SpotifyPremiumRequiredError,
    SpotifyRestrictedDeviceError,
)
from app.integrations.spotify.schemas import SpotifyDevice

API = "https://api.spotify.com/v1"


class FakeTokens:
    async def get_access_token(self, *, force_refresh: bool = False) -> str:
        return "access-token"


@pytest.fixture
async def spotify() -> AsyncIterator[SpotifyClient]:
    async with SpotifyClient(FakeTokens()) as client:
        yield client


def device(
    device_id: str | None = "d1",
    *,
    name: str = "Phone",
    kind: str = "smartphone",
    active: bool = False,
    restricted: bool = False,
) -> SpotifyDevice:
    return SpotifyDevice(
        id=device_id, name=name, type=kind, is_active=active, is_restricted=restricted
    )


def refusal(status: int, reason: str) -> httpx.Response:
    """What a player endpoint actually returns when it will not do something."""
    body = {"status": status, "message": "Player command failed", "reason": reason}
    return httpx.Response(status, json={"error": body})


# --------------------------------------------------------------------- devices


@respx.mock
async def test_get_devices_parses_the_list(spotify: SpotifyClient) -> None:
    respx.get(f"{API}/me/player/devices").mock(
        return_value=httpx.Response(
            200,
            json={
                "devices": [
                    {
                        "id": "d1",
                        "name": "Kitchen speaker",
                        "type": "Speaker",
                        "is_active": True,
                        "is_restricted": False,
                        "volume_percent": 40,
                        # A field we do not model: it must be ignored, not fatal.
                        "supports_volume": True,
                    }
                ]
            },
        )
    )

    devices = await player.get_devices(spotify)

    assert len(devices) == 1
    assert devices[0].name == "Kitchen speaker"
    assert devices[0].is_usable is True


@respx.mock
async def test_no_devices_is_an_answer_not_an_error(spotify: SpotifyClient) -> None:
    """The normal response when Spotify is closed everywhere."""
    respx.get(f"{API}/me/player/devices").mock(
        return_value=httpx.Response(200, json={"devices": []})
    )

    assert await player.get_devices(spotify) == []


@respx.mock
async def test_get_devices_survives_an_empty_body(spotify: SpotifyClient) -> None:
    respx.get(f"{API}/me/player/devices").mock(return_value=httpx.Response(204))

    assert await player.get_devices(spotify) == []


def test_pick_device_prefers_the_one_already_playing() -> None:
    chosen = player.pick_device(
        [device("d1", kind="tv"), device("d2", name="Laptop", kind="computer", active=True)]
    )

    assert chosen is not None
    assert chosen.id == "d2"


def test_pick_device_ignores_restricted_devices() -> None:
    """Listed, but documented as refusing every Web API command."""
    chosen = player.pick_device(
        [
            device("d1", name="Car", kind="computer", active=True, restricted=True),
            device("d2", name="Phone"),
        ]
    )

    assert chosen is not None
    assert chosen.id == "d2"


def test_pick_device_ignores_a_device_with_no_id() -> None:
    assert player.pick_device([device(None, active=True)]) is None


def test_pick_device_falls_back_to_the_most_likely_to_be_in_reach() -> None:
    chosen = player.pick_device(
        [device("d1", name="TV", kind="tv"), device("d2", name="Laptop", kind="computer")]
    )

    assert chosen is not None
    assert chosen.id == "d2"  # a computer that is awake beats a TV nobody is watching


def test_pick_device_puts_an_unknown_type_last() -> None:
    chosen = player.pick_device(
        [device("d1", name="Fridge", kind="appliance"), device("d2", name="TV", kind="tv")]
    )

    assert chosen is not None
    assert chosen.id == "d2"


def test_pick_device_on_an_empty_list() -> None:
    assert player.pick_device([]) is None


# -------------------------------------------------------------------- playback


@respx.mock
async def test_transfer_playback_does_not_start_playing_by_itself(
    spotify: SpotifyClient,
) -> None:
    route = respx.put(f"{API}/me/player").mock(return_value=httpx.Response(204))

    await player.transfer_playback(spotify, "d1")

    assert route.called
    assert json.loads(respx.calls.last.request.content) == {"device_ids": ["d1"], "play": False}


@respx.mock
async def test_start_playback_sends_the_playlist_as_a_context(spotify: SpotifyClient) -> None:
    """A context, not a list of uris, so next/previous walk the session in order."""
    route = respx.put(f"{API}/me/player/play").mock(return_value=httpx.Response(204))

    await player.start_playback(spotify, context_uri="spotify:playlist:p1", device_id="d1")

    assert route.called
    request = respx.calls.last.request
    assert request.url.params["device_id"] == "d1"
    assert json.loads(request.content) == {"context_uri": "spotify:playlist:p1"}


@respx.mock
async def test_start_playback_can_start_part_way_in(spotify: SpotifyClient) -> None:
    respx.put(f"{API}/me/player/play").mock(return_value=httpx.Response(204))

    await player.start_playback(
        spotify, context_uri="spotify:playlist:p1", position=3, position_ms=15_000
    )

    assert json.loads(respx.calls.last.request.content) == {
        "context_uri": "spotify:playlist:p1",
        "offset": {"position": 3},
        "position_ms": 15_000,
    }


@respx.mock
async def test_start_playback_can_take_bare_uris(spotify: SpotifyClient) -> None:
    respx.put(f"{API}/me/player/play").mock(return_value=httpx.Response(204))

    await player.start_playback(spotify, uris=["spotify:track:t1"])

    assert json.loads(respx.calls.last.request.content) == {"uris": ["spotify:track:t1"]}


@respx.mock
async def test_playback_state_reads_what_is_playing(spotify: SpotifyClient) -> None:
    respx.get(f"{API}/me/player").mock(
        return_value=httpx.Response(
            200,
            json={
                "is_playing": True,
                "progress_ms": 42_000,
                "device": {"id": "d1", "name": "Phone", "type": "Smartphone"},
                "context": {"uri": "spotify:playlist:p1", "type": "playlist"},
                "item": {
                    "id": "t1",
                    "name": "Something",
                    "duration_ms": 200_000,
                    "artists": [{"id": "a1", "name": "Alpha"}],
                    "album": {
                        "id": "al1",
                        "name": "An album",
                        "images": [{"url": "https://i.scdn.co/big", "width": 640, "height": 640}],
                    },
                },
            },
        )
    )

    state = await player.get_playback_state(spotify)

    assert state is not None
    assert state.is_playing is True
    assert state.track_id == "t1"
    assert state.progress_ms == 42_000
    assert state.context is not None and state.context.uri == "spotify:playlist:p1"
    assert state.item is not None and state.item.image_url == "https://i.scdn.co/big"


@respx.mock
async def test_playback_state_is_none_when_nothing_is_playing(spotify: SpotifyClient) -> None:
    """``GET /me/player`` answers 204 with no body, which is not an error."""
    respx.get(f"{API}/me/player").mock(return_value=httpx.Response(204))

    assert await player.get_playback_state(spotify) is None


@respx.mock
@pytest.mark.parametrize(
    ("command", "method", "path"),
    [
        (player.pause, "PUT", "/me/player/pause"),
        (player.resume, "PUT", "/me/player/play"),
        (player.next_track, "POST", "/me/player/next"),
        (player.previous_track, "POST", "/me/player/previous"),
    ],
)
async def test_the_transport_controls_hit_their_own_endpoints(
    spotify: SpotifyClient, command: Any, method: str, path: str
) -> None:
    route = respx.request(method, f"{API}{path}").mock(return_value=httpx.Response(204))

    await command(spotify)

    assert route.call_count == 1


@respx.mock
async def test_resume_sends_no_body(spotify: SpotifyClient) -> None:
    """A body would restart the context instead of picking up where it stopped."""
    respx.put(f"{API}/me/player/play").mock(return_value=httpx.Response(204))

    await player.resume(spotify)

    assert not respx.calls.last.request.content


# -------------------------------------------------------------------- refusals


@respx.mock
@pytest.mark.parametrize(
    ("status", "reason", "expected"),
    [
        (403, "PREMIUM_REQUIRED", SpotifyPremiumRequiredError),
        (404, "NO_ACTIVE_DEVICE", SpotifyNoActiveDeviceError),
        (403, "DEVICE_NOT_CONTROLLABLE", SpotifyRestrictedDeviceError),
        (403, "REMOTE_CONTROL_DISALLOWED", SpotifyRestrictedDeviceError),
    ],
)
async def test_a_refusal_reason_becomes_its_own_error_type(
    spotify: SpotifyClient, status: int, reason: str, expected: type[SpotifyError]
) -> None:
    respx.put(f"{API}/me/player/play").mock(return_value=refusal(status, reason))

    with pytest.raises(expected) as caught:
        await player.start_playback(spotify, context_uri="spotify:playlist:p1")

    assert caught.value.code == reason
    assert caught.value.status == status
    assert caught.value.message == "Player command failed"


@respx.mock
async def test_a_failure_with_no_reason_stays_a_plain_spotify_error(
    spotify: SpotifyClient,
) -> None:
    respx.put(f"{API}/me/player/play").mock(
        return_value=httpx.Response(403, json={"error": {"status": 403, "message": "nope"}})
    )

    with pytest.raises(SpotifyError) as caught:
        await player.start_playback(spotify, context_uri="spotify:playlist:p1")

    assert type(caught.value) is SpotifyError
    assert caught.value.code is None


@respx.mock
async def test_a_404_without_a_reason_is_still_a_not_found(spotify: SpotifyClient) -> None:
    """So the device-specific 404 does not swallow every other missing resource."""
    respx.post(f"{API}/me/player/next").mock(return_value=httpx.Response(404))

    with pytest.raises(SpotifyNotFoundError):
        await player.next_track(spotify)
