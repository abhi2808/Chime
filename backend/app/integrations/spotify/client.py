"""Async Spotify Web API client: timeout, refresh-on-401, backoff on 429/5xx.

The retry loop itself lives in :mod:`app.integrations.http`; this module only supplies
what is specific to Spotify.
"""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.integrations.http import ApiClient, ApiError, ErrorSet
from app.integrations.spotify.errors import (
    PLAYER_REASONS,
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
        error = self._error_object(response)
        if error is not None:
            return str(error.get("message") or f"Spotify returned {status}")
        return f"Spotify returned {status}"

    def error_code(self, response: httpx.Response) -> str | None:
        """Player refusals add ``reason``: PREMIUM_REQUIRED, NO_ACTIVE_DEVICE, and so on."""
        error = self._error_object(response)
        reason = error.get("reason") if error else None
        return str(reason) if reason else None

    def failure(
        self, default: type[ApiError], message: str, response: httpx.Response
    ) -> ApiError:
        """Give the refusals a user can act on their own type.

        ``PUT /me/player/play`` answers "no device is open" as a 404 and "you are not
        Premium" as a 403, so without this both would surface as a generic Spotify error
        and the UI could not say the one useful thing about either.

        A refusal also keeps Spotify's own wording rather than ``message``: the 404 branch
        of the retry loop describes a missing *resource* ("Spotify has no /me/player/play"),
        which is true of an unknown artist id and nonsense for a player command.
        """
        code = self.error_code(response)
        specific = PLAYER_REASONS.get(code or "")
        if specific is not None:
            said = self.error_message(response, response.status_code)
            return specific(said, status=response.status_code, code=code)
        return default(message, status=response.status_code, code=code)

    @staticmethod
    def _error_object(response: httpx.Response) -> dict[str, object] | None:
        try:
            body = response.json()
        except ValueError:
            return None
        error = body.get("error") if isinstance(body, dict) else None
        return error if isinstance(error, dict) else None
