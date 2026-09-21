from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from app.integrations.spotify import auth as spotify_auth
from app.integrations.spotify.pkce import (
    MAX_VERIFIER_LENGTH,
    MIN_VERIFIER_LENGTH,
    VERIFIER_ALPHABET,
    code_challenge,
    generate_code_verifier,
    generate_state,
)

# RFC 7636 appendix B, the vector Spotify's S256 requirement follows.
RFC_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
RFC_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_challenge_matches_the_rfc_vector() -> None:
    assert code_challenge(RFC_VERIFIER) == RFC_CHALLENGE


def test_challenge_is_unpadded_base64url() -> None:
    challenge = code_challenge(generate_code_verifier())

    assert "=" not in challenge
    assert "+" not in challenge
    assert "/" not in challenge


def test_verifier_uses_only_allowed_characters() -> None:
    verifier = generate_code_verifier()

    assert MIN_VERIFIER_LENGTH <= len(verifier) <= MAX_VERIFIER_LENGTH
    assert set(verifier) <= set(VERIFIER_ALPHABET)


def test_verifiers_and_states_are_unique() -> None:
    assert len({generate_code_verifier() for _ in range(50)}) == 50
    assert len({generate_state() for _ in range(50)}) == 50


@pytest.mark.parametrize("length", [42, 129])
def test_verifier_length_is_bounded(length: int) -> None:
    with pytest.raises(ValueError, match="43-128"):
        generate_code_verifier(length)


def test_authorize_url_carries_everything_spotify_requires() -> None:
    url = spotify_auth.build_authorize_url(
        client_id="client-123",
        redirect_uri="http://127.0.0.1:5173/auth/spotify/callback",
        state="state-abc",
        code_challenge=RFC_CHALLENGE,
    )

    parsed = urlparse(url)
    query = {key: value[0] for key, value in parse_qs(parsed.query).items()}

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == spotify_auth.AUTHORIZE_URL
    assert query["response_type"] == "code"
    assert query["code_challenge_method"] == "S256"
    assert query["code_challenge"] == RFC_CHALLENGE
    assert query["state"] == "state-abc"
    assert query["redirect_uri"] == "http://127.0.0.1:5173/auth/spotify/callback"
    assert "localhost" not in query["redirect_uri"]  # Spotify rejects it
    assert "user-library-read" in query["scope"].split()


def test_we_never_ask_for_the_deprecated_profile_scopes() -> None:
    # product / country / email are deprecated and we do not detect Premium.
    assert "user-read-private" not in spotify_auth.SCOPES
    assert "user-read-email" not in spotify_auth.SCOPES
