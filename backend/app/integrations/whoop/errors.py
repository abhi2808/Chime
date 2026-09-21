"""Typed WHOOP errors, so callers never branch on raw status codes."""

from __future__ import annotations

from app.integrations.http import ApiError


class WhoopError(ApiError):
    """Base for every failure talking to WHOOP."""


class WhoopAuthError(WhoopError):
    """Token exchange or refresh failed, or a call stayed 401 after a refresh."""


class WhoopRateLimitError(WhoopError):
    """429 that outlived our retry budget. WHOOP allows 100/min and 10,000/day."""


class WhoopServerError(WhoopError):
    """5xx that outlived our retry budget."""


class WhoopUnavailableError(WhoopError):
    """Network or timeout failure that outlived our retry budget."""


class WhoopNotFoundError(WhoopError):
    """404 for a specific resource."""
