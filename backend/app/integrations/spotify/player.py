"""Playback control.

Two things shape this module, both from CLAUDE.md:

* **We cannot detect Premium.** ``GET /me`` no longer returns ``product``, so there is no
  check to make before acting. Every call here can fail with PREMIUM_REQUIRED and the
  client turns that into :class:`SpotifyPremiumRequiredError` for the UI to explain.
* **We cannot open Spotify for the user.** If no device is listed there is nothing to play
  on, and the honest answer is an instruction, not a retry.
"""

from __future__ import annotations

from app.integrations.spotify.client import SpotifyClient
from app.integrations.spotify.schemas import DevicesResponse, PlaybackState, SpotifyDevice, parse

#: Device types we would rather wake up first, best last. A phone in a pocket beats a TV
#: nobody is looking at, and a computer that is already awake beats both.
_PREFERENCE = ("tv", "speaker", "smartphone", "computer")


async def get_devices(client: SpotifyClient) -> list[SpotifyDevice]:
    """Every device Spotify currently knows about for this user.

    An empty list is the normal answer when Spotify is closed everywhere, not an error.
    """
    payload = await client.get_json("/me/player/devices")
    return parse(DevicesResponse, payload or {}, "device list").devices


def pick_device(devices: list[SpotifyDevice]) -> SpotifyDevice | None:
    """Which device to play on: the active one, else the most likely to be in reach.

    Restricted devices are excluded outright — they are listed but documented as refusing
    every Web API command, so targeting one is a guaranteed failure.
    """
    usable = [device for device in devices if device.is_usable]
    if not usable:
        return None
    active = next((device for device in usable if device.is_active), None)
    if active is not None:
        return active
    return max(usable, key=_preference)


def _preference(device: SpotifyDevice) -> int:
    """Higher is better. An unfamiliar device type sorts below every known one."""
    kind = (device.type or "").lower()
    return _PREFERENCE.index(kind) if kind in _PREFERENCE else -1


async def transfer_playback(client: SpotifyClient, device_id: str, *, play: bool = False) -> None:
    """Move playback to a device. ``PUT /me/player``."""
    await client.request("PUT", "/me/player", json={"device_ids": [device_id], "play": play})


async def start_playback(
    client: SpotifyClient,
    *,
    context_uri: str | None = None,
    uris: list[str] | None = None,
    device_id: str | None = None,
    position: int | None = None,
    position_ms: int = 0,
) -> None:
    """``PUT /me/player/play``. 204 on success, and a ``reason`` on refusal.

    A playlist goes in as a ``context_uri`` rather than as ``uris`` so that Spotify's own
    next/previous walk the session in order, and so the user sees the playlist they were
    given rather than a queue with no name.
    """
    payload: dict[str, object] = {}
    if context_uri:
        payload["context_uri"] = context_uri
        if position is not None:
            payload["offset"] = {"position": position}
    elif uris:
        payload["uris"] = list(uris)
    if position_ms:
        payload["position_ms"] = position_ms

    params = {"device_id": device_id} if device_id else None
    await client.request("PUT", "/me/player/play", params=params, json=payload or None)


async def get_playback_state(client: SpotifyClient) -> PlaybackState | None:
    """``GET /me/player``, which answers 204 with no body when nothing is playing."""
    payload = await client.get_json("/me/player")
    if not payload:
        return None
    return parse(PlaybackState, payload, "playback state")


async def pause(client: SpotifyClient, *, device_id: str | None = None) -> None:
    params = {"device_id": device_id} if device_id else None
    await client.request("PUT", "/me/player/pause", params=params)


async def resume(client: SpotifyClient, *, device_id: str | None = None) -> None:
    """Resume whatever was playing. ``PUT /me/player/play`` with no body."""
    params = {"device_id": device_id} if device_id else None
    await client.request("PUT", "/me/player/play", params=params)


async def next_track(client: SpotifyClient, *, device_id: str | None = None) -> None:
    params = {"device_id": device_id} if device_id else None
    await client.request("POST", "/me/player/next", params=params)


async def previous_track(client: SpotifyClient, *, device_id: str | None = None) -> None:
    params = {"device_id": device_id} if device_id else None
    await client.request("POST", "/me/player/previous", params=params)
