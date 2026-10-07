"""The live loop's three jobs (SPEC section 6).

The jobs themselves are thin — they find the live sessions and call into playback, adaptation
and WHOOP — so what is worth testing is the thing that is easy to get wrong in a background
worker and impossible to notice: **isolation**. One expired Spotify grant, or one session that
was chimed out a moment ago, must not stop the loop before it reaches the next session. A job
that raises is only logged by APScheduler, and every session after the failing one is skipped
until the next tick.

The scheduler is off in these tests (``ENABLE_SCHEDULER=false`` in conftest), so the ticks are
called directly. That is on purpose: a real 20-second timer would make these tests depend on
wall-clock luck.
"""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.clock import utcnow
from app.models import (
    EVENT_WHOOP_REFRESH,
    STATUS_ACTIVE,
    STATUS_ENDED,
    TRACK_SOURCE_LIBRARY,
    OAuthToken,
    Session,
    SessionEvent,
    SessionTrack,
    Track,
    User,
    UserTrack,
)
from app.core.crypto import encrypt
from app.integrations.spotify import auth as spotify_auth
from app.services import scheduler, whoop_sync

API = "https://api.spotify.com/v1"
PLAYLIST_URI = "spotify:playlist:pl1"
DURATION_MS = 200_000


@pytest.fixture
def spotify_token(db: DbSession, user: User) -> None:
    """A stored Spotify grant, since the jobs build their own clients from the token store."""
    db.add(
        OAuthToken(
            user_id=user.id,
            provider="spotify",
            access_token_enc=encrypt("access-token"),
            refresh_token_enc=encrypt("refresh-token"),
            expires_at=utcnow() + timedelta(hours=1),
            scopes=spotify_auth.SCOPE_STRING,
        )
    )
    db.commit()


@pytest.fixture
def session(db: DbSession, user: User, spotify_token: None) -> Session:
    row = Session(
        user_id=user.id,
        status=STATUS_ACTIVE,
        type="focus",
        intent="match",
        started_at=utcnow(),
        playlist_uri=PLAYLIST_URI,
        playlist_name="Chime · Focus",
    )
    db.add(row)
    db.flush()
    track = Track(
        spotify_track_id="t0",
        name="a song",
        artist_ids=["a1"],
        artist_names=["an artist"],
        duration_ms=DURATION_MS,
    )
    db.add(track)
    db.flush()
    db.add(UserTrack(user_id=user.id, track_id=track.id, source="liked"))
    db.add(
        SessionTrack(
            session_id=row.id, position=0, track_id=track.id, source=TRACK_SOURCE_LIBRARY
        )
    )
    db.commit()
    return row


def mock_playback(*, track_id: str = "t0", progress_ms: int = 5_000) -> respx.Route:
    return respx.get(f"{API}/me/player").mock(
        return_value=httpx.Response(
            200,
            json={
                "is_playing": True,
                "progress_ms": progress_ms,
                "item": {"id": track_id, "name": "a song", "duration_ms": DURATION_MS},
                "context": {"uri": PLAYLIST_URI, "type": "playlist"},
            },
        )
    )


# -------------------------------------------------------------- playback ticks


@respx.mock
async def test_the_playback_tick_measures_a_live_session(
    db: DbSession, session: Session
) -> None:
    mock_playback()

    assert await scheduler.tick_playback() == 1

    row = db.scalars(select(SessionTrack).where(SessionTrack.session_id == session.id)).one()
    db.refresh(row)
    assert row.started_at is not None
    assert row.played_ms == 5_000


@respx.mock
async def test_the_playback_tick_does_nothing_without_a_live_session(
    db: DbSession, session: Session
) -> None:
    """An idle Chime makes no outbound requests at all, which is what keeps the poll cheap."""
    session.status = STATUS_ENDED
    session.ended_at = utcnow()
    db.commit()
    route = mock_playback()

    assert await scheduler.tick_playback() == 0
    assert not route.called


@respx.mock
async def test_an_unreadable_session_does_not_stop_the_others(
    db: DbSession, user: User, session: Session
) -> None:
    """A second session whose playback read fails must not cost the first its measurement.

    Two sessions for one user cannot normally happen, but the shape of the failure is the same
    as two users where one grant has expired, and this is the cheaper way to set it up.
    """
    other = Session(
        user_id=user.id,
        status=STATUS_ACTIVE,
        type="focus",
        started_at=utcnow(),
        playlist_uri="spotify:playlist:pl2",
    )
    db.add(other)
    db.commit()
    respx.get(f"{API}/me/player").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "is_playing": True,
                    "progress_ms": 5_000,
                    "item": {"id": "t0", "duration_ms": DURATION_MS},
                    "context": {"uri": PLAYLIST_URI, "type": "playlist"},
                },
            ),
            httpx.Response(401, json={"error": {"status": 401, "message": "expired"}}),
        ]
    )

    # One read succeeded, one failed, and the tick still finished.
    assert await scheduler.tick_playback() == 1
    row = db.scalars(select(SessionTrack).where(SessionTrack.session_id == session.id)).one()
    db.refresh(row)
    assert row.played_ms == 5_000


@respx.mock
async def test_a_session_ended_mid_tick_is_skipped(db: DbSession, session: Session) -> None:
    """Chime out can land between listing the sessions and polling one of them."""
    route = mock_playback()
    session_id = session.id

    live = scheduler._live_sessions()
    assert live == [(session_id, session.user_id)]
    session.status = STATUS_ENDED
    session.ended_at = utcnow()
    db.commit()

    assert await scheduler._poll_one(session_id, session.user_id) == 0
    assert not route.called


# ------------------------------------------------------------- adaptation ticks


@respx.mock
async def test_the_adaptation_tick_reaches_a_live_session(
    db: DbSession, session: Session
) -> None:
    """One track queued and nothing to add it from, so the trigger fires and finds nothing.

    The point is that the job got as far as the decision: an empty library is the honest
    answer, and it must not raise.
    """
    assert await scheduler.tick_adaptation() == 0
    assert (
        db.scalars(
            select(SessionEvent).where(SessionEvent.session_id == session.id)
        ).all()
        == []
    )


@respx.mock
async def test_a_failed_playlist_edit_does_not_stop_the_tick(
    db: DbSession, user: User, session: Session
) -> None:
    """The session plays on with what it has, and the next tick tries again."""
    for index in range(20):
        track = Track(
            spotify_track_id=f"lib{index}",
            name=f"track {index}",
            artist_ids=[f"a{index % 5}"],
            artist_names=[f"artist {index % 5}"],
            duration_ms=DURATION_MS,
        )
        db.add(track)
        db.flush()
        db.add(UserTrack(user_id=user.id, track_id=track.id, source="liked"))
    db.commit()
    respx.post(f"{API}/playlists/pl1/items").mock(
        return_value=httpx.Response(502, json={"error": {"status": 502, "message": "boom"}})
    )

    assert await scheduler.tick_adaptation() == 0
    assert (
        db.scalars(
            select(SessionEvent).where(SessionEvent.session_id == session.id)
        ).all()
        == []
    )


# ------------------------------------------------------------------ whoop ticks


async def test_the_whoop_tick_records_a_refresh_that_changed_something(
    db: DbSession, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def refreshed(user_id: int, **_: object) -> whoop_sync.RefreshResult:
        return whoop_sync.RefreshResult(days=1, workouts=2)

    monkeypatch.setattr(whoop_sync, "refresh_body_data", refreshed)

    assert await scheduler.tick_whoop() == 1

    event = db.scalars(
        select(SessionEvent).where(
            SessionEvent.session_id == session.id, SessionEvent.type == EVENT_WHOOP_REFRESH
        )
    ).one()
    assert event.payload == {"days": 1, "workouts": 2}


async def test_a_refresh_that_changed_nothing_is_not_worth_recording(
    db: DbSession, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Otherwise every session's timeline fills with "refreshed WHOOP" four times an hour."""

    async def unchanged(user_id: int, **_: object) -> whoop_sync.RefreshResult:
        return whoop_sync.RefreshResult(skipped=True)

    monkeypatch.setattr(whoop_sync, "refresh_body_data", unchanged)

    assert await scheduler.tick_whoop() == 0
    assert (
        db.scalars(
            select(SessionEvent).where(SessionEvent.type == EVENT_WHOOP_REFRESH)
        ).all()
        == []
    )


async def test_a_whoop_failure_does_not_stop_the_tick(
    db: DbSession, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(user_id: int, **_: object) -> whoop_sync.RefreshResult:
        raise RuntimeError("whoop is having a bad morning")

    monkeypatch.setattr(whoop_sync, "refresh_body_data", broken)

    assert await scheduler.tick_whoop() == 0


async def test_the_whoop_tick_ignores_users_who_are_not_listening(
    db: DbSession, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Body data is read on demand at Chime in, so polling an idle user spends WHOOP's
    budget on an answer nobody asked for."""
    called: list[int] = []

    async def refreshed(user_id: int, **_: object) -> whoop_sync.RefreshResult:
        called.append(user_id)
        return whoop_sync.RefreshResult(days=1)

    monkeypatch.setattr(whoop_sync, "refresh_body_data", refreshed)

    assert await scheduler.tick_whoop() == 0
    assert called == []


# -------------------------------------------------------------- on and off


def test_the_loop_stays_off_when_it_is_switched_off() -> None:
    """``ENABLE_SCHEDULER=false`` is how the tests run and how a second process stays quiet."""
    assert scheduler.start() is None
    scheduler.shutdown()  # safe to call either way
