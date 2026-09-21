from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.core import crypto
from app.core.config import settings


def test_round_trip_preserves_the_token() -> None:
    secret = "BQD-not-a-real-access-token"

    sealed = crypto.encrypt(secret)

    assert secret not in sealed
    assert crypto.decrypt(sealed) == secret


def test_each_encryption_is_distinct() -> None:
    first = crypto.encrypt("same")
    second = crypto.encrypt("same")

    assert first != second
    assert crypto.decrypt(first) == crypto.decrypt(second) == "same"


def test_a_rotated_key_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    sealed = crypto.encrypt("token")
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())

    with pytest.raises(crypto.EncryptionError, match="ENCRYPTION_KEY has probably changed"):
        crypto.decrypt(sealed)


def test_a_missing_key_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "encryption_key", "")

    with pytest.raises(crypto.EncryptionError, match="ENCRYPTION_KEY is not set"):
        crypto.encrypt("token")
