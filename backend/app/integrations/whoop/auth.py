"""WHOOP OAuth 2.0 (authorization code with a client secret).

Verified against developer.whoop.com: authorize at
``https://api.prod.whoop.com/oauth/oauth2/auth``, exchange and refresh at
``/oauth/oauth2/token``, form-encoded, and a client secret is required — unlike Spotify,
this is not PKCE. Two WHOOP-specific rules the docs call out:

* ``state`` must be exactly eight characters.
* a refresh token is only issued when ``offline`` is among the requested scopes.
"""

from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx

from app.integrations.oauth import OAuthTokenResponse, post_token
from app.integrations.whoop.errors import WhoopAuthError

AUTHORIZE_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"

#: WHOOP rejects a state parameter of any other length.
STATE_LENGTH = 8

#: There is no stress score and no live heart rate in the API, so nothing here asks for
#: one. read:body_measurement is requested now to avoid a second consent screen later.
SCOPES: tuple[str, ...] = (
    "offline",  # required for a refresh token
    "read:profile",
    "read:recovery",  # recovery score, HRV, resting HR, SpO2, skin temp
    "read:sleep",
    "read:workout",
    "read:cycles",  # day strain
    "read:body_measurement",
)

SCOPE_STRING = " ".join(SCOPES)


def new_state() -> str:
    """Exactly eight characters, as WHOOP requires."""
    return secrets.token_hex(STATE_LENGTH // 2)


def build_authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    scopes: str = SCOPE_STRING,
) -> str:
    query = urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": scopes,
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


async def _post(data: dict[str, str], client: httpx.AsyncClient | None) -> OAuthTokenResponse:
    return await post_token(
        TOKEN_URL, data, label="WHOOP", error_cls=WhoopAuthError, client=client
    )


async def exchange_code(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
    client: httpx.AsyncClient | None = None,
) -> OAuthTokenResponse:
    return await _post(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        client,
    )


async def refresh_access_token(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    scopes: str = SCOPE_STRING,
    client: httpx.AsyncClient | None = None,
) -> OAuthTokenResponse:
    """Refresh, resending ``scope`` as WHOOP's documented payload requires.

    We resend the full granted set rather than the bare ``offline`` shown in WHOOP's
    example, because RFC 6749 treats a refresh ``scope`` as the scopes being requested
    for the new token and we want to keep all of them. If a live refresh ever 400s here,
    try ``scopes="offline"`` before assuming the grant is broken.
    """
    return await _post(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": scopes,
        },
        client,
    )
