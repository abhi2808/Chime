"""Signed httpOnly cookies: the app session and the short-lived OAuth handshake."""

from __future__ import annotations

from typing import Any

from fastapi import Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import settings

SESSION_SALT = "chime.session"
OAUTH_SALT = "chime.oauth"


class CookieConfigError(RuntimeError):
    """SESSION_SECRET is missing."""


def _serializer(salt: str) -> URLSafeTimedSerializer:
    secret = settings.session_secret.strip()
    if not secret:
        raise CookieConfigError(
            "SESSION_SECRET is not set. Generate one with: "
            'python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
    return URLSafeTimedSerializer(secret, salt=salt)


def dumps(salt: str, payload: dict[str, Any]) -> str:
    return _serializer(salt).dumps(payload)


def loads(salt: str, raw: str | None, max_age: int) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        value = _serializer(salt).loads(raw, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    return value if isinstance(value, dict) else None


def set_session_cookie(response: Response, payload: dict[str, Any]) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        dumps(SESSION_SALT, payload),
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def read_session(request: Request) -> dict[str, Any] | None:
    raw = request.cookies.get(settings.session_cookie_name)
    return loads(SESSION_SALT, raw, settings.session_ttl_seconds)


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/")


def set_oauth_cookie(response: Response, payload: dict[str, Any]) -> None:
    response.set_cookie(
        settings.oauth_cookie_name,
        dumps(OAUTH_SALT, payload),
        max_age=settings.oauth_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/auth",
    )


def read_oauth_cookie(request: Request) -> dict[str, Any] | None:
    raw = request.cookies.get(settings.oauth_cookie_name)
    return loads(OAUTH_SALT, raw, settings.oauth_ttl_seconds)


def clear_oauth_cookie(response: Response) -> None:
    response.delete_cookie(settings.oauth_cookie_name, path="/auth")
