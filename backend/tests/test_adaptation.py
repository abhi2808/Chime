"""Mid-session adaptation (SPEC section 6).

The triggers are easy to get nearly right and hard to get right, so most of these tests are
about the ways an adaptation could misbehave rather than the happy path: reacting to the same
run of skips for ever, throwing away a queue that was only running low, restarting the energy
curve half way through a workout, or deleting tracks the user has already heard.

The Spotify side is asserted on directly, because the ordering is a safety property: tracks
are added before any are removed, so a failure part way through can only ever leave the
playlist longer than intended — never short while someone is listening to it.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.clock import utcnow
from app.integrations.spotify.client import SpotifyClient
from app.integrations.spotify.schemas import PlaybackState
from app.models import (
    EVENT_ADAPT,
    EVENT_MOOD_CHECK,
    STATUS_ACTIVE,
    STATUS_CREATED,
    TRACK_SOURCE_ADAPT,
    TRACK_SOURCE_LIBRARY,
    Session,
    SessionEvent,
    SessionTrack,
    Track,
    TrackTag,
    User,
    UserTrack,
)
from app.services import adaptation, body_state, playback
from app.services.profile_rules import build_profile

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
def library(db: DbSession, user: User) -> None:
    """Forty liked tracks across eight artists, so there is always something new to add."""
    for index in range(40):
        track = Track(
            spotify_track_id=f"lib{index}",
            name=f"library track {index}",
            artist_ids=[f"a{index % 8}"],
            artist_names=[f"artist {index % 8}"],
            duration_ms=DURATION_MS,
        )
        db.add(track)
        db.flush()
        db.add(UserTrack(user_id=user.id, track_id=track.id, source="liked"))
        db.add(
            TrackTag(
                track_id=track.id,
                energy=1.0 + (index % 5),
                affinities={"focus": 0.7, "calm": 0.5},
                confidence=0.8,
                source="external",
                raw_tags=[["ambient", 1.0]],
            )
        )
    db.commit()


@pytest.fixture
def session(db: DbSession, user: User, library: None) -> Session:
    """An active session holding a handful of the library's tracks, none of them played yet.

    ``body_in`` records the body state as it is *right now*, which is what Chime in does. It
    matters here: a fixture that hard-coded a readiness would differ from the live reading and
    fire the body trigger on every one of these tests, hiding the trigger being tested.
    """
    state = body_state.build(db, user.id)
    row = Session(
        user_id=user.id,
        status=STATUS_ACTIVE,
        type="focus",
        intent="match",
        mood_in="flat",
        started_at=utcnow(),
        playlist_uri=PLAYLIST_URI,
        playlist_name="Chime · Focus",
        body_in={"readiness": state.readiness, "day_part": state.day_part},
    )
    db.add(row)
    db.flush()
    tracks = db.scalars(select(Track).order_by(Track.id).limit(6)).all()
    for position, track in enumerate(tracks):
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


def mock_add() -> respx.Route:
    return respx.post(f"{API}/playlists/pl1/items").mock(
        return_value=httpx.Response(201, json={"snapshot_id": "snap-add"})
    )


def mock_remove() -> respx.Route:
    return respx.delete(f"{API}/playlists/pl1/items").mock(
        return_value=httpx.Response(200, json={"snapshot_id": "snap-remove"})
    )


def play(db: DbSession, session: Session, position: int, progress_ms: int) -> None:
    """Move playback onto one of the session's tracks, through the real sampler.

    Through ``playback.record`` rather than by setting columns, so these tests exercise the
    same path the scheduler does: the triggers read what measurement wrote, and a trigger that
    only fires against hand-written rows would be no use.
    """
    track = next(row.track for row in session.tracks if row.position == position)
    playback.record(
        db,
        session,
        PlaybackState.model_validate(
            {
                "is_playing": True,
                "progress_ms": progress_ms,
                "item": {"id": track.spotify_track_id, "duration_ms": DURATION_MS},
                "context": {"uri": PLAYLIST_URI, "type": "playlist"},
            }
        ),
    )


def rows(db: DbSession, session: Session) -> list[SessionTrack]:
    db.expire_all()
    return list(
        db.scalars(
            select(SessionTrack)
            .where(SessionTrack.session_id == session.id)
            .order_by(SessionTrack.position)
        ).all()
    )


def adapt_events(db: DbSession, session: Session) -> list[SessionEvent]:
    return list(
        db.scalars(
            select(SessionEvent)
            .where(SessionEvent.session_id == session.id, SessionEvent.type == EVENT_ADAPT)
            .order_by(SessionEvent.id)
        ).all()
    )


# ------------------------------------------------------------- nothing to do


@respx.mock
async def test_a_session_going_well_is_left_alone(
    db: DbSession, session: Session, spotify: SpotifyClient
) -> None:
    """The usual answer. Six tracks queued, nothing skipped, no mood check: no triggers."""
    add, remove = mock_add(), mock_remove()

    assert await adaptation.adapt(db, session, spotify=spotify) is None
    assert not add.called and not remove.called
    assert adapt_events(db, session) == []


@respx.mock
async def test_a_session_that_has_not_started_is_left_alone(
    db: DbSession, session: Session, spotify: SpotifyClient
) -> None:
    """Editing a playlist someone is one tap away from starting would change what they get."""
    session.status = STATUS_CREATED
    db.commit()
    add = mock_add()

    assert await adaptation.adapt(db, session, spotify=spotify) is None
    assert not add.called


# ------------------------------------------------------------------- triggers


@respx.mock
async def test_running_low_tops_the_queue_up_without_trimming(
    db: DbSession, session: Session, spotify: SpotifyClient
) -> None:
    """Fewer than three left is not a change of plan, so what is queued must survive it."""
    add, remove = mock_add(), mock_remove()
    for position in range(4):
        play(db, session, position, 190_000)
    still_queued = [row.id for row in rows(db, session) if row.started_at is None]
    assert len(still_queued) == 2

    result = await adaptation.adapt(db, session, spotify=spotify)

    assert result is not None
    assert result.triggers == (adaptation.TRIGGER_RUNNING_OUT,)
    assert result.removed == 0
    assert not remove.called
    assert add.called
    surviving = {row.id for row in rows(db, session)}
    assert set(still_queued) <= surviving
    # Topped up to the target, counting what was already there.
    assert len([row for row in rows(db, session) if row.started_at is None]) == (
        adaptation.TARGET_UPCOMING
    )


@respx.mock
async def test_a_mood_check_replaces_what_is_coming_up(
    db: DbSession, session: Session, spotify: SpotifyClient
) -> None:
    add, remove = mock_add(), mock_remove()
    play(db, session, 0, 50_000)
    queued = [row.id for row in rows(db, session) if row.started_at is None]
    db.add(SessionEvent(session_id=session.id, type=EVENT_MOOD_CHECK, payload={"mood": "wired"}))
    db.commit()

    result = await adaptation.adapt(db, session, spotify=spotify)

    assert result is not None
    assert adaptation.TRIGGER_MOOD in result.triggers
    assert result.mood == "wired"
    assert result.removed == len(queued)
    assert remove.called
    # Everything that was coming is gone; the track playing and the one played are not.
    surviving = {row.id for row in rows(db, session)}
    assert surviving.isdisjoint(queued)
    assert len([row for row in rows(db, session) if row.started_at is not None]) == 1


@respx.mock
async def test_three_skips_out_of_five_change_the_plan(
    db: DbSession, session: Session, spotify: SpotifyClient
) -> None:
    add, remove = mock_add(), mock_remove()
    for position in range(3):
        play(db, session, position, 2_000)
    play(db, session, 3, 5_000)  # the fourth is playing, so three are judged skips

    result = await adaptation.adapt(db, session, spotify=spotify)

    assert result is not None
    assert adaptation.TRIGGER_SKIPS in result.triggers
    assert remove.called and add.called


@respx.mock
async def test_the_same_run_of_skips_does_not_trigger_twice(
    db: DbSession, session: Session, spotify: SpotifyClient
) -> None:
    """Otherwise a bad patch early on would churn the mix every five minutes for an hour."""
    mock_add()
    mock_remove()
    for position in range(3):
        play(db, session, position, 2_000)
    play(db, session, 3, 5_000)

    first = await adaptation.adapt(db, session, spotify=spotify)
    assert first is not None and adaptation.TRIGGER_SKIPS in first.triggers

    second = await adaptation.adapt(db, session, spotify=spotify)

    assert second is None
    assert len(adapt_events(db, session)) == 1


@respx.mock
async def test_a_body_change_since_the_last_adaptation_triggers_one(
    db: DbSession, session: Session, spotify: SpotifyClient
) -> None:
    """Readiness is compared against the plan in force, not against a fixed starting point.

    This session was planned for a green morning; the live reading (no WHOOP in tests) has no
    readiness at all, and that difference is what SPEC means by the body state having moved.
    Once an adaptation has run, *its* numbers are the plan in force, so the same difference
    must not fire again — that is the second half of the test.
    """
    add, remove = mock_add(), mock_remove()
    session.body_in = {"readiness": "green", "day_part": "morning"}
    db.commit()
    play(db, session, 0, 50_000)

    result = await adaptation.adapt(db, session, spotify=spotify)

    assert result is not None
    assert adaptation.TRIGGER_BODY in result.triggers
    assert add.called and remove.called

    # Now the plan in force records the *current* body state, so nothing has changed again.
    assert await adaptation.adapt(db, session, spotify=spotify) is None


# --------------------------------------------------------------- what it writes


@respx.mock
async def test_new_tracks_are_marked_as_adaptations_and_queued_after_the_rest(
    db: DbSession, session: Session, spotify: SpotifyClient
) -> None:
    mock_add()
    mock_remove()
    for position in range(4):
        play(db, session, position, 190_000)
    highest = max(row.position for row in rows(db, session))

    result = await adaptation.adapt(db, session, spotify=spotify)

    assert result is not None
    added = [row for row in rows(db, session) if row.source == TRACK_SOURCE_ADAPT]
    assert len(added) == result.added
    assert all(row.position > highest for row in added)
    assert all(row.started_at is None and row.played_ms == 0 for row in added)
    assert all(row.score_breakdown and "target" in row.score_breakdown for row in added)


@respx.mock
async def test_it_never_offers_a_track_the_session_already_used(
    db: DbSession, session: Session, spotify: SpotifyClient
) -> None:
    """A song that was just skipped coming straight back would read as a bug."""
    mock_add()
    mock_remove()
    for position in range(4):
        play(db, session, position, 2_000)
    played = {row.track_id for row in rows(db, session)}

    await adaptation.adapt(db, session, spotify=spotify)

    added = [row for row in rows(db, session) if row.source == TRACK_SOURCE_ADAPT]
    assert added
    assert {row.track_id for row in added}.isdisjoint(played)


@respx.mock
async def test_the_event_records_numbers_and_no_spotify_content(
    db: DbSession, session: Session, spotify: SpotifyClient
) -> None:
    """CLAUDE.md rule 7: nothing on this payload may name a track, artist or playlist.

    The timeline is the one place a session's own words get written down, and the "why this
    mix" sentence is written by an LLM from exactly these fields.
    """
    mock_add()
    mock_remove()
    for position in range(4):
        play(db, session, position, 190_000)

    result = await adaptation.adapt(db, session, spotify=spotify)

    assert result is not None
    event = adapt_events(db, session)[-1]
    payload = event.payload or {}
    assert payload["triggers"] == list(result.triggers)
    assert payload["added"] == result.added
    assert payload["removed"] == result.removed
    assert payload["day_part"] == result.day_part
    assert "energy_start" in payload and "energy_end" in payload

    names = {track.name for track in db.scalars(select(Track)).all()}
    written = repr(payload)
    assert not any(name in written for name in names)
    assert "pl1" not in written


@respx.mock
async def test_tracks_are_added_before_any_are_removed(
    db: DbSession, session: Session, spotify: SpotifyClient
) -> None:
    """A safety property, not a preference.

    If the add fails the playlist is untouched; if the remove fails it is longer than intended
    but still playing. The other order can leave a session short mid-playback.
    """
    calls: list[str] = []

    def note(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(200, json={"snapshot_id": "snap"})

    respx.post(f"{API}/playlists/pl1/items").mock(side_effect=note)
    respx.delete(f"{API}/playlists/pl1/items").mock(side_effect=note)
    play(db, session, 0, 50_000)
    db.add(SessionEvent(session_id=session.id, type=EVENT_MOOD_CHECK, payload={"mood": "wired"}))
    db.commit()

    await adaptation.adapt(db, session, spotify=spotify)

    assert calls == ["POST", "DELETE"]


@respx.mock
async def test_a_failed_add_leaves_the_session_exactly_as_it_was(
    db: DbSession, session: Session, spotify: SpotifyClient
) -> None:
    respx.post(f"{API}/playlists/pl1/items").mock(
        return_value=httpx.Response(500, json={"error": {"status": 500, "message": "boom"}})
    )
    remove = mock_remove()
    play(db, session, 0, 50_000)
    db.add(SessionEvent(session_id=session.id, type=EVENT_MOOD_CHECK, payload={"mood": "wired"}))
    db.commit()
    before = [row.id for row in rows(db, session)]

    with pytest.raises(Exception):
        await adaptation.adapt(db, session, spotify=spotify)

    assert not remove.called
    assert [row.id for row in rows(db, session)] == before
    assert adapt_events(db, session) == []


@respx.mock
async def test_the_curve_carries_on_instead_of_starting_again(
    db: DbSession, user: User, spotify: SpotifyClient, library: None
) -> None:
    """A workout that is half an hour in must not drop back to its opening energy.

    An adaptation fills the *tail* of a session, so it samples the target curve from where the
    session has got to. Asserted against what a fresh, from-the-top curve would have asked
    for, because that is the bug: ``profile.curve(count)`` instead of the slice.
    """
    mock_add()
    mock_remove()
    session = Session(
        user_id=user.id,
        status=STATUS_ACTIVE,
        type="workout",
        intent="match",
        started_at=utcnow(),
        playlist_uri=PLAYLIST_URI,
        playlist_name="Chime · Workout",
        body_in={"day_part": "morning"},
    )
    db.add(session)
    db.flush()
    for position, track in enumerate(db.scalars(select(Track).order_by(Track.id).limit(6)).all()):
        db.add(
            SessionTrack(
                session_id=session.id,
                position=position,
                track_id=track.id,
                source=TRACK_SOURCE_LIBRARY,
            )
        )
    db.commit()
    for position in range(5):
        play(db, session, position, 190_000)

    result = await adaptation.adapt(db, session, spotify=spotify)

    assert result is not None
    added = sorted(
        (row for row in rows(db, session) if row.source == TRACK_SOURCE_ADAPT),
        key=lambda row: row.position,
    )
    targets = [(row.score_breakdown or {}).get("target") for row in added]
    assert all(target is not None for target in targets)

    # What the bug would have produced: the ramp starting over from the session's opening
    # energy, five tracks in.
    profile = build_profile(
        body_state.build(db, user.id), mood=None, session_type="workout", intent="match"
    )
    from_the_top = profile.curve(len(added))
    assert targets[0] > from_the_top[0]
    # And it is genuinely the tail of the longer curve, not just a higher number.
    assert targets == pytest.approx(profile.curve(5 + len(added))[5:])
