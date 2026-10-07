"""Typed Spotify errors, so callers never branch on raw status codes."""

from __future__ import annotations

from app.integrations.http import ApiError


class SpotifyError(ApiError):
    """Base for every failure talking to Spotify."""


class SpotifyAuthError(SpotifyError):
    """Token exchange or refresh failed, or a call stayed 401 after a refresh."""


class SpotifyRateLimitError(SpotifyError):
    """429 that outlived our retry budget."""


class SpotifyServerError(SpotifyError):
    """5xx that outlived our retry budget."""


class SpotifyUnavailableError(SpotifyError):
    """Network or timeout failure that outlived our retry budget."""


class SpotifyNotFoundError(SpotifyError):
    """404 for a specific resource."""


class SpotifyPlayerError(SpotifyError):
    """A player command Spotify refused, with its ``reason`` in ``code``.

    The player endpoints are the only ones that fail for reasons the *user* can fix, so
    they are the only ones whose refusals get their own types.
    """


class SpotifyPremiumRequiredError(SpotifyPlayerError):
    """Playback control needs Premium, and ``GET /me`` no longer tells us who has it.

    So this is not something to check before acting: the only way to find out is to try
    (CLAUDE.md rule 5).
    """


class SpotifyNoActiveDeviceError(SpotifyPlayerError):
    """No Spotify app is open anywhere to play on.

    Nothing the API can do about it — Chime cannot open Spotify for you, so this has to
    reach the user as an instruction rather than an error.
    """


class SpotifyRestrictedDeviceError(SpotifyPlayerError):
    """A device that exists but will not take remote commands (``is_restricted``)."""


#: Spotify's ``reason`` values that deserve their own exception type.
PLAYER_REASONS: dict[str, type[SpotifyPlayerError]] = {
    "PREMIUM_REQUIRED": SpotifyPremiumRequiredError,
    "NO_ACTIVE_DEVICE": SpotifyNoActiveDeviceError,
    "DEVICE_NOT_CONTROLLABLE": SpotifyRestrictedDeviceError,
    "REMOTE_CONTROL_DISALLOWED": SpotifyRestrictedDeviceError,
}
