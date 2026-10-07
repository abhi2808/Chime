"""History: the list, the week summary, the timeline, bringing a session back, forgetting it.

What is worth pinning here is mostly about honesty. A session that failed played nothing and
does not belong in a record of what you listened to. Minutes come off the stored summary, so
an old session reads the same today as it did the day it ended. Counts that nothing has
measured yet stay null instead of becoming zero. A playlist Chime out removed does not get
offered as a link. And "bring it back" builds a *new* playlist without touching the row that
says which one the session originally made.
"""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DbSession

from app.core.clock import utcnow
from app.core.config import settings
from app.core.cookies import dumps
from app.core.crypto import encrypt
from app.integrations.spotify import auth as spotify_auth
from app.models import (
    EVENT_MOOD_CHECK,
    EVENT_RESTORE,
    STATUS_ACTIVE,
    STATUS_ENDED,
    STATUS_FAILED,
    OAuthToken,
    Session,
    SessionEvent,
    SessionTrack,
    Track,
    User,
)
from app.services import history

API = "https://api.spotify.com/v1"


@pytest.fixture
def signed_in(client: TestClient, db: DbSession, user: User) -> User:
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
    client.cookies.set(settings.session_cookie_name, dumps("chime.session", {"uid": user.id}))
    return user


def make_session(
    db: DbSession,
    user: User,
    *,
    status: str = STATUS_ENDED,
    session_type: str = "focus",
    mood_in: str | None = "flat",
    mood_out: str | None = None,
    hours_ago: float = 1.0,
    minutes: float | None = 42.0,
    kept: bool = False,
    playlist: str | None = "spotify:playlist:pl1",
    removed: bool = False,
    tracks: int = 0,
    images: list[str] | None = None,
) -> Session:
    started = utcnow() - timedelta(hours=hours_ago)
    session = Session(
        user_id=user.id,
        status=status,
        type=session_type,
        intent="match",
        mood_in=mood_in,
        mood_out=mood_out,
        started_at=started,
        ended_at=started + timedelta(minutes=30) if status == STATUS_ENDED else None,
        playlist_uri=playlist,
        playlist_name="Chime · Focus · 9:20 am",
        kept=kept,
        playlist_removed_at=utcnow() if removed else None,
        summary={"minutes": minutes, "queued": tracks} if minutes is not None else None,
    )
    db.add(session)
    db.flush()
    for position in range(tracks):
        track = Track(
            spotify_track_id=f"t{session.id}-{position}",
            name=f"track {position}",
            artist_ids=["a1"],
            artist_names=["artist one"],
            album_name="An album",
            image_url=(images[position] if images and position < len(images) else None),
            duration_ms=200_000,
        )
        db.add(track)
        db.flush()
        db.add(
            SessionTrack(session_id=session.id, position=position, track_id=track.id)
        )
    db.commit()
    return session


# ------------------------------------------------------------------------ the list


def test_sessions_come_back_newest_first(client: TestClient, signed_in: User, db: DbSession) -> None:
    old = make_session(db, signed_in, hours_ago=48)
    new = make_session(db, signed_in, hours_ago=1)

    body = client.get("/api/sessions").json()

    assert [row["id"] for row in body["sessions"]] == [new.id, old.id]
    assert body["total"] == 2


def test_a_failed_session_is_left_out_unless_asked_for(
    client: TestClient, signed_in: User, db: DbSession
) -> None:
    """It played nothing, so it is noise in a record of what you listened to."""
    make_session(db, signed_in)
    failed = make_session(db, signed_in, status=STATUS_FAILED, playlist=None, minutes=None)

    assert failed.id not in [row["id"] for row in client.get("/api/sessions").json()["sessions"]]

    body = client.get("/api/sessions?include_failed=true").json()
    assert failed.id in [row["id"] for row in body["sessions"]]


def test_each_filter_narrows_the_list(
    client: TestClient, signed_in: User, db: DbSession
) -> None:
    focus = make_session(db, signed_in, session_type="focus", mood_in="flat", kept=True)
    workout = make_session(db, signed_in, session_type="workout", mood_in="wired")

    by_type = client.get("/api/sessions?type=workout").json()
    assert [row["id"] for row in by_type["sessions"]] == [workout.id]

    by_mood = client.get("/api/sessions?mood_in=flat").json()
    assert [row["id"] for row in by_mood["sessions"]] == [focus.id]

    kept_only = client.get("/api/sessions?kept=true").json()
    assert [row["id"] for row in kept_only["sessions"]] == [focus.id]


def test_a_date_range_includes_its_last_day(
    client: TestClient, signed_in: User, db: DbSession
) -> None:
    """``to`` is inclusive: a filter that quietly dropped today would be worse than one
    that is a few hours generous at the edges."""
    today = make_session(db, signed_in, hours_ago=0.5)
    last_week = make_session(db, signed_in, hours_ago=24 * 8)
    day = utcnow().date().isoformat()

    body = client.get(f"/api/sessions?from={day}&to={day}").json()

    assert [row["id"] for row in body["sessions"]] == [today.id]
    assert last_week.id not in [row["id"] for row in body["sessions"]]


def test_paging_reports_the_whole_filtered_count(
    client: TestClient, signed_in: User, db: DbSession
) -> None:
    for index in range(5):
        make_session(db, signed_in, hours_ago=index + 1)

    first = client.get("/api/sessions?limit=2").json()
    second = client.get("/api/sessions?limit=2&offset=2").json()

    assert len(first["sessions"]) == 2
    assert first["total"] == 5
    assert second["total"] == 5
    # No overlap, so "load more" cannot show the same card twice.
    assert not {row["id"] for row in first["sessions"]} & {row["id"] for row in second["sessions"]}


def test_a_card_carries_its_count_and_a_few_covers(
    client: TestClient, signed_in: User, db: DbSession
) -> None:
    """Four *different* covers. Four copies of one would read as a rendering bug."""
    make_session(
        db,
        signed_in,
        tracks=6,
        images=["https://i/1", "https://i/1", "https://i/2", "https://i/3", "https://i/4", None],
    )

    row = client.get("/api/sessions").json()["sessions"][0]

    assert row["queued"] == 6
    assert row["images"] == ["https://i/1", "https://i/2", "https://i/3", "https://i/4"]


def test_unmeasured_counts_stay_null(client: TestClient, signed_in: User, db: DbSession) -> None:
    """Nothing measures played and skipped until phase 6, and zero would be a lie."""
    make_session(db, signed_in, tracks=3)

    row = client.get("/api/sessions").json()["sessions"][0]

    assert row["minutes"] == 42.0
    assert row["played"] is None
    assert row["skipped"] is None


def test_a_removed_playlist_is_not_offered_as_a_link(
    client: TestClient, signed_in: User, db: DbSession
) -> None:
    make_session(db, signed_in, removed=True)

    row = client.get("/api/sessions").json()["sessions"][0]

    assert row["playlist_url"] is None


def test_a_live_session_is_measured_against_the_clock(
    signed_in: User, db: DbSession
) -> None:
    """It has no summary yet, so the stored minutes cannot be the answer."""
    session = make_session(db, signed_in, status=STATUS_ACTIVE, hours_ago=0.5, minutes=None)

    assert 25 <= history.minutes_of(session) <= 35


def test_the_list_is_per_user(client: TestClient, signed_in: User, db: DbSession) -> None:
    stranger = User(spotify_account_id="acc_other", spotify_user_id="other", display_name="Other")
    db.add(stranger)
    db.commit()
    theirs = make_session(db, stranger)
    mine = make_session(db, signed_in)

    body = client.get("/api/sessions").json()

    assert [row["id"] for row in body["sessions"]] == [mine.id]
    assert client.get(f"/api/sessions/{theirs.id}").status_code == 404


def test_history_needs_a_signed_in_user(client: TestClient) -> None:
    assert client.get("/api/sessions").status_code == 401
    assert client.get("/api/sessions/week").status_code == 401


# ------------------------------------------------------------------ week summary


def test_an_empty_week_says_so_rather_than_showing_zeroes(
    client: TestClient, signed_in: User
) -> None:
    body = client.get("/api/sessions/week").json()

    assert body["sessions"] == 0
    assert body["note"] == "Nothing in the last 7 days."


def test_the_week_counts_sessions_and_minutes(
    client: TestClient, signed_in: User, db: DbSession
) -> None:
    make_session(db, signed_in, minutes=30.0, mood_in="flat", mood_out="steady")
    make_session(db, signed_in, minutes=12.5, mood_in="flat", mood_out="steady")
    make_session(db, signed_in, hours_ago=24 * 9, minutes=99.0)

    body = client.get("/api/sessions/week").json()

    assert body["sessions"] == 2
    assert body["minutes"] == 42.5
    assert (body["shift_from"], body["shift_to"], body["shift_count"]) == ("flat", "steady", 2)


def test_a_week_with_no_second_mood_explains_itself(
    client: TestClient, signed_in: User, db: DbSession
) -> None:
    """"No shift" would read as "you did not change", which is not what the data says."""
    make_session(db, signed_in, mood_in="wired", mood_out=None)

    body = client.get("/api/sessions/week").json()

    assert body["sessions"] == 1
    assert body["shift_from"] is None
    assert "did not record both ends" in body["note"]


def test_a_failed_session_does_not_count_towards_the_week(
    client: TestClient, signed_in: User, db: DbSession
) -> None:
    make_session(db, signed_in, status=STATUS_FAILED, minutes=None, playlist=None)

    assert client.get("/api/sessions/week").json()["sessions"] == 0


def test_week_beats_the_id_route(client: TestClient, signed_in: User) -> None:
    """``/week`` is declared before ``/{session_id}``; without that it is parsed as an id."""
    assert client.get("/api/sessions/week").status_code == 200


# ---------------------------------------------------------------------- detail


def test_the_detail_page_carries_the_timeline(
    client: TestClient, signed_in: User, db: DbSession
) -> None:
    session = make_session(db, signed_in, tracks=2)
    db.add(
        SessionEvent(session_id=session.id, type=EVENT_MOOD_CHECK, payload={"mood": "steady"})
    )
    db.commit()

    body = client.get(f"/api/sessions/{session.id}").json()

    assert [event["type"] for event in body["events"]] == [EVENT_MOOD_CHECK]
    assert body["events"][0]["payload"] == {"mood": "steady"}
    assert len(body["tracks"]) == 2


def test_the_live_session_is_not_charged_for_the_timeline(
    client: TestClient, signed_in: User, db: DbSession
) -> None:
    """``/active`` polls every few seconds and draws none of it."""
    session = make_session(db, signed_in, status=STATUS_ACTIVE, minutes=None)
    db.add(SessionEvent(session_id=session.id, type=EVENT_MOOD_CHECK, payload={"mood": "flat"}))
    db.commit()

    with respx.mock:
        respx.get(f"{API}/me/player").mock(return_value=httpx.Response(204))
        body = client.get("/api/sessions/active").json()

    assert body["session"]["events"] == []


# ------------------------------------------------------------- bring it back


def mock_new_playlist(playlist_id: str = "pl9") -> respx.Route:
    """Creating and filling a playlist. Returns the route the track URIs go through."""
    respx.post(f"{API}/me/playlists").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": playlist_id,
                "uri": f"spotify:playlist:{playlist_id}",
                "name": "Chime · Focus · 9:20 am",
                "public": False,
            },
        )
    )
    return respx.post(f"{API}/playlists/{playlist_id}/items").mock(
        return_value=httpx.Response(201, json={"snapshot_id": "snap"})
    )


@respx.mock
def test_bringing_a_session_back_rebuilds_it_from_our_own_rows(
    client: TestClient, signed_in: User, db: DbSession
) -> None:
    """The original playlist is gone from Spotify; ``session_tracks`` is the record."""
    session = make_session(db, signed_in, tracks=3, removed=True)
    items = mock_new_playlist()

    response = client.post(f"/api/sessions/{session.id}/restore")

    assert response.status_code == 200
    body = response.json()
    assert body["playlist_url"] == "https://open.spotify.com/playlist/pl9"
    assert body["tracks"] == 3
    sent = items.calls.last.request
    assert b"spotify:track:t" in sent.content


@respx.mock
def test_bringing_it_back_leaves_the_original_uri_alone(
    client: TestClient, signed_in: User, db: DbSession
) -> None:
    """``playlist_uri`` names the playlist the session made, which is a fact about what
    happened, not a stale value. The new one rides on an event."""
    session = make_session(db, signed_in, tracks=2, removed=True)
    mock_new_playlist()

    client.post(f"/api/sessions/{session.id}/restore")

    db.expire_all()
    reloaded = db.get(Session, session.id)
    assert reloaded is not None
    assert reloaded.playlist_uri == "spotify:playlist:pl1"
    assert [event.type for event in reloaded.events] == [EVENT_RESTORE]
    assert reloaded.events[0].payload["playlist_id"] == "pl9"


@respx.mock
def test_a_brought_back_session_says_where_the_new_playlist_is(
    client: TestClient, signed_in: User, db: DbSession
) -> None:
    session = make_session(db, signed_in, tracks=2, removed=True)
    mock_new_playlist()
    client.post(f"/api/sessions/{session.id}/restore")

    body = client.get(f"/api/sessions/{session.id}").json()

    assert body["restored_playlist_url"] == "https://open.spotify.com/playlist/pl9"
    # The one it originally made is still gone, so it is still not a link.
    assert body["playlist_url"] is None


@respx.mock
def test_bringing_it_back_twice_reports_the_newer_playlist(
    client: TestClient, signed_in: User, db: DbSession
) -> None:
    session = make_session(db, signed_in, tracks=1, removed=True)
    mock_new_playlist("pl9")
    client.post(f"/api/sessions/{session.id}/restore")
    respx.reset()
    mock_new_playlist("pl10")

    client.post(f"/api/sessions/{session.id}/restore")

    body = client.get(f"/api/sessions/{session.id}").json()
    assert body["restored_playlist_url"] == "https://open.spotify.com/playlist/pl10"


def test_a_session_with_no_songs_cannot_be_brought_back(
    client: TestClient, signed_in: User, db: DbSession
) -> None:
    session = make_session(db, signed_in, tracks=0)

    response = client.post(f"/api/sessions/{session.id}/restore")

    assert response.status_code == 409
    assert "nothing to rebuild" in response.json()["detail"]


@respx.mock
def test_a_stale_login_asks_for_a_sign_in_rather_than_failing_quietly(
    client: TestClient, signed_in: User, db: DbSession
) -> None:
    session = make_session(db, signed_in, tracks=1)
    respx.post(f"{API}/me/playlists").mock(
        return_value=httpx.Response(401, json={"error": {"status": 401, "message": "expired"}})
    )
    respx.post("https://accounts.spotify.com/api/token").mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )

    response = client.post(f"/api/sessions/{session.id}/restore")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "REAUTH"


# ------------------------------------------------------------------- forgetting


def test_forgetting_a_session_takes_its_tracks_and_timeline_with_it(
    client: TestClient, signed_in: User, db: DbSession
) -> None:
    session = make_session(db, signed_in, tracks=3)
    db.add(SessionEvent(session_id=session.id, type=EVENT_MOOD_CHECK, payload={"mood": "flat"}))
    db.commit()

    session_id = session.id

    assert client.delete(f"/api/sessions/{session_id}").status_code == 204

    # Expunged rather than expired: this test's own session still holds the deleted row, and
    # asking it to refresh one is an error rather than an answer.
    db.expunge_all()
    assert db.get(Session, session_id) is None
    assert db.query(SessionTrack).filter_by(session_id=session_id).count() == 0
    assert db.query(SessionEvent).filter_by(session_id=session_id).count() == 0


@respx.mock
def test_forgetting_a_session_does_not_touch_spotify(
    client: TestClient, signed_in: User, db: DbSession
) -> None:
    """A kept playlist belongs to the user now. Deleting our record is not permission to
    reach into their library."""
    session = make_session(db, signed_in, tracks=1, kept=True)
    # Both routes to getting rid of a playlist, so this stays true whichever one the
    # engine uses.
    library = respx.delete(f"{API}/me/library").mock(return_value=httpx.Response(200))
    unfollowed = respx.delete(url__regex=rf"{API}/playlists/.+/followers").mock(
        return_value=httpx.Response(200)
    )

    assert client.delete(f"/api/sessions/{session.id}").status_code == 204
    assert library.call_count == 0
    assert unfollowed.call_count == 0


def test_a_running_session_cannot_be_forgotten(
    client: TestClient, signed_in: User, db: DbSession
) -> None:
    session = make_session(db, signed_in, status=STATUS_ACTIVE, minutes=None)

    response = client.delete(f"/api/sessions/{session.id}")

    assert response.status_code == 409
    assert "Chime out first" in response.json()["detail"]


def test_forgetting_someone_elses_session_is_a_404(
    client: TestClient, signed_in: User, db: DbSession
) -> None:
    stranger = User(spotify_account_id="acc_x", spotify_user_id="x", display_name="X")
    db.add(stranger)
    db.commit()
    theirs = make_session(db, stranger)

    assert client.delete(f"/api/sessions/{theirs.id}").status_code == 404
    db.expire_all()
    assert db.get(Session, theirs.id) is not None
