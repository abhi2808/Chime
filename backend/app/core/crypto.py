"""Fernet encryption for OAuth tokens at rest."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

__all__ = ["EncryptionError", "decrypt", "encrypt"]

_cache: dict[str, Fernet] = {}


class EncryptionError(RuntimeError):
    """ENCRYPTION_KEY is missing or a stored value cannot be decrypted with it."""


def _fernet() -> Fernet:
    key = settings.encryption_key.strip()
    if not key:
        raise EncryptionError(
            "ENCRYPTION_KEY is not set. Generate one with: "
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    cached = _cache.get(key)
    if cached is None:
        try:
            cached = Fernet(key.encode())
        except (ValueError, TypeError) as exc:
            raise EncryptionError("ENCRYPTION_KEY is not a valid Fernet key") from exc
        _cache[key] = cached
    return cached


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise EncryptionError(
            "Stored token could not be decrypted. ENCRYPTION_KEY has probably changed; "
            "sign in again to re-issue tokens."
        ) from exc
