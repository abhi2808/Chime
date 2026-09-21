"""Spotify login (PKCE), WHOOP connect (client secret), logout.

The browser hits these paths on the Vite origin (http://127.0.0.1:5173/auth/...), which
proxies to this app, so every cookie stays same-origin through the OAuth round trip.

Spotify login *creates* the session; WHOOP connect happens inside an existing one, so
the WHOOP routes require a signed-in user and attach a second provider to that account.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.cookies import (
    clear_oauth_cookie,
    clear_session_cookie,
    read_oauth_cookie,
    set_oauth_cookie,
    set_session_cookie,
)
from app.integrations.spotify import auth as spotify_auth
from app.integrations.spotify import library as spotify_library
from app.integrations.spotify.client import SpotifyClient
from app.integrations.spotify.errors import SpotifyError
from app.integrations.spotify.pkce import code_challenge, generate_code_verifier, generate_state
from app.integrations.whoop import api as whoop_api
from app.integrations.whoop import auth as whoop_auth
from app.integrations.whoop.client import WhoopClient
from app.integrations.whoop.errors import WhoopError
from app.services import library_sync, whoop_sync
from app.services.auth_service import ProfileUnusable, UserNotAllowed, upsert_user
from app.services.token_store import save_tokens

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class _StaticToken:
    """Access-token provider for the one call we make before tokens are stored."""

    def __init__(self, access_token: str) -> None:
        self._access_token = access_token

    async def get_access_token(self, *, force_refresh: bool = False) -> str:
        return self._access_token


@router.get("/spotify/login")
def spotify_login() -> RedirectResponse:
    if not settings.spotify_client_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SPOTIFY_CLIENT_ID is not set. Add it to .env and restart the backend.",
        )

    verifier = generate_code_verifier()
    state = generate_state()
    url = spotify_auth.build_authorize_url(
        client_id=settings.spotify_client_id,
        redirect_uri=settings.spotify_redirect_uri,
        state=state,
        code_challenge=code_challenge(verifier),
    )
    response = RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    set_oauth_cookie(response, {"state": state, "verifier": verifier})
    return response


@router.get("/spotify/callback")
async def spotify_callback(
    request: Request,
    db: DbSession,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error:
        logger.warning("spotify denied the authorization request", extra={"reason": error})
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Spotify did not grant access ({error}). Try signing in again.",
        )

    handshake = read_oauth_cookie(request)
    if not handshake or not state or handshake.get("state") != state:
        # Expired handshake, wrong browser, or a forged callback.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This login link is stale. Start again from the login screen.",
        )
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Spotify did not return an authorization code. Start again from the login screen.",
        )

    try:
        tokens = await spotify_auth.exchange_code(
            client_id=settings.spotify_client_id,
            redirect_uri=settings.spotify_redirect_uri,
            code=code,
            code_verifier=handshake["verifier"],
        )
        async with SpotifyClient(_StaticToken(tokens.access_token)) as client:
            profile = await spotify_library.get_current_profile(client)
    except SpotifyError as exc:
        logger.warning("spotify login failed", extra={"reason": exc.message, "status": exc.status})
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc

    try:
        user = upsert_user(db, profile)
    except UserNotAllowed as exc:
        logger.warning("refused a spotify login", extra={"spotify_id": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This Chime install is private. Ask the owner to add your Spotify account.",
        ) from exc
    except ProfileUnusable as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Spotify returned a profile without an id, so we cannot identify the account.",
        ) from exc

    save_tokens(db, user_id=user.id, provider="spotify", tokens=tokens)
    db.commit()
    logger.info("spotify login succeeded", extra={"user_id": user.id})

    # First thing after login: get the library in, so Home has something to show.
    library_sync.start_sync(user.id)

    response = RedirectResponse(
        settings.frontend_origin.rstrip("/") + "/", status_code=status.HTTP_303_SEE_OTHER
    )
    set_session_cookie(response, {"uid": user.id})
    clear_oauth_cookie(response)
    return response


@router.get("/whoop/login")
def whoop_login(user: CurrentUser) -> RedirectResponse:
    """Start the WHOOP consent flow for the signed-in account."""
    if not settings.whoop_client_id or not settings.whoop_client_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "WHOOP_CLIENT_ID and WHOOP_CLIENT_SECRET are not set. "
                "Add them to .env and restart the backend."
            ),
        )

    # WHOOP requires a state of exactly eight characters, unlike Spotify.
    state = whoop_auth.new_state()
    url = whoop_auth.build_authorize_url(
        client_id=settings.whoop_client_id,
        redirect_uri=settings.whoop_redirect_uri,
        state=state,
    )
    response = RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    set_oauth_cookie(response, {"state": state, "provider": "whoop", "uid": user.id})
    return response


@router.get("/whoop/callback")
async def whoop_callback(
    request: Request,
    db: DbSession,
    user: CurrentUser,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error:
        logger.warning("whoop denied the authorization request", extra={"reason": error})
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"WHOOP did not grant access ({error}). Try connecting again.",
        )

    handshake = read_oauth_cookie(request)
    if (
        not handshake
        or not state
        or handshake.get("provider") != "whoop"
        or handshake.get("state") != state
        # The session must still belong to whoever started the handshake.
        or handshake.get("uid") != user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This WHOOP link is stale. Start again from settings.",
        )
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="WHOOP did not return an authorization code. Start again from settings.",
        )

    try:
        tokens = await whoop_auth.exchange_code(
            client_id=settings.whoop_client_id,
            client_secret=settings.whoop_client_secret,
            redirect_uri=settings.whoop_redirect_uri,
            code=code,
        )
        # One cheap read proves the token works before we store it as a connection.
        async with WhoopClient(_StaticToken(tokens.access_token)) as client:
            await whoop_api.get_profile(client)
    except WhoopError as exc:
        logger.warning("whoop connect failed", extra={"reason": exc.message, "status": exc.status})
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc

    if not tokens.refresh_token:
        # Without the offline scope every token dies in an hour and the connection is
        # useless. Better to say so now than to look connected and quietly stop working.
        logger.warning("whoop returned no refresh token", extra={"user_id": user.id})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "WHOOP did not return a refresh token, so the connection would expire "
                "within the hour. Check that the 'offline' scope is enabled on the WHOOP app."
            ),
        )

    save_tokens(db, user_id=user.id, provider="whoop", tokens=tokens)
    db.commit()
    logger.info("whoop connected", extra={"user_id": user.id})

    # Pull today's data straight away so Home has figures on the way back.
    try:
        await whoop_sync.refresh_body_data(user.id, force=True)
    except WhoopError as exc:
        # Connected is connected; the first read can be retried by the body-state endpoint.
        logger.warning(
            "first whoop refresh failed", extra={"user_id": user.id, "reason": exc.message}
        )

    response = RedirectResponse(
        settings.frontend_origin.rstrip("/") + "/", status_code=status.HTTP_303_SEE_OTHER
    )
    clear_oauth_cookie(response)
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout() -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response)
    return response
