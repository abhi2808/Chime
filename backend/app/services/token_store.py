"""Encrypted token storage plus refresh-on-demand.

Opens a short database session per operation rather than holding one, so it is safe to
share a single store across the concurrent tasks of a library sync.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import as_utc, utcnow
from app.core.config import settings
from app.core.crypto import decrypt, encrypt
from app.integrations.http import ApiError
from app.integrations.oauth import OAuthTokenResponse
from app.integrations.spotify import auth as spotify_auth
from app.integrations.spotify.errors import SpotifyAuthError
from app.integrations.whoop import auth as whoop_auth
from app.integrations.whoop.errors import WhoopAuthError
from app.models import OAuthToken

logger = logging.getLogger(__name__)

#: Refresh a little early so a long request cannot start on an about-to-expire token.
REFRESH_MARGIN = timedelta(seconds=60)

SessionFactory = sessionmaker[Session] | Callable[[], Session]


async def _refresh_spotify(refresh_token: str) -> OAuthTokenResponse:
    return await spotify_auth.refresh_access_token(
        client_id=settings.spotify_client_id,
        refresh_token=refresh_token,
    )


async def _refresh_whoop(refresh_token: str) -> OAuthTokenResponse:
    return await whoop_auth.refresh_access_token(
        client_id=settings.whoop_client_id,
        client_secret=settings.whoop_client_secret,
        refresh_token=refresh_token,
    )


@dataclass(frozen=True, slots=True)
class _Provider:
    """What differs between providers when a token needs renewing."""

    label: str
    refresh: Callable[[str], Awaitable[OAuthTokenResponse]]
    auth_error: type[ApiError]


PROVIDERS: dict[str, _Provider] = {
    "spotify": _Provider("Spotify", _refresh_spotify, SpotifyAuthError),
    "whoop": _Provider("WHOOP", _refresh_whoop, WhoopAuthError),
}


def save_tokens(
    db: Session,
    *,
    user_id: int,
    provider: str,
    tokens: OAuthTokenResponse,
    fallback_refresh_token: str | None = None,
) -> OAuthToken:
    """Upsert encrypted tokens. Keeps the previous refresh token when none is returned."""
    record = db.scalar(
        select(OAuthToken).where(OAuthToken.user_id == user_id, OAuthToken.provider == provider)
    )
    refresh_token = tokens.refresh_token or fallback_refresh_token
    expires_at = utcnow() + timedelta(seconds=tokens.expires_in)

    if record is None:
        record = OAuthToken(user_id=user_id, provider=provider)
        db.add(record)

    record.access_token_enc = encrypt(tokens.access_token)
    if refresh_token:
        record.refresh_token_enc = encrypt(refresh_token)
    record.expires_at = expires_at
    if tokens.scope:
        record.scopes = tokens.scope
    record.updated_at = utcnow()
    return record


class TokenStore:
    """Access-token provider for any :class:`~app.integrations.http.ApiClient`."""

    def __init__(
        self,
        session_factory: SessionFactory,
        user_id: int,
        provider: str = "spotify",
    ) -> None:
        if provider not in PROVIDERS:
            raise ValueError(f"No refresh strategy for provider {provider!r}")
        self._session_factory = session_factory
        self._user_id = user_id
        self._provider = provider
        self._config = PROVIDERS[provider]
        self._lock = asyncio.Lock()

    async def get_access_token(self, *, force_refresh: bool = False) -> str:
        if not force_refresh:
            token = self._read_valid_access_token()
            if token is not None:
                return token

        # One refresh at a time; a concurrent caller may already have done the work.
        async with self._lock:
            if not force_refresh:
                token = self._read_valid_access_token()
                if token is not None:
                    return token
            return await self._refresh()

    def _read_valid_access_token(self) -> str | None:
        with self._session_factory() as db:
            record = self._require_record(db)
            expires_at = as_utc(record.expires_at)
            if expires_at is None or expires_at - REFRESH_MARGIN > utcnow():
                return decrypt(record.access_token_enc)
        return None

    async def _refresh(self) -> str:
        with self._session_factory() as db:
            record = self._require_record(db)
            if not record.refresh_token_enc:
                raise self._config.auth_error(
                    f"No {self._config.label} refresh token stored. Sign in again."
                )
            refresh_token = decrypt(record.refresh_token_enc)

        tokens = await self._config.refresh(refresh_token)

        with self._session_factory() as db:
            save_tokens(
                db,
                user_id=self._user_id,
                provider=self._provider,
                tokens=tokens,
                fallback_refresh_token=refresh_token,
            )
            db.commit()

        logger.info(
            "refreshed provider access token",
            extra={"provider": self._provider, "user_id": self._user_id},
        )
        return tokens.access_token

    def _require_record(self, db: Session) -> OAuthToken:
        record = db.scalar(
            select(OAuthToken).where(
                OAuthToken.user_id == self._user_id, OAuthToken.provider == self._provider
            )
        )
        if record is None:
            raise self._config.auth_error(
                f"{self._config.label} is not connected for this account. Sign in again."
            )
        return record
