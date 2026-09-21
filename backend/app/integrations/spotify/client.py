"""Async Spotify Web API client: timeout, refresh-on-401, backoff on 429/5xx.

The retry loop itself lives in :mod:`app.integrations.http`; this module only supplies
what is specific to Spotify.
"""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.integrations.http import ApiClient, ErrorSet
from app.integrations.spotify.errors import (
    SpotifyAuthError,
    SpotifyError,
    SpotifyNotFoundError,
    SpotifyRateLimitError,
    SpotifyServerError,
    SpotifyUnavailableError,
)

API_BASE = "https://api.spotify.com/v1"


class SpotifyClient(ApiClient):
    """One instance per user per unit of work. Safe to share across concurrent tasks."""

    base_url = API_BASE
    label = "Spotify"
    errors = ErrorSet(
        generic=SpotifyError,
        auth=SpotifyAuthError,
        rate_limit=SpotifyRateLimitError,
        server=SpotifyServerError,
        unavailable=SpotifyUnavailableError,
        not_found=SpotifyNotFoundError,
    )

    def default_min_interval(self) -> float:
        return settings.spotify_min_request_interval_ms / 1000

    def error_message(self, response: httpx.Response, status: int) -> str:
        """Spotify errors arrive as ``{"error": {"status": .., "message": ..}}``."""
        try:
            body = response.json()
        except ValueError:
            return f"Spotify returned {status}"
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict):
            return str(error.get("message") or f"Spotify returned {status}")
        return f"Spotify returned {status}"
