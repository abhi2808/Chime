"""Typed MusicBrainz errors, so callers never branch on raw status codes."""

from __future__ import annotations

from app.integrations.http import ApiError


class MusicBrainzError(ApiError):
    """Base for every failure talking to MusicBrainz."""


class MusicBrainzRateLimitError(MusicBrainzError):
    """Throttled beyond our retry budget. MusicBrainz signals this with 503."""


class MusicBrainzServerError(MusicBrainzError):
    """5xx that outlived our retry budget."""


class MusicBrainzUnavailableError(MusicBrainzError):
    """Network or timeout failure that outlived our retry budget."""


class MusicBrainzNotFoundError(MusicBrainzError):
    """404 for a specific MBID."""
