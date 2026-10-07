"""The behaviour counters (SPEC section 5, step 5).

These are what finally make 15% of the ranking score mean something: before phase 6 nothing
wrote ``plays``, ``completes``, ``fast_skips`` or ``kept_count``, so ``behavior_boost`` scored
every track at neutral for ever. What is worth testing is the arithmetic being *conservative*
— a mid-track skip is not evidence against a song, and a track that has left the library must
not come back through a counter update.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.clock import utcnow
from app.models import (
    STATUS_ACTIVE,
    TRACK_SOURCE_LIBRARY,
    Session,
    SessionTrack,
    Track,
    User,
    UserTrack,
)
from app.services import behavior


@pytest.fixture
def track(db: DbSession) -> Track:
    row = Track(
        spotify_track_id="t1",
        name="a song",
        artist_ids=["a1"],
        artist_names=["an artist"],
        duration_ms=200_000,
    )
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def liked(db: DbSession, user: User, track: Track) -> UserTrack:
    row = UserTrack(user_id=user.id, track_id=track.id, source="liked")
    db.add(row)
    db.commit()
    return row


def test_finishing_a_track_counts_a_play_and_a_complete(
    db: DbSession, user: User, track: Track, liked: UserTrack
) -> None:
    behavior.record_finish(db, user.id, track.id, played_ms=190_000, skipped=False)

    db.refresh(liked)
    assert liked.plays == 1
    assert liked.completes == 1
    assert liked.fast_skips == 0
    assert liked.last_played_at is not None


def test_a_fast_skip_counts_against_the_track(
    db: DbSession, user: User, track: Track, liked: UserTrack
) -> None:
    behavior.record_finish(db, user.id, track.id, played_ms=4_000, skipped=True)

    db.refresh(liked)
    assert liked.plays == 1
    assert liked.completes == 0
    assert liked.fast_skips == 1


def test_a_skip_part_way_through_counts_neither_way(
    db: DbSession, user: User, track: Track, liked: UserTrack
) -> None:
    """Someone who listened to a minute and moved on has not told us they dislike it.

    SPEC only calls a *fast* skip evidence against a track, and this is why: the boost would
    otherwise punish every long song someone dips into.
    """
    behavior.record_finish(db, user.id, track.id, played_ms=55_000, skipped=True)

    db.refresh(liked)
    assert liked.plays == 1
    assert liked.completes == 0
    assert liked.fast_skips == 0


def test_a_track_no_longer_in_the_library_is_left_alone(
    db: DbSession, user: User, track: Track
) -> None:
    """No ``user_tracks`` row means they unliked it mid-session.

    Inventing a row here would quietly put the track back in the candidate pool, which is the
    opposite of what unliking it meant.
    """
    behavior.record_finish(db, user.id, track.id, played_ms=190_000, skipped=False)

    assert db.scalars(select(UserTrack)).all() == []


def test_every_row_for_a_pair_is_updated(
    db: DbSession, user: User, track: Track, liked: UserTrack
) -> None:
    """``user_tracks`` is keyed by source, so one track can hold several rows for one user.

    Updating only the first would make the counters depend on which source happened to be
    inserted first, and ranking reads whichever row the candidate query joined.
    """
    other = UserTrack(user_id=user.id, track_id=track.id, source="playlist")
    db.add(other)
    db.commit()

    behavior.record_finish(db, user.id, track.id, played_ms=190_000, skipped=False)

    db.refresh(liked)
    db.refresh(other)
    assert liked.completes == 1
    assert other.completes == 1


def test_keeping_a_session_credits_every_track_in_it(
    db: DbSession, user: User, track: Track, liked: UserTrack
) -> None:
    """A kept playlist is the strongest signal there is, so SPEC weights it double."""
    session = Session(
        user_id=user.id, status=STATUS_ACTIVE, type="focus", started_at=utcnow(), kept=True
    )
    db.add(session)
    db.flush()
    db.add(
        SessionTrack(
            session_id=session.id,
            position=0,
            track_id=track.id,
            source=TRACK_SOURCE_LIBRARY,
        )
    )
    db.commit()

    credited = behavior.record_keep(db, session)

    db.refresh(liked)
    assert credited == 1
    assert liked.kept_count == 1
    # Keeping is not listening: it must not move the play counters.
    assert liked.plays == 0
    assert liked.completes == 0
