"""Async MusicBrainz client.

MusicBrainz is open data (CC0 for the core data, including tags and genres) and needs no
key, but it does ask for one request per second and a User-Agent that identifies the
application, so both live here. The retry loop is the shared one in
:mod:`app.integrations.http`; MusicBrainz signals throttling with 503 rather than 429,
which that loop already retries with backoff.

Verified live on 2026-09-21 against ``https://musicbrainz.org/ws/2``:

* ``GET /recording?query=...&fmt=json`` returns hits carrying ``score`` **and inline
  ``tags``**, so one request tags one track — no second lookup per recording.
* ``GET /recording/{mbid}?inc=tags+genres`` and ``GET /artist/{mbid}?inc=tags+genres``
  both return ``[{"name": .., "count": ..}]``; ``genres`` is the curated subset of
  ``tags`` and is only present on lookups, never on search hits.
* Responses carry ``X-RateLimit-Limit`` / ``-Remaining`` / ``-Reset`` for the caller's IP.
"""

from __future__ import annotations

from app.core.config import settings
from app.integrations.http import ApiClient, ErrorSet
from app.integrations.musicbrainz.errors import (
    MusicBrainzError,
    MusicBrainzNotFoundError,
    MusicBrainzRateLimitError,
    MusicBrainzServerError,
    MusicBrainzUnavailableError,
)

API_BASE = "https://musicbrainz.org/ws/2"


class MusicBrainzClient(ApiClient):
    """Unauthenticated: constructed with no token provider."""

    base_url = API_BASE
    label = "MusicBrainz"
    errors = ErrorSet(
        # There is no auth, so a 401 would be a MusicBrainz bug rather than our problem.
        generic=MusicBrainzError,
        auth=MusicBrainzError,
        rate_limit=MusicBrainzRateLimitError,
        server=MusicBrainzServerError,
        unavailable=MusicBrainzUnavailableError,
        not_found=MusicBrainzNotFoundError,
    )

    def default_min_interval(self) -> float:
        return settings.musicbrainz_min_request_interval_ms / 1000

    def default_headers(self) -> dict[str, str]:
        return {"User-Agent": settings.musicbrainz_agent, "Accept": "application/json"}
