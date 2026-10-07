"""Test environment.

Every setting the app reads is pinned here *before* ``app`` is imported, so a real
.env on the machine can never leak into a test run and no test can touch the real
database. respx blocks outbound HTTP, so nothing reaches Spotify or WHOOP either.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

_TEST_DB = Path(tempfile.mkdtemp(prefix="chime-tests-")) / "test.db"

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB.as_posix()}"
os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["SESSION_SECRET"] = "test-session-secret-not-a-real-one"
os.environ["SPOTIFY_CLIENT_ID"] = "test-client-id"
os.environ["SPOTIFY_REDIRECT_URI"] = "http://127.0.0.1:5173/auth/spotify/callback"
# WHOOP uses a client secret rather than PKCE, so both halves have to be present for the
# connect routes to get as far as the token exchange.
os.environ["WHOOP_CLIENT_ID"] = "test-whoop-client-id"
os.environ["WHOOP_CLIENT_SECRET"] = "test-whoop-secret"
os.environ["WHOOP_REDIRECT_URI"] = "http://127.0.0.1:5173/auth/whoop/callback"
os.environ["FRONTEND_ORIGIN"] = "http://127.0.0.1:5173"
os.environ["ALLOWED_SPOTIFY_USER_IDS"] = ""
os.environ["LOG_LEVEL"] = "WARNING"
# Request pacing off by default, so tests that assert on sleeps see only retry backoff.
# The pacer gets its own tests, which set an interval explicitly.
os.environ["SPOTIFY_MIN_REQUEST_INTERVAL_MS"] = "0"
os.environ["WHOOP_MIN_REQUEST_INTERVAL_MS"] = "0"
# MusicBrainz asks for one request per second. Honoured in production, not in tests:
# a paced test suite would spend minutes asleep.
os.environ["MUSICBRAINZ_MIN_REQUEST_INTERVAL_MS"] = "0"
os.environ["MUSICBRAINZ_USER_AGENT"] = "ChimeTests/0.1 ( tests@example.invalid )"
# The `client` fixture runs the app's lifespan, which starts the live loop. A background job
# polling Spotify mid-test would fight respx and make failures depend on timing, so the loop
# is off and its ticks are called directly in test_scheduler.py instead.
os.environ["ENABLE_SCHEDULER"] = "false"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_database() -> Iterator[None]:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def user(db: Session) -> User:
    record = User(
        spotify_account_id="acc_owner",
        spotify_user_id="owner",
        display_name="Owner",
    )
    db.add(record)
    db.commit()
    return record
