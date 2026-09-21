"""Async WHOOP API v2 client: timeout, refresh-on-401, backoff on 429/5xx.

The retry loop lives in :mod:`app.integrations.http`; this module only supplies what is
specific to WHOOP. The rate limit is 100 requests/min and 10,000/day, which a day's
refresh comes nowhere near, so the pacer here is politeness rather than necessity.
"""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.integrations.http import ApiClient, ErrorSet
from app.integrations.whoop.errors import (
    WhoopAuthError,
    WhoopError,
    WhoopNotFoundError,
    WhoopRateLimitError,
    WhoopServerError,
    WhoopUnavailableError,
)

API_BASE = "https://api.prod.whoop.com/developer"


class WhoopClient(ApiClient):
    """One instance per user per unit of work."""

    base_url = API_BASE
    label = "WHOOP"
    errors = ErrorSet(
        generic=WhoopError,
        auth=WhoopAuthError,
        rate_limit=WhoopRateLimitError,
        server=WhoopServerError,
        unavailable=WhoopUnavailableError,
        not_found=WhoopNotFoundError,
    )

    def default_min_interval(self) -> float:
        return settings.whoop_min_request_interval_ms / 1000

    def error_message(self, response: httpx.Response, status: int) -> str:
        """WHOOP returns ``{"message": ...}``; tolerate a bare string or an empty body."""
        try:
            body = response.json()
        except ValueError:
            return f"WHOOP returned {status}"
        if isinstance(body, dict):
            message = body.get("message") or body.get("error_description") or body.get("error")
            if message:
                return str(message)
        return f"WHOOP returned {status}"
