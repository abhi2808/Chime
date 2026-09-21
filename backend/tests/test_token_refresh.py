"""Token refresh, and the client behaviour that depends on it."""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qs

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import as_utc, utcnow
from app.core.crypto import decrypt, encrypt
from app.db.session import SessionLocal
from app.integrations.spotify import auth as spotify_auth
from app.integrations.spotify.client import SpotifyClient
from app.integrations.spotify.errors import (
    SpotifyAuthError,
    SpotifyRateLimitError,
    SpotifyServerError,
)
from app.models import OAuthToken, User
from app.services.token_store import TokenStore


@pytest.fixture
def stored_token(db: Session, user: User) -> OAuthToken:
    record = OAuthToken(
        user_id=user.id,
        provider="spotify",
        access_token_enc=encrypt("stale-access"),
        refresh_token_enc=encrypt("long-lived-refresh"),
        expires_at=utcnow() - timedelta(minutes=5),
        scopes=spotify_auth.SCOPE_STRING,
    )
    db.add(record)
    db.commit()
    return record


class FakeTokens:
    """Access-token provider that counts refreshes instead of doing them."""

    def __init__(self) -> None:
        self.refreshes = 0
        self.token = "token-1"

    async def get_access_token(self, *, force_refresh: bool = False) -> str:
        if force_refresh:
            self.refreshes += 1
            self.token = f"token-{self.refreshes + 1}"
        return self.token


@respx.mock
async def test_expired_token_is_refreshed_and_persisted(
    db: Session, user: User, stored_token: OAuthToken
) -> None:
    route = respx.post(spotify_auth.TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "fresh-access", "expires_in": 3600})
    )

    token = await TokenStore(SessionLocal, user.id).get_access_token()

    assert token == "fresh-access"
    body = parse_qs(route.calls[0].request.content.decode())
    assert body["grant_type"] == ["refresh_token"]
    assert body["refresh_token"] == ["long-lived-refresh"]
    assert body["client_id"] == ["test-client-id"]  # PKCE refresh needs the id, not a secret
    assert "client_secret" not in body

    db.expire_all()
    record = db.scalar(select(OAuthToken).where(OAuthToken.user_id == user.id))
    assert record is not None
    assert decrypt(record.access_token_enc) == "fresh-access"
    # Spotify may omit a new refresh token; the old one must survive.
    assert decrypt(record.refresh_token_enc or "") == "long-lived-refresh"
    expires_at = as_utc(record.expires_at)
    assert expires_at is not None and expires_at > utcnow()


@respx.mock
async def test_rotated_refresh_token_replaces_the_old_one(
    db: Session, user: User, stored_token: OAuthToken
) -> None:
    respx.post(spotify_auth.TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "fresh-access",
                "expires_in": 3600,
                "refresh_token": "rotated-refresh",
            },
        )
    )

    await TokenStore(SessionLocal, user.id).get_access_token()

    db.expire_all()
    record = db.scalar(select(OAuthToken).where(OAuthToken.user_id == user.id))
    assert record is not None
    assert decrypt(record.refresh_token_enc or "") == "rotated-refresh"


@respx.mock
async def test_a_valid_token_is_reused_without_calling_spotify(
    db: Session, user: User, stored_token: OAuthToken
) -> None:
    stored_token.expires_at = utcnow() + timedelta(minutes=30)
    db.add(stored_token)
    db.commit()
    route = respx.post(spotify_auth.TOKEN_URL)

    store = TokenStore(SessionLocal, user.id)
    assert await store.get_access_token() == "stale-access"
    assert await store.get_access_token() == "stale-access"

    assert route.call_count == 0


@respx.mock
async def test_a_revoked_refresh_token_surfaces_as_an_auth_error(
    user: User, stored_token: OAuthToken
) -> None:
    respx.post(spotify_auth.TOKEN_URL).mock(
        return_value=httpx.Response(
            400, json={"error": "invalid_grant", "error_description": "Refresh token revoked"}
        )
    )

    with pytest.raises(SpotifyAuthError, match="Refresh token revoked"):
        await TokenStore(SessionLocal, user.id).get_access_token()


async def test_missing_tokens_ask_the_user_to_sign_in(user: User) -> None:
    with pytest.raises(SpotifyAuthError, match="not connected"):
        await TokenStore(SessionLocal, user.id).get_access_token()


@respx.mock
async def test_client_refreshes_once_on_401_then_retries() -> None:
    tokens = FakeTokens()
    route = respx.get("https://api.spotify.com/v1/me").mock(
        side_effect=[
            httpx.Response(401, json={"error": {"status": 401, "message": "expired"}}),
            httpx.Response(200, json={"id": "abhinav"}),
        ]
    )

    async with SpotifyClient(tokens) as client:
        assert await client.get_json("/me") == {"id": "abhinav"}

    assert tokens.refreshes == 1
    assert route.call_count == 2
    assert route.calls[1].request.headers["Authorization"] == "Bearer token-2"


@respx.mock
async def test_a_second_401_is_not_retried_forever() -> None:
    tokens = FakeTokens()
    respx.get("https://api.spotify.com/v1/me").mock(return_value=httpx.Response(401))

    async with SpotifyClient(tokens) as client:
        with pytest.raises(SpotifyAuthError, match="Sign in again"):
            await client.get_json("/me")

    assert tokens.refreshes == 1


@respx.mock
async def test_429_honours_retry_after() -> None:
    slept: list[float] = []

    async def record_sleep(seconds: float) -> None:
        slept.append(seconds)

    respx.get("https://api.spotify.com/v1/me/tracks").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "3"}),
            httpx.Response(200, json={"items": []}),
        ]
    )

    async with SpotifyClient(FakeTokens(), sleep=record_sleep) as client:
        assert await client.get_json("/me/tracks") == {"items": []}

    assert slept == [3.0]


@respx.mock
async def test_relentless_rate_limiting_raises() -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    respx.get("https://api.spotify.com/v1/me/tracks").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "1"})
    )

    async with SpotifyClient(FakeTokens(), max_retries=2, sleep=no_sleep) as client:
        with pytest.raises(SpotifyRateLimitError) as caught:
            await client.get_json("/me/tracks")

    assert caught.value.retry_after == 1.0


@respx.mock
async def test_5xx_is_retried_with_backoff_then_raises() -> None:
    slept: list[float] = []

    async def record_sleep(seconds: float) -> None:
        slept.append(seconds)

    route = respx.get("https://api.spotify.com/v1/artists/abc").mock(
        return_value=httpx.Response(502)
    )

    async with SpotifyClient(FakeTokens(), max_retries=2, sleep=record_sleep) as client:
        with pytest.raises(SpotifyServerError):
            await client.get_json("/artists/abc")

    assert route.call_count == 3  # first attempt plus two retries
    assert len(slept) == 2
    assert slept[0] < slept[1]  # backoff grows


@respx.mock
async def test_a_long_retry_after_is_handed_back_instead_of_slept_through() -> None:
    """A ten minute penalty must not hold the request open: the caller decides."""
    slept: list[float] = []

    async def record_sleep(seconds: float) -> None:
        slept.append(seconds)

    route = respx.get("https://api.spotify.com/v1/artists/abc").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "600"})
    )

    async with SpotifyClient(FakeTokens(), sleep=record_sleep) as client:
        with pytest.raises(SpotifyRateLimitError) as caught:
            await client.get_json("/artists/abc")

    assert caught.value.retry_after == 600.0
    assert slept == []  # no waiting
    assert route.call_count == 1  # and no further hammering


@respx.mock
async def test_requests_are_spaced_by_the_pacer() -> None:
    slept: list[float] = []

    async def record_sleep(seconds: float) -> None:
        slept.append(seconds)

    respx.get("https://api.spotify.com/v1/artists/abc").mock(
        return_value=httpx.Response(200, json={"id": "abc"})
    )

    async with SpotifyClient(FakeTokens(), min_request_interval=0.2, sleep=record_sleep) as client:
        await client.get_json("/artists/abc")
        await client.get_json("/artists/abc")
        await client.get_json("/artists/abc")

    # The first call goes straight out; each later one waits for its slot. A fake sleep
    # never advances the clock, so those slots keep receding here.
    assert len(slept) == 2
    assert slept[0] == pytest.approx(0.2, abs=0.05)
    assert slept[1] > slept[0]


@respx.mock
async def test_a_transport_error_is_retried_then_reported() -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    respx.get("https://api.spotify.com/v1/me").mock(side_effect=httpx.ConnectError("boom"))

    async with SpotifyClient(FakeTokens(), max_retries=1, sleep=no_sleep) as client:
        with pytest.raises(Exception, match="Could not reach Spotify"):
            await client.get_json("/me")
