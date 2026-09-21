"""Spotify Authorization Code with PKCE.

Verified against the current docs: authorize at ``accounts.spotify.com/authorize``,
token exchange and refresh at ``accounts.spotify.com/api/token`` form-encoded, no
client secret, ``client_id`` required in both grant bodies.
"""

from __future__ import annotations

from urllib.parse import urlencode

import httpx

from app.integrations.oauth import OAuthTokenResponse, post_token
from app.integrations.spotify.errors import SpotifyAuthError

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"

#: Requested once, at first consent, so later phases do not trigger a second screen.
#: user-read-private / user-read-email are deliberately absent: the fields they unlock
#: (product, country, email) are deprecated and we do not detect Premium.
SCOPES: tuple[str, ...] = (
    "user-library-read",  # GET /me/tracks (phase 1)
    "user-library-modify",  # PUT/DELETE /me/library (phase 4)
    "user-read-recently-played",  # 'recent' source (phase 6)
    "user-top-read",  # 'top' source (phase 3)
    "playlist-read-private",  # 'playlist' source (phase 3)
    "playlist-modify-private",  # session playlists (phase 4)
    "user-read-playback-state",  # devices + playback polling (phase 4/6)
    "user-modify-playback-state",  # transfer + play (phase 4)
    "user-read-currently-playing",  # redundant with playback-state for our calls
)

SCOPE_STRING = " ".join(SCOPES)


def build_authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    scopes: str = SCOPE_STRING,
) -> str:
    query = urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": scopes,
            "code_challenge_method": "S256",
            "code_challenge": code_challenge,
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


async def _post(data: dict[str, str], client: httpx.AsyncClient | None) -> OAuthTokenResponse:
    return await post_token(
        TOKEN_URL, data, label="Spotify", error_cls=SpotifyAuthError, client=client
    )


async def exchange_code(
    *,
    client_id: str,
    redirect_uri: str,
    code: str,
    code_verifier: str,
    client: httpx.AsyncClient | None = None,
) -> OAuthTokenResponse:
    return await _post(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": code_verifier,
        },
        client,
    )


async def refresh_access_token(
    *,
    client_id: str,
    refresh_token: str,
    client: httpx.AsyncClient | None = None,
) -> OAuthTokenResponse:
    return await _post(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        },
        client,
    )
