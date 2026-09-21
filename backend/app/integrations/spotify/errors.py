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
