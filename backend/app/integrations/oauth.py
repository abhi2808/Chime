"""The token-endpoint half of OAuth, shared by Spotify (PKCE) and WHOOP (secret).

Only the grant body differs between the two providers, so the POST, the error decoding
and the response model live here.
"""

from __future__ import annotations

import httpx
from pydantic import BaseModel, ConfigDict

from app.core.config import settings
from app.integrations.http import ApiError


class OAuthTokenResponse(BaseModel):
    """A token endpoint's success body.

    ``refresh_token`` is optional because a refresh response may omit it, in which case
    the previously stored one stays valid.
    """

    model_config = ConfigDict(extra="ignore")

    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600
    refresh_token: str | None = None
    scope: str | None = None


async def post_token(
    url: str,
    data: dict[str, str],
    *,
    label: str,
    error_cls: type[ApiError],
    client: httpx.AsyncClient | None = None,
) -> OAuthTokenResponse:
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=settings.http_timeout_seconds)
    try:
        response = await client.post(
            url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    except httpx.HTTPError as exc:
        raise error_cls(f"Could not reach {label}'s token endpoint: {exc}") from exc
    finally:
        if owns_client:
            await client.aclose()

    if response.status_code >= 400:
        detail, code = _token_error(response, label)
        raise error_cls(detail, status=response.status_code, code=code)
    return OAuthTokenResponse.model_validate(response.json())


def _token_error(response: httpx.Response, label: str) -> tuple[str, str | None]:
    """Both providers use the RFC 6749 ``error`` / ``error_description`` pair."""
    fallback = f"{label} token endpoint returned {response.status_code}"
    try:
        body = response.json()
    except ValueError:
        return fallback, None
    if not isinstance(body, dict):
        return fallback, None
    code = body.get("error")
    description = body.get("error_description")
    return (description or code or fallback, code)
