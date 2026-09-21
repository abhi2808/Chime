"""WHOOP API v2 integration: OAuth, client, typed reads.

Base URL ``https://api.prod.whoop.com/developer``. The API offers no stress score and no
live heart rate, so Chime treats WHOOP as daily context rather than a live signal.
"""

from app.integrations.whoop.client import WhoopClient
from app.integrations.whoop.errors import (
    WhoopAuthError,
    WhoopError,
    WhoopNotFoundError,
    WhoopRateLimitError,
    WhoopServerError,
    WhoopUnavailableError,
)

__all__ = [
    "WhoopAuthError",
    "WhoopClient",
    "WhoopError",
    "WhoopNotFoundError",
    "WhoopRateLimitError",
    "WhoopServerError",
    "WhoopUnavailableError",
]
