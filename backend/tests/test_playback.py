"""The playback sampler (SPEC section 6).

Spotify only answers "what is playing now", so every one of these tests is really about the
same question: what may a series of snapshots honestly claim? The answers that matter —

* progress is a position, not a total, so a seek backwards must not lose or double-count it;
* a track is judged only once playback has left it;
* silence, a pause and an unreadable answer change nothing at all;
* and a session ended mid-track has not had that track rejected.

Each of those is one wrong line away from feeding a lie into the behaviour counters, which
then shape the ranking for the next sixty days.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from sqlalchemy.orm import Session as DbSession

from app.core.clock import utcnow
from app.integrations.spotify.client import SpotifyClient
from app.integrations.spotify.schemas import PlaybackState
from app.models import (
    STATUS_ACTIVE,
    STATUS_CREATED,
    TRACK_SOURCE_LIBRARY,
    Session,
    SessionTrack,
    Track,
    User,
    UserTrack,
)
from app.services import playback

API = "https://api.spotify.com/v1"
PLAYLIST_URI = "spotify:playlist:pl1"
DURATION_MS = 200_000


class FakeTokens:
    async def get_access_token(self, *, force_refresh: bool = False) -> str:
        return "access-token"


@pytest.fixture
async def spotify():
    async with SpotifyClient(FakeTokens()) as client:
        yield client


@pytest.fixture
def session(db: DbSession, user: User) -> Session:
    """A three-track active session, every track liked so the counters have somewhere to go."""
    row = Session(
        user_id=user.id,
        status=STATUS_ACTIVE,
        type="focus",
        started_at=utcnow(),
        playlist_uri=PLAYLIST_URI,
        playlist_name="Chime · Focus",
    )
    db.add(row)
    db.flush()
    for position in range(3):
        track = Track(
            spotify_track_id=f"t{position}",
            name=f"track {position}",
            artist_ids=[f"a{position}"],
            artist_names=[f"artist {position}"],
            duration_ms=DURATION_MS,
        )
        db.add(track)
        db.flush()
        db.add(UserTrack(user_id=user.id, track_id=track.id, source="liked"))
        db.add(
            SessionTrack(
                session_id=row.id,
                position=position,
                track_id=track.id,
                source=TRACK_SOURCE_LIBRARY,
            )
        )
    db.commit()
    return row


def state(
    track_id: str | None,
    progress_ms: int,
    *,
    is_playing: bool = True,
    context: str | None = PLAYLIST_URI,
) -> PlaybackState:
    return PlaybackState.model_validate(
        {
            "is_playing": is_playing,
            "progress_ms": progress_ms,
            "item": {"id": track_id, "name": "whatever", "duration_ms": DURATION_MS},
            "context": {"uri": context, "type": "playlist"} if context else None,
        }
    )


def row_at(db: DbSession, session: Session, position: int) -> SessionTrack:
    row = next(track for track in session.tracks if track.position == position)
    db.refresh(row)
    return row


# ------------------------------------------------------------------- measuring


def test_a_snapshot_starts_the_track_it_is_on(db: DbSession, session: Session) -> None:
    observed = playback.record(db, session, state("t0", 5_000))

    assert observed.playing == 0
    first = row_at(db, session, 0)
    assert first.started_at is not None
    assert first.played_ms == 5_000
    # Nothing is decided while it is still playing.
    assert first.finished_at is None
    assert first.skipped is False


def test_progress_is_the_furthest_point_reached(db: DbSession, session: Session) -> None:
    """A seek backwards, or a replay, must neither reduce nor accumulate the total.

    ``progress_ms`` is where the needle is. Adding the samples up would count a repeat as a
    longer listen; taking the last one would let a rewind erase a full play.
    """
    playback.record(db, session, state("t0", 120_000))
    playback.record(db, session, state("t0", 3_000))

    assert row_at(db, session, 0).played_ms == 120_000


def test_a_pause_changes_nothing(db: DbSession, session: Session) -> None:
    playback.record(db, session, state("t0", 120_000))

    observed = playback.record(db, session, state("t0", 120_000, is_playing=False))

    assert observed.idle is True
    first = row_at(db, session, 0)
    assert first.finished_at is None  # a phone call is not a skip
    assert first.played_ms == 120_000


def test_nothing_playing_changes_nothing(db: DbSession, session: Session) -> None:
    playback.record(db, session, state("t0", 120_000))

    observed = playback.record(db, session, None)

    assert observed.idle is True
    assert row_at(db, session, 0).finished_at is None


def test_moving_on_judges_the_track_left_behind(
    db: DbSession, user: User, session: Session
) -> None:
    playback.record(db, session, state("t0", 190_000))
    observed = playback.record(db, session, state("t1", 2_000))

    assert observed.playing == 1
    assert observed.finished == (0,)
    assert observed.skipped == ()

    first = row_at(db, session, 0)
    assert first.finished_at is not None
    assert first.skipped is False

    liked = next(row for row in db.query(UserTrack).all() if row.track_id == first.track_id)
    assert liked.completes == 1
    assert liked.fast_skips == 0


def test_a_track_dropped_early_is_a_skip(db: DbSession, session: Session) -> None:
    playback.record(db, session, state("t0", 4_000))
    observed = playback.record(db, session, state("t1", 1_000))

    assert observed.skipped == (0,)
    assert row_at(db, session, 0).skipped is True


def test_a_third_of_the_way_through_is_not_a_skip(db: DbSession, session: Session) -> None:
    """SPEC's threshold is 30%, so 70 s of a 200 s track counts as listened to."""
    playback.record(db, session, state("t0", 70_000))
    playback.record(db, session, state("t1", 1_000))

    assert row_at(db, session, 0).skipped is False


def test_tracks_missed_between_two_polls_are_still_judged(
    db: DbSession, session: Session
) -> None:
    """At a 20-second poll a short track can come and go unseen, and that is not fixable.

    What *is* fixable is leaving a row open for ever because nothing ever saw playback move
    off it. Anything started but unjudged is closed on whatever we last saw of it.
    """
    playback.record(db, session, state("t0", 2_000))
    playback.record(db, session, state("t1", 2_000))
    observed = playback.record(db, session, state("t2", 2_000))

    assert observed.finished == (1,)
    assert row_at(db, session, 0).finished_at is not None
    assert row_at(db, session, 1).finished_at is not None


def test_playing_something_else_is_left_alone(db: DbSession, session: Session) -> None:
    """Wandering off to another playlist is not a verdict on the track we were on."""
    playback.record(db, session, state("t0", 50_000))

    observed = playback.record(db, session, state("x1", 5_000, context="spotify:album:other"))

    assert observed.off_context is True
    first = row_at(db, session, 0)
    assert first.finished_at is None
    assert first.played_ms == 50_000


def test_a_track_we_do_not_know_is_idle(db: DbSession, session: Session) -> None:
    """Our own playlist, but a track added to it by hand. Nothing of ours to measure."""
    observed = playback.record(db, session, state("unknown", 5_000))

    assert observed.idle is True
    assert observed.playing is None


# ------------------------------------------------------------------- promotion


def test_our_playlist_playing_makes_a_created_session_active(
    db: DbSession, session: Session
) -> None:
    session.status = STATUS_CREATED
    db.commit()

    observed = playback.record(db, session, state("t0", 1_000))

    assert observed.promoted is True
    assert session.status == STATUS_ACTIVE


def test_something_else_playing_does_not_start_a_session(
    db: DbSession, session: Session
) -> None:
    session.status = STATUS_CREATED
    db.commit()

    observed = playback.record(db, session, state("x1", 1_000, context="spotify:album:other"))

    assert observed.promoted is False
    assert session.status == STATUS_CREATED


# --------------------------------------------------------------------- closing


def test_chime_out_closes_the_last_track_without_judging_it(
    db: DbSession, user: User, session: Session
) -> None:
    """The track playing at Chime out has nothing to move off it, so this closes it.

    Unjudged on purpose: stopping a session 30 seconds into a song is the user finishing with
    Chime, not rejecting the song. Judging it would put a black mark against whatever tends to
    be playing at bedtime, every night, until the ranking learned to avoid it.
    """
    playback.record(db, session, state("t0", 30_000))

    closed = playback.finish_open(db, session)

    assert closed == [0]
    first = row_at(db, session, 0)
    assert first.finished_at is not None
    assert first.skipped is False
    liked = next(row for row in db.query(UserTrack).all() if row.track_id == first.track_id)
    assert liked.plays == 0
    assert liked.fast_skips == 0


def test_closing_a_session_that_never_played_does_nothing(
    db: DbSession, session: Session
) -> None:
    assert playback.finish_open(db, session) == []


# ---------------------------------------------------------------------- counts


def test_counts_report_what_started_and_what_was_skipped(
    db: DbSession, session: Session
) -> None:
    playback.record(db, session, state("t0", 2_000))
    playback.record(db, session, state("t1", 190_000))
    playback.record(db, session, state("t2", 1_000))

    assert playback.counts(db, session.id) == (3, 1)


def test_recent_skips_only_counts_judged_tracks(db: DbSession, session: Session) -> None:
    """The track playing now has not had its chance, so it must not dilute the window.

    Counting it as a non-skip would hide a run of three skips from the adaptation trigger for
    as long as something was playing — which is always.
    """
    playback.record(db, session, state("t0", 1_000))
    playback.record(db, session, state("t1", 1_000))
    playback.record(db, session, state("t2", 1_000))

    assert playback.recent_skips(db, session.id) == (2, 2)


def test_recent_skips_can_ignore_what_is_already_answered(
    db: DbSession, session: Session
) -> None:
    """``since`` is what stops one run of skips triggering an adaptation every five minutes.

    The watermark is the moment a track was *judged*, not the moment it started, because that
    is when the skip became something an adaptation could have reacted to.
    """
    playback.record(db, session, state("t0", 1_000))
    playback.record(db, session, state("t1", 1_000))  # judges t0 a skip
    assert playback.recent_skips(db, session.id) == (1, 1)

    watermark = utcnow()
    playback.record(db, session, state("t2", 1_000))  # judges t1 a skip

    # t0 was already answered; only t1 is news since the watermark.
    assert playback.recent_skips(db, session.id, since=watermark) == (1, 1)
    assert playback.recent_skips(db, session.id) == (2, 2)


def test_is_skip_falls_back_to_the_floor_without_a_duration() -> None:
    """A track with no duration cached: 30% of zero would call every play complete."""
    assert playback.is_skip(4_000, 0) is True
    assert playback.is_skip(11_000, 0) is False


# ----------------------------------------------------------------------- polling


@respx.mock
async def test_poll_records_what_spotify_reports(
    db: DbSession, session: Session, spotify: SpotifyClient
) -> None:
    respx.get(f"{API}/me/player").mock(
        return_value=httpx.Response(
            200,
            json={
                "is_playing": True,
                "progress_ms": 5_000,
                "item": {"id": "t0", "name": "track 0", "duration_ms": DURATION_MS},
                "context": {"uri": PLAYLIST_URI, "type": "playlist"},
            },
        )
    )

    observed = await playback.poll(db, session, spotify=spotify)

    assert observed is not None and observed.playing == 0
    assert row_at(db, session, 0).played_ms == 5_000


@respx.mock
async def test_poll_answers_none_when_spotify_cannot_be_read(
    db: DbSession, session: Session, spotify: SpotifyClient
) -> None:
    """"Spotify did not answer" is not a measurement, and must not read as "nothing played"."""
    respx.get(f"{API}/me/player").mock(
        return_value=httpx.Response(500, json={"error": {"status": 500, "message": "boom"}})
    )
    playback.record(db, session, state("t0", 50_000))

    assert await playback.poll(db, session, spotify=spotify) is None
    assert row_at(db, session, 0).finished_at is None
