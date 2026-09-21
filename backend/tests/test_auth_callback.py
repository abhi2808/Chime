"""The Spotify login round trip: happy path, bad state, refused account."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import decrypt
from app.integrations.spotify import auth as spotify_auth
from app.models import OAuthToken, User

PROFILE = {"id": "abhinav", "account_id": "acc_123", "display_name": "Abhinav"}
TOKENS = {
    "access_token": "access-one",
    "token_type": "Bearer",
    "expires_in": 3600,
    "refresh_token": "refresh-one",
    "scope": spotify_auth.SCOPE_STRING,
}


@pytest.fixture(autouse=True)
def no_background_sync(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, bool]]:
    """Record the post-login sync instead of running it."""
    calls: list[tuple[int, bool]] = []

    def fake_start(user_id: int, *, full: bool = False) -> bool:
        calls.append((user_id, full))
        return True

    monkeypatch.setattr("app.api.routes.auth.library_sync.start_sync", fake_start)
    return calls


def begin_login(client: TestClient) -> str:
    response = client.get("/auth/spotify/login", follow_redirects=False)
    assert response.status_code == 307
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert client.cookies.get(settings.oauth_cookie_name)
    return query["state"][0]


def mock_spotify() -> None:
    respx.post(spotify_auth.TOKEN_URL).mock(return_value=httpx.Response(200, json=TOKENS))
    respx.get("https://api.spotify.com/v1/me").mock(
        return_value=httpx.Response(200, json=PROFILE)
    )


@respx.mock
def test_login_sets_a_single_use_handshake_cookie(client: TestClient) -> None:
    first = begin_login(client)
    second = begin_login(client)

    assert first != second  # fresh state and verifier every attempt


@respx.mock
def test_callback_creates_the_owner_and_stores_encrypted_tokens(
    client: TestClient, db: Session, no_background_sync: list[tuple[int, bool]]
) -> None:
    mock_spotify()
    state = begin_login(client)

    response = client.get(
        f"/auth/spotify/callback?code=auth-code&state={state}", follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "http://127.0.0.1:5173/"
    assert client.cookies.get(settings.session_cookie_name)

    user = db.scalar(select(User))
    assert user is not None
    assert user.spotify_account_id == "acc_123"  # the stable id, not the public one
    assert user.spotify_user_id == "abhinav"
    assert user.display_name == "Abhinav"

    token = db.scalar(select(OAuthToken).where(OAuthToken.user_id == user.id))
    assert token is not None
    assert "access-one" not in token.access_token_enc
    assert "refresh-one" not in (token.refresh_token_enc or "")
    assert decrypt(token.access_token_enc) == "access-one"
    assert decrypt(token.refresh_token_enc or "") == "refresh-one"
    assert token.expires_at is not None

    # The code exchange must be PKCE: verifier present, no client secret.
    exchange = respx.calls[0].request
    body = parse_qs(exchange.content.decode())
    assert body["grant_type"] == ["authorization_code"]
    assert body["client_id"] == ["test-client-id"]
    assert body["code_verifier"][0]
    assert "client_secret" not in body

    assert no_background_sync == [(user.id, False)]

    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["display_name"] == "Abhinav"
    assert me.json()["connections"] == {"spotify": True, "whoop": False}


@respx.mock
def test_callback_rejects_a_mismatched_state(client: TestClient, db: Session) -> None:
    mock_spotify()
    begin_login(client)

    response = client.get(
        "/auth/spotify/callback?code=auth-code&state=forged", follow_redirects=False
    )

    assert response.status_code == 400
    assert "stale" in response.json()["detail"]
    assert db.scalar(select(User)) is None
    assert not respx.calls  # never exchanged the code


@respx.mock
def test_callback_rejects_a_missing_handshake_cookie(client: TestClient) -> None:
    mock_spotify()
    state = begin_login(client)
    client.cookies.delete(settings.oauth_cookie_name)

    response = client.get(
        f"/auth/spotify/callback?code=auth-code&state={state}", follow_redirects=False
    )

    assert response.status_code == 400
    assert not respx.calls


@respx.mock
def test_callback_reports_a_denied_consent_screen(client: TestClient) -> None:
    state = begin_login(client)

    response = client.get(
        f"/auth/spotify/callback?error=access_denied&state={state}", follow_redirects=False
    )

    assert response.status_code == 400
    assert "did not grant access" in response.json()["detail"]


@respx.mock
def test_callback_refuses_an_account_outside_the_allowlist(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "allowed_spotify_user_ids", "someone_else,another_one")
    mock_spotify()
    state = begin_login(client)

    response = client.get(
        f"/auth/spotify/callback?code=auth-code&state={state}", follow_redirects=False
    )

    assert response.status_code == 403
    assert "private" in response.json()["detail"]
    assert db.scalar(select(User)) is None
    assert client.cookies.get(settings.session_cookie_name) is None


@respx.mock
def test_callback_admits_an_account_on_the_allowlist_by_public_id(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A user can read their public id off their profile URL, but not their account_id.
    monkeypatch.setattr(settings, "allowed_spotify_user_ids", "abhinav")
    mock_spotify()
    state = begin_login(client)

    response = client.get(
        f"/auth/spotify/callback?code=auth-code&state={state}", follow_redirects=False
    )

    assert response.status_code == 303
    assert db.scalar(select(User)) is not None


@respx.mock
def test_second_account_is_refused_once_an_owner_exists(
    client: TestClient, db: Session, user: User
) -> None:
    mock_spotify()  # a different account than the seeded owner
    state = begin_login(client)

    response = client.get(
        f"/auth/spotify/callback?code=auth-code&state={state}", follow_redirects=False
    )

    assert response.status_code == 403
    assert db.scalars(select(User)).all() == [user]


@respx.mock
def test_returning_owner_signs_in_again_without_creating_a_second_row(
    client: TestClient, db: Session
) -> None:
    mock_spotify()
    for _ in range(2):
        state = begin_login(client)
        response = client.get(
            f"/auth/spotify/callback?code=auth-code&state={state}", follow_redirects=False
        )
        assert response.status_code == 303

    assert len(db.scalars(select(User)).all()) == 1


def test_api_requires_a_session(client: TestClient) -> None:
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/library/status").status_code == 401


@respx.mock
def test_logout_clears_the_session(client: TestClient) -> None:
    mock_spotify()
    state = begin_login(client)
    client.get(f"/auth/spotify/callback?code=auth-code&state={state}", follow_redirects=False)
    assert client.get("/api/me").status_code == 200

    assert client.post("/auth/logout").status_code == 204

    assert client.get("/api/me").status_code == 401


def test_health_needs_no_session(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
