"""PKCE helpers (Authorization Code with PKCE, S256 only).

Spotify requires a verifier of 43-128 characters drawn from
``[A-Za-z0-9-._~]`` and ``code_challenge = base64url(sha256(verifier))`` unpadded.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import string

VERIFIER_ALPHABET = string.ascii_letters + string.digits + "-._~"
MIN_VERIFIER_LENGTH = 43
MAX_VERIFIER_LENGTH = 128


def generate_code_verifier(length: int = 96) -> str:
    if not MIN_VERIFIER_LENGTH <= length <= MAX_VERIFIER_LENGTH:
        raise ValueError(
            f"code verifier length must be {MIN_VERIFIER_LENGTH}-{MAX_VERIFIER_LENGTH}, got {length}"
        )
    return "".join(secrets.choice(VERIFIER_ALPHABET) for _ in range(length))


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def generate_state(length: int = 32) -> str:
    return secrets.token_urlsafe(length)
