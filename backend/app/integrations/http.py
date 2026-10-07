"""Shared plumbing for outbound API calls: pacing, retries, typed errors.

Both Spotify and WHOOP need the same behaviour — a timeout on every call, one token
refresh on 401, ``Retry-After`` honoured on 429 up to a ceiling, backoff on 5xx, and a
typed exception rather than a raw status. That lives here once so the two integrations
cannot drift apart, while each keeps its own error classes and its own wording.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_BACKOFF_SECONDS = 8.0

#: A ``Retry-After`` beyond this is treated as nonsense and capped.
MAX_RETRY_AFTER_SECONDS = 3600.0


class ApiError(Exception):
    """Base for every failure talking to an external API."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class ErrorSet:
    """The exception classes one provider raises, so the shared loop stays generic."""

    generic: type[ApiError]
    auth: type[ApiError]
    rate_limit: type[ApiError]
    server: type[ApiError]
    unavailable: type[ApiError]
    not_found: type[ApiError]


class AccessTokenProvider(Protocol):
    async def get_access_token(self, *, force_refresh: bool = False) -> str: ...


class Pacer:
    """Keeps a minimum gap between outbound calls, shared by everything on one client.

    Rate limits are measured over a rolling window, so what trips them is a burst, not a
    total. Concurrent callers each take a slot in the queue, sleep outside the lock, and
    so stay spaced without serialising on each other's sleeps.
    """

    def __init__(self, min_interval: float, sleep: Callable[[float], Awaitable[None]]) -> None:
        self._min_interval = max(0.0, min_interval)
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._next_at: float | None = None

    async def wait(self) -> None:
        if self._min_interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            if self._next_at is None:
                self._next_at = now + self._min_interval
                return
            delay = self._next_at - now
            self._next_at = max(now, self._next_at) + self._min_interval
        if delay > 0:
            await self._sleep(delay)


class ApiClient:
    """One instance per user per unit of work. Safe to share across concurrent tasks.

    Subclasses set :attr:`base_url`, :attr:`label` and :attr:`errors`, and may override
    :meth:`default_min_interval`, :meth:`default_headers` and :meth:`error_message`.

    ``token_provider`` is optional: an open API (MusicBrainz) needs no Authorization
    header but still wants every other guarantee in here — pacing, retries, timeouts.
    """

    base_url: ClassVar[str]
    #: How the provider is named in user-facing error messages.
    label: ClassVar[str]
    errors: ClassVar[ErrorSet]

    def __init__(
        self,
        token_provider: AccessTokenProvider | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        max_retries: int | None = None,
        min_request_interval: float | None = None,
        rate_limit_sleep_ceiling: float | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._tokens = token_provider
        self._client = client or httpx.AsyncClient(timeout=settings.http_timeout_seconds)
        self._owns_client = client is None
        self._max_retries = settings.http_max_retries if max_retries is None else max_retries
        self._sleep = sleep
        self._sleep_ceiling = (
            settings.rate_limit_sleep_ceiling_seconds
            if rate_limit_sleep_ceiling is None
            else rate_limit_sleep_ceiling
        )
        self._pacer = Pacer(
            self.default_min_interval() if min_request_interval is None else min_request_interval,
            sleep,
        )

    def default_min_interval(self) -> float:
        """Seconds between calls when the caller does not say. Override per provider."""
        return 0.0

    def default_headers(self) -> dict[str, str]:
        """Headers sent on every request, before Authorization. Override per provider."""
        return {}

    async def __aenter__(self) -> ApiClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        response = await self.request("GET", path, params=params)
        if not response.content:
            return None
        return response.json()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
    ) -> httpx.Response:
        errors = self.errors
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        attempt = 0
        refreshed = False

        while True:
            await self._pacer.wait()
            headers = self.default_headers()
            if self._tokens is not None:
                headers["Authorization"] = f"Bearer {await self._tokens.get_access_token()}"
            try:
                response = await self._client.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                if attempt >= self._max_retries:
                    raise errors.unavailable(
                        f"Could not reach {self.label} after {attempt + 1} attempts: {exc}"
                    ) from exc
                attempt += 1
                await self._sleep(backoff(attempt))
                continue

            status = response.status_code

            if status == 401 and self._tokens is not None and not refreshed:
                # Expired or revoked access token: refresh once, then retry.
                refreshed = True
                await self._tokens.get_access_token(force_refresh=True)
                continue

            if status == 429:
                retry_after = self.retry_after(response)
                # Waiting out a long penalty inside a request would freeze the caller for
                # minutes. Hand the wait back instead, so the caller can stop cleanly and
                # resume later.
                if retry_after > self._sleep_ceiling or attempt >= self._max_retries:
                    raise errors.rate_limit(
                        f"{self.label} is rate limiting this app. "
                        f"The earliest it will answer again is in about {round(retry_after)}s.",
                        status=status,
                        retry_after=retry_after,
                    )
                attempt += 1
                logger.warning(
                    "rate limited, backing off",
                    extra={
                        "provider": self.label,
                        "path": path,
                        "retry_after": retry_after,
                        "attempt": attempt,
                    },
                )
                await self._sleep(retry_after)
                continue

            if status >= 500:
                if attempt >= self._max_retries:
                    raise errors.server(
                        f"{self.label} returned {status} after {attempt + 1} attempts",
                        status=status,
                    )
                attempt += 1
                await self._sleep(backoff(attempt))
                continue

            if status == 401:
                raise errors.auth(
                    f"{self.label} rejected the access token. Sign in again.", status=status
                )
            if status == 404:
                raise self.failure(errors.not_found, f"{self.label} has no {path}", response)
            if status >= 400:
                raise self.failure(
                    errors.generic, self.error_message(response, status), response
                )

            return response

    def retry_after(self, response: httpx.Response) -> float:
        """Honour ``Retry-After`` as sent, in whole seconds.

        Reported as sent (capped at an hour) rather than clamped down to something
        comfortable: a penalty shortened by us just earns another 429.
        """
        raw = response.headers.get("Retry-After")
        if raw:
            try:
                return max(0.0, min(float(raw), MAX_RETRY_AFTER_SECONDS))
            except ValueError:
                pass
        return 2.0

    def error_message(self, response: httpx.Response, status: int) -> str:
        """Pull a human message out of an error body. Override for provider shapes."""
        return f"{self.label} returned {status}"

    def error_code(self, response: httpx.Response) -> str | None:
        """A machine-readable reason from the body, if the provider sends one."""
        return None

    def failure(
        self, default: type[ApiError], message: str, response: httpx.Response
    ) -> ApiError:
        """Build the exception for a response we are giving up on.

        A hook rather than a bare ``raise`` because some failures are worth their own
        type: "this account is not Premium" and "nothing is playing anywhere" both arrive
        as ordinary 403s, and every caller would otherwise re-parse the body to tell them
        apart. Providers override this; the retry loop above stays generic.
        """
        return default(message, status=response.status_code, code=self.error_code(response))


def backoff(attempt: int) -> float:
    return min(MAX_BACKOFF_SECONDS, 0.5 * (2 ** (attempt - 1))) + random.uniform(0, 0.25)
