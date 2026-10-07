"""The session engine: Chime in, mood re-check, Chime out.

Most of what is worth testing here is the order of operations and the failure paths,
because those are the design (see the module docstring in ``app.services.sessions``):
nothing external happens until the local work is done, the session row exists before the
playlist does, a Spotify that will not press play leaves the mix in a playlist the user can
start themselves, and a Chime in that ends up with nothing usable leaves nothing behind in
the user's library.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import timedelta

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.clock import utcnow
from app.integrations.spotify.client import SpotifyClient
from app.integrations.spotify.errors import (
    SpotifyAuthError,
    SpotifyNoActiveDeviceError,
)
from app.models import (
    EVENT_ERROR,
    EVENT_MANUAL_START,
    EVENT_MOOD_CHECK,
    STATUS_ACTIVE,
    STATUS_CREATED,
    STATUS_ENDED,
    STATUS_FAILED,
    Session,
    SessionEvent,
    SessionTrack,
    Track,
    TrackTag,
    User,
    UserTrack,
)
from app.services import playback, sessions

API = "https://api.spotify.com/v1"
PLAYLIST = {
    "id": "pl1",
    "uri": "spotify:playlist:pl1",
    "name": "Chime · Focus · 9:20 am",
    "public": False,
}


class FakeTokens:
    async def get_access_token(self, *, force_refresh: bool = False) -> str:
        return "access-token"


@pytest.fixture
async def spotify() -> AsyncIterator[SpotifyClient]:
    async with SpotifyClient(FakeTokens()) as client:
        yield client


@pytest.fixture
def library(db: DbSession, user: User) -> None:
    """Enough tagged tracks across enough artists for a full session to be rankable."""
    for index in range(40):
        track = Track(
            spotify_track_id=f"s{index}",
            name=f"track {index}",
            artist_ids=[f"a{index % 8}"],
            artist_names=[f"artist {index % 8}"],
            album_name="An album",
            duration_ms=200_000,
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


# ------------------------------------------------------------------- mock setup


def mock_devices(*, active: bool = True, empty: bool = False) -> respx.Route:
    devices = (
        []
        if empty
        else [
            {
                "id": "d1",
                "name": "Laptop",
                "type": "Computer",
                "is_active": active,
                "is_restricted": False,
            }
        ]
    )
    return respx.get(f"{API}/me/player/devices").mock(
        return_value=httpx.Response(200, json={"devices": devices})
    )


def mock_create() -> respx.Route:
    return respx.post(f"{API}/me/playlists").mock(
        return_value=httpx.Response(201, json=PLAYLIST)
    )


def mock_items() -> respx.Route:
    return respx.post(f"{API}/playlists/pl1/items").mock(
        return_value=httpx.Response(201, json={"snapshot_id": "snap1"})
    )


def mock_play() -> respx.Route:
    return respx.put(f"{API}/me/player/play").mock(return_value=httpx.Response(204))


def mock_remove(*, status: int = 200, still_there: bool = False) -> respx.Route:
    """Getting rid of a session playlist: unfollow it, then check it is really gone.

    Both halves live in one helper because a removal is only believed once the library says
    so — ``DELETE`` answering 200 was exactly what hid the real bug (see
    :mod:`app.integrations.spotify.playlists`). Returns the unfollow route, which is the one
    tests assert on.
    """
    route = respx.delete(f"{API}/playlists/pl1/followers").mock(
        return_value=httpx.Response(status)
    )
    respx.get(f"{API}/me/library/contains").mock(
        return_value=httpx.Response(200, json=[still_there])
    )
    return route


def mock_happy_path() -> None:
    mock_devices()
    mock_create()
    mock_items()
    mock_play()


async def start(
    db: DbSession, user: User, spotify: SpotifyClient, *, count: int = 6
) -> Session:
    """A session that got all the way to playing, for the tests that start from there."""
    mock_happy_path()
    result = await sessions.chime_in(db, user.id, count=count, spotify=spotify)
    return result.session


# --------------------------------------------------------------------- chime in


@respx.mock
async def test_chime_in_builds_a_playlist_and_starts_it(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    mock_happy_path()

    result = await sessions.chime_in(db, user.id, mood="flat", count=12, spotify=spotify)

    session = result.session
    assert session.status == STATUS_ACTIVE
    assert session.mood_in == "flat"
    assert session.playlist_uri == "spotify:playlist:pl1"
    assert session.playlist_id == "pl1"
    assert session.playlist_name == "Chime · Focus · 9:20 am"
    assert session.why_text
    assert session.target_profile is not None
    assert session.body_in is not None and session.body_in["connected"] is False
    assert result.device_name == "Laptop"

    tracks = db.scalars(
        select(SessionTrack).where(SessionTrack.session_id == session.id)
    ).all()
    assert len(tracks) == 12
    assert sorted(track.position for track in tracks) == list(range(12))
    assert all(track.score_breakdown for track in tracks)
    assert all(track.started_at is None for track in tracks)  # nothing measured yet


@respx.mock
async def test_the_playlist_gets_the_tracks_in_ranked_order(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    mock_happy_path()

    session = (await sessions.chime_in(db, user.id, count=8, spotify=spotify)).session

    added = next(
        call.request for call in respx.calls if call.request.url.path.endswith("/items")
    )
    sent = json.loads(added.content)["uris"]
    ordered = db.scalars(
        select(Track.spotify_track_id)
        .join(SessionTrack, SessionTrack.track_id == Track.id)
        .where(SessionTrack.session_id == session.id)
        .order_by(SessionTrack.position)
    ).all()
    assert sent == [f"spotify:track:{track_id}" for track_id in ordered]


@respx.mock
async def test_an_already_awake_device_is_not_transferred_to(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    mock_happy_path()
    transfer = respx.put(f"{API}/me/player")

    await sessions.chime_in(db, user.id, count=5, spotify=spotify)

    assert transfer.call_count == 0


@respx.mock
async def test_a_sleeping_device_is_woken_before_play(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    mock_devices(active=False)
    mock_create()
    mock_items()
    play = mock_play()
    transfer = respx.put(f"{API}/me/player").mock(return_value=httpx.Response(204))

    await sessions.chime_in(db, user.id, count=5, spotify=spotify)

    assert transfer.call_count == 1
    assert play.call_count == 1


@respx.mock
async def test_no_device_leaves_the_mix_in_a_playlist_to_start_by_hand(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    """Nothing to play on is not a failure: the playlist is the way in."""
    mock_devices(empty=True)
    mock_create()
    mock_items()
    removed = mock_remove()

    result = await sessions.chime_in(db, user.id, count=5, spotify=spotify)

    assert result.manual is not None
    assert result.manual.code == "NO_ACTIVE_DEVICE"
    assert "waiting in a playlist" in result.manual.message
    assert result.device_name is None
    assert removed.call_count == 0

    session = db.scalars(select(Session)).one()
    assert session.status == STATUS_CREATED  # waiting, not failed and not playing
    assert session.ended_at is None
    assert session.playlist_uri == "spotify:playlist:pl1"

    event = db.scalars(select(SessionEvent)).one()
    assert event.type == EVENT_MANUAL_START
    assert event.payload["code"] == "NO_ACTIVE_DEVICE"
    assert event.payload["spotify_code"] == "NO_ACTIVE_DEVICE"


@respx.mock
async def test_the_reason_survives_a_reload(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    """The screen is drawn from the row and its events, not from the Chime in answer."""
    mock_devices(empty=True)
    mock_create()
    mock_items()

    session = (await sessions.chime_in(db, user.id, count=5, spotify=spotify)).session

    manual = sessions.manual_start(db, session)
    assert manual is not None and manual.code == "NO_ACTIVE_DEVICE"


@respx.mock
async def test_a_restricted_device_is_not_a_device(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    respx.get(f"{API}/me/player/devices").mock(
        return_value=httpx.Response(
            200,
            json={
                "devices": [
                    {"id": "d9", "name": "Car", "type": "Computer", "is_restricted": True}
                ]
            },
        )
    )
    mock_create()
    mock_items()

    result = await sessions.chime_in(db, user.id, count=5, spotify=spotify)

    assert result.manual is not None and result.manual.code == "NO_ACTIVE_DEVICE"


@respx.mock
async def test_a_refused_play_keeps_the_playlist_so_spotify_can_start_it(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    """Premium cannot be checked for, so this is the only place it can be discovered.

    And it is exactly the case the playlist exists for: Chime cannot press play on a free
    account, but the user can.
    """
    mock_devices()
    mock_create()
    mock_items()
    respx.put(f"{API}/me/player/play").mock(
        return_value=httpx.Response(
            403,
            json={
                "error": {
                    "status": 403,
                    "message": "Player command failed: Premium required",
                    "reason": "PREMIUM_REQUIRED",
                }
            },
        )
    )
    removed = mock_remove()

    result = await sessions.chime_in(db, user.id, count=5, spotify=spotify)

    assert result.manual is not None and result.manual.code == "PREMIUM_REQUIRED"
    assert "Premium" in result.manual.message
    assert removed.call_count == 0
    session = db.scalars(select(Session)).one()
    assert session.status == STATUS_CREATED
    assert session.playlist_uri == "spotify:playlist:pl1"


@respx.mock
async def test_an_expired_login_still_takes_the_playlist_back(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    """The one refusal a link cannot rescue: with no login, nothing here works."""
    mock_devices()
    mock_create()
    mock_items()
    respx.put(f"{API}/me/player/play").mock(
        return_value=httpx.Response(401, json={"error": {"status": 401, "message": "expired"}})
    )
    removed = mock_remove()

    with pytest.raises(SpotifyAuthError):
        await sessions.chime_in(db, user.id, count=5, spotify=spotify)

    assert removed.call_count == 1
    session = db.scalars(select(Session)).one()
    assert session.status == STATUS_FAILED


@respx.mock
async def test_try_again_plays_a_waiting_session(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    """Spotify was closed at Chime in and is open now. No second playlist."""
    mock_devices(empty=True)
    create = mock_create()
    mock_items()
    session = (await sessions.chime_in(db, user.id, count=5, spotify=spotify)).session

    respx.get(f"{API}/me/player/devices").mock(
        return_value=httpx.Response(
            200,
            json={
                "devices": [
                    {
                        "id": "d1",
                        "name": "Phone",
                        "type": "Smartphone",
                        "is_active": True,
                        "is_restricted": False,
                    }
                ]
            },
        )
    )
    play = mock_play()

    result = await sessions.start_playback(db, user.id, session, spotify=spotify)

    assert result.device_name == "Phone"
    assert play.calls.last.request.read()
    assert create.call_count == 1  # the original playlist, reused
    assert session.status == STATUS_ACTIVE
    assert sessions.manual_start(db, session) is None


@respx.mock
async def test_try_again_records_why_it_failed_again(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    mock_devices(empty=True)
    mock_create()
    mock_items()
    session = (await sessions.chime_in(db, user.id, count=5, spotify=spotify)).session

    with pytest.raises(SpotifyNoActiveDeviceError):
        await sessions.start_playback(db, user.id, session, spotify=spotify)

    events = db.scalars(
        select(SessionEvent).where(SessionEvent.type == EVENT_MANUAL_START)
    ).all()
    assert len(events) == 2  # one from Chime in, one from the retry
    assert session.status == STATUS_CREATED


@respx.mock
async def test_playback_seen_on_our_playlist_starts_the_session(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    """Pressing play inside Spotify is only ever visible to us on the next poll.

    The promotion itself lives in ``app.services.playback`` — the evidence for it is a
    playback snapshot, so it belongs with the rest of the measuring — but it is the session
    engine's state machine being driven, which is why the test is here.
    """
    mock_devices(empty=True)
    mock_create()
    mock_items()
    session = (await sessions.chime_in(db, user.id, count=5, spotify=spotify)).session

    # Something else playing is not this session starting.
    playback.promote(db, session, context_uri="spotify:playlist:other")
    assert session.status == STATUS_CREATED

    playback.promote(db, session, context_uri="spotify:playlist:pl1")
    assert session.status == STATUS_ACTIVE
    assert sessions.manual_start(db, session) is None


@respx.mock
async def test_a_cleanup_that_fails_does_not_replace_the_real_error(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    mock_devices()
    mock_create()
    respx.post(f"{API}/playlists/pl1/items").mock(
        return_value=httpx.Response(403, json={"error": {"status": 403, "message": "nope"}})
    )
    mock_remove(status=403)

    with pytest.raises(Exception) as caught:
        await sessions.chime_in(db, user.id, count=5, spotify=spotify)

    assert "nope" in str(caught.value)
    assert db.scalars(select(Session)).one().status == STATUS_FAILED


@respx.mock
async def test_only_one_session_runs_at_a_time(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    live = await start(db, user, spotify, count=5)

    with pytest.raises(sessions.SessionAlreadyLiveError) as caught:
        await sessions.chime_in(db, user.id, count=5, spotify=spotify)

    assert caught.value.session.id == live.id


async def test_an_empty_library_never_reaches_spotify(
    db: DbSession, user: User, spotify: SpotifyClient
) -> None:
    """No respx mock at all: any outbound call here would fail the test."""
    with pytest.raises(sessions.NoTracksError):
        await sessions.chime_in(db, user.id, spotify=spotify)

    assert db.scalars(select(Session)).all() == []


async def test_a_nonsense_mood_is_refused_before_anything_happens(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    with pytest.raises(sessions.SessionError):
        await sessions.chime_in(db, user.id, mood="peckish", spotify=spotify)

    assert db.scalars(select(Session)).all() == []


# ---------------------------------------------------------------- stale session


def stale_session(db: DbSession, user: User, *, hours: int) -> Session:
    session = Session(
        user_id=user.id,
        status=STATUS_ACTIVE,
        type="focus",
        intent="match",
        started_at=utcnow() - timedelta(hours=hours),
        playlist_uri="spotify:playlist:old",
    )
    db.add(session)
    db.commit()
    return session


def test_a_session_left_running_overnight_is_closed_as_ended(
    db: DbSession, user: User
) -> None:
    """A crash mid-session must not block every future Chime in."""
    session = stale_session(db, user, hours=sessions.STALE_SESSION_HOURS + 1)

    assert sessions.active_session(db, user.id) is None

    db.refresh(session)
    assert session.status == STATUS_ENDED  # it did run, so ended and not failed
    assert session.ended_at is not None
    assert session.summary == {"abandoned": True}
    # The playlist is deliberately left alone: nobody asked us to tidy it up hours later.
    assert session.playlist_removed_at is None


def test_a_session_still_inside_the_window_stays_live(db: DbSession, user: User) -> None:
    session = stale_session(db, user, hours=sessions.STALE_SESSION_HOURS - 1)

    live = sessions.active_session(db, user.id)

    assert live is not None and live.id == session.id


@respx.mock
async def test_chime_in_works_again_after_an_abandoned_session(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    stale_session(db, user, hours=sessions.STALE_SESSION_HOURS + 1)

    session = await start(db, user, spotify, count=5)

    assert session.status == STATUS_ACTIVE


# ------------------------------------------------------------------ mood check


@respx.mock
async def test_a_mid_session_mood_check_is_recorded(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    session = await start(db, user, spotify, count=5)

    sessions.record_mood(db, session, "wired")

    event = db.scalars(select(SessionEvent)).one()
    assert event.type == EVENT_MOOD_CHECK
    assert event.payload == {"mood": "wired"}
    # mood_in is what the session started as; a re-check does not rewrite history.
    assert session.mood_in is None


@respx.mock
async def test_a_mood_check_on_a_finished_session_is_refused(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    session = await start(db, user, spotify, count=5)
    mock_remove()
    respx.put(f"{API}/me/player/pause").mock(return_value=httpx.Response(204))
    await sessions.chime_out(db, user.id, session, spotify=spotify)

    with pytest.raises(sessions.SessionError):
        sessions.record_mood(db, session, "steady")


# -------------------------------------------------------------------- chime out


@respx.mock
async def test_chime_out_removes_the_playlist_by_default(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    session = await start(db, user, spotify, count=6)
    pause = respx.put(f"{API}/me/player/pause").mock(return_value=httpx.Response(204))
    removed = mock_remove()

    ended = await sessions.chime_out(db, user.id, session, mood_out="steady", spotify=spotify)

    assert pause.call_count == 1
    assert removed.call_count == 1
    assert removed.calls.last.request.url.path == "/v1/playlists/pl1/followers"
    # And the library was asked whether that worked, rather than the 200 being taken on faith.
    checked = [call for call in respx.calls if call.request.url.path.endswith("/library/contains")]
    assert checked and checked[-1].request.url.params["uris"] == "spotify:playlist:pl1"
    assert ended.status == STATUS_ENDED
    assert ended.kept is False
    assert ended.mood_out == "steady"
    assert ended.ended_at is not None
    assert ended.playlist_removed_at is not None
    assert ended.body_out is not None


@respx.mock
async def test_the_summary_says_unmeasured_rather_than_nothing_played(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    """Only the phase 6 poller fills these in, and zero would be a lie until it does."""
    session = await start(db, user, spotify, count=6)
    respx.put(f"{API}/me/player/pause").mock(return_value=httpx.Response(204))
    mock_remove()

    ended = await sessions.chime_out(db, user.id, session, spotify=spotify)

    assert ended.summary is not None
    assert ended.summary["queued"] == 6
    assert ended.summary["played"] is None
    assert ended.summary["skipped"] is None
    assert ended.summary["skip_rate"] is None
    assert ended.summary["minutes"] >= 0


@respx.mock
async def test_a_kept_session_renames_the_playlist_instead(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    session = await start(db, user, spotify, count=6)
    respx.put(f"{API}/me/player/pause").mock(return_value=httpx.Response(204))
    rename = respx.put(f"{API}/playlists/pl1").mock(return_value=httpx.Response(200))
    removed = mock_remove()

    ended = await sessions.chime_out(db, user.id, session, keep=True, spotify=spotify)

    assert rename.call_count == 1
    assert removed.call_count == 0
    assert ended.kept is True
    assert ended.playlist_removed_at is None
    # Dropping the "Chime ·" prefix: once it is theirs it is a playlist, not a session.
    assert not ended.playlist_name.startswith("Chime")


@respx.mock
async def test_a_kept_session_can_be_given_a_name(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    session = await start(db, user, spotify, count=6)
    respx.put(f"{API}/me/player/pause").mock(return_value=httpx.Response(204))
    rename = respx.put(f"{API}/playlists/pl1").mock(return_value=httpx.Response(200))

    ended = await sessions.chime_out(
        db, user.id, session, keep=True, name="  Tuesday mornings  ", spotify=spotify
    )

    assert json.loads(rename.calls.last.request.content)["name"] == "Tuesday mornings"
    assert ended.playlist_name == "Tuesday mornings"


@respx.mock
async def test_a_playlist_we_could_not_remove_is_an_apology_not_a_failure(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    """Being unable to tidy up must not trap someone in a session they have finished."""
    session = await start(db, user, spotify, count=6)
    respx.put(f"{API}/me/player/pause").mock(return_value=httpx.Response(204))
    mock_remove(status=403)

    ended = await sessions.chime_out(db, user.id, session, spotify=spotify)

    assert ended.status == STATUS_ENDED
    assert ended.playlist_removed_at is None
    assert ended.summary is not None
    assert ended.summary["problems"] == [
        "We couldn't remove the playlist from Spotify. You can delete it yourself."
    ]


@respx.mock
async def test_a_removal_that_removed_nothing_is_not_reported_as_removed(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    """The bug this phase found, pinned: a 200 is not evidence the playlist went away.

    Two real sessions recorded ``playlist_removed_at`` while the playlists sat in the
    library, so the removal is now believed only when the library agrees.
    """
    session = await start(db, user, spotify, count=6)
    respx.put(f"{API}/me/player/pause").mock(return_value=httpx.Response(204))
    mock_remove(still_there=True)

    ended = await sessions.chime_out(db, user.id, session, spotify=spotify)

    assert ended.status == STATUS_ENDED
    assert ended.playlist_removed_at is None
    assert ended.summary is not None
    assert ended.summary["problems"] == [
        "Spotify still has the playlist in your library. You can remove it there."
    ]


@respx.mock
async def test_a_removal_we_cannot_confirm_is_believed(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    """Failing to *check* is not failing to remove: the 200 stands, and nobody is nagged."""
    session = await start(db, user, spotify, count=6)
    respx.put(f"{API}/me/player/pause").mock(return_value=httpx.Response(204))
    respx.delete(f"{API}/playlists/pl1/followers").mock(return_value=httpx.Response(200))
    respx.get(f"{API}/me/library/contains").mock(
        return_value=httpx.Response(500, json={"error": {"status": 500, "message": "oops"}})
    )

    ended = await sessions.chime_out(db, user.id, session, spotify=spotify)

    assert ended.playlist_removed_at is not None
    assert ended.summary is not None
    assert "problems" not in ended.summary


@respx.mock
async def test_a_kept_playlist_we_could_not_rename_is_still_kept(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    session = await start(db, user, spotify, count=6)
    respx.put(f"{API}/me/player/pause").mock(return_value=httpx.Response(204))
    respx.put(f"{API}/playlists/pl1").mock(
        return_value=httpx.Response(403, json={"error": {"status": 403, "message": "nope"}})
    )

    ended = await sessions.chime_out(db, user.id, session, keep=True, spotify=spotify)

    assert ended.kept is True
    assert ended.status == STATUS_ENDED
    assert ended.summary is not None
    assert ended.summary["problems"] == ["We kept the playlist but couldn't rename it."]


@respx.mock
async def test_nothing_playing_to_pause_is_not_a_problem(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    session = await start(db, user, spotify, count=6)
    respx.put(f"{API}/me/player/pause").mock(
        return_value=httpx.Response(
            403,
            json={
                "error": {
                    "status": 403,
                    "message": "Restriction violated",
                    "reason": "UNKNOWN",
                }
            },
        )
    )
    mock_remove()

    ended = await sessions.chime_out(db, user.id, session, spotify=spotify)

    assert ended.status == STATUS_ENDED
    assert ended.summary is not None
    assert "problems" not in ended.summary


@respx.mock
async def test_chime_out_can_leave_the_music_playing(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    session = await start(db, user, spotify, count=6)
    pause = respx.put(f"{API}/me/player/pause")
    mock_remove()

    await sessions.chime_out(db, user.id, session, pause=False, spotify=spotify)

    assert pause.call_count == 0


@respx.mock
async def test_chime_out_twice_is_refused(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    session = await start(db, user, spotify, count=6)
    respx.put(f"{API}/me/player/pause").mock(return_value=httpx.Response(204))
    mock_remove()
    await sessions.chime_out(db, user.id, session, spotify=spotify)

    with pytest.raises(sessions.SessionError):
        await sessions.chime_out(db, user.id, session, spotify=spotify)


@respx.mock
async def test_an_unknown_mood_out_is_refused_before_anything_is_touched(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    session = await start(db, user, spotify, count=6)
    pause = respx.put(f"{API}/me/player/pause")

    with pytest.raises(sessions.SessionError):
        await sessions.chime_out(db, user.id, session, mood_out="peckish", spotify=spotify)

    assert pause.call_count == 0
    assert session.status == STATUS_ACTIVE


# ------------------------------------------------------------------ freshness


@respx.mock
async def test_recent_tracks_are_remembered_for_freshness(
    db: DbSession, user: User, library: None, spotify: SpotifyClient
) -> None:
    session = await start(db, user, spotify, count=6)

    recent = sessions.recent_track_ids(db, user.id)

    used = db.scalars(
        select(SessionTrack.track_id).where(SessionTrack.session_id == session.id)
    ).all()
    assert recent == set(used)


def test_freshness_only_looks_at_the_last_few_sessions(db: DbSession, user: User) -> None:
    for index in range(sessions.FRESHNESS_SESSIONS + 2):
        db.add(
            Session(
                user_id=user.id,
                status=STATUS_ENDED,
                type="focus",
                intent="match",
                started_at=utcnow() - timedelta(hours=index + 1),
            )
        )
    db.commit()
    rows = db.scalars(select(Session).order_by(Session.started_at.desc())).all()
    track = Track(spotify_track_id="old", name="Old", duration_ms=1000)
    db.add(track)
    db.flush()
    # Only on the oldest session, which is outside the window.
    db.add(SessionTrack(session_id=rows[-1].id, position=0, track_id=track.id))
    db.commit()

    assert sessions.recent_track_ids(db, user.id) == set()


# -------------------------------------------------------------------- wording


def test_a_session_playlist_is_named_for_its_type_and_the_time(
    db: DbSession, user: User
) -> None:
    session = stale_session(db, user, hours=0)
    session.type = "wind_down"

    name = sessions.playlist_name(db, session)

    assert name.startswith("Chime · Wind down · ")
    assert name.endswith(("am", "pm"))
    assert " 0" not in name  # no leading zero on the hour


def test_a_users_own_sessions_are_the_only_ones_they_can_read(
    db: DbSession, user: User
) -> None:
    other = User(spotify_account_id="acc_other", spotify_user_id="other")
    db.add(other)
    db.commit()
    theirs = stale_session(db, other, hours=0)

    assert sessions.get_session(db, user.id, theirs.id) is None
    assert sessions.get_session(db, other.id, theirs.id) is not None
