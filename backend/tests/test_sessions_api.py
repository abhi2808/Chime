"""The session endpoints (SPEC section 7).

The service tests cover what happens; these cover what the screens are told about it. The
part worth pinning is what a screen has to do about an answer: the two refusals we cannot
check for in advance (no open Spotify, no Premium) come back as a *created* session with
`needs_manual_start` and a playlist to open, not as an error, and a session is a database
fact that must stay readable even when playback cannot be read at all.
"""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DbSession

from app.api.routes.sessions import NOT_PLAYING, PLAYBACK_UNREADABLE
from app.core.clock import utcnow
from app.core.config import settings
from app.core.cookies import dumps
from app.core.crypto import encrypt
from app.integrations.spotify import auth as spotify_auth
from app.models import OAuthToken, Track, TrackTag, User, UserTrack

API = "https://api.spotify.com/v1"
PLAYLIST = {
    "id": "pl1",
    "uri": "spotify:playlist:pl1",
    "name": "Chime · Focus · 9:20 am",
    "public": False,
}


@pytest.fixture
def signed_in(client: TestClient, db: DbSession, user: User) -> User:
    """A user with a cookie and a live Spotify token, which every route here needs."""
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


@pytest.fixture
def library(db: DbSession, user: User) -> None:
    for index in range(20):
        track = Track(
            spotify_track_id=f"s{index}",
            name=f"track {index}",
            artist_ids=[f"a{index % 5}"],
            artist_names=[f"artist {index % 5}"],
            album_name="An album",
            image_url="https://i.scdn.co/big",
            duration_ms=200_000,
        )
        db.add(track)
        db.flush()
        db.add(UserTrack(user_id=user.id, track_id=track.id, source="liked"))
        db.add(
            TrackTag(
                track_id=track.id,
                energy=1.0 + (index % 5),
                affinities={"focus": 0.7},
                confidence=0.8,
                source="external",
                raw_tags=[["ambient", 1.0]],
            )
        )
    db.commit()


def mock_happy_path() -> None:
    respx.get(f"{API}/me/player/devices").mock(
        return_value=httpx.Response(
            200,
            json={
                "devices": [
                    {"id": "d1", "name": "Laptop", "type": "Computer", "is_active": True}
                ]
            },
        )
    )
    respx.post(f"{API}/me/playlists").mock(return_value=httpx.Response(201, json=PLAYLIST))
    respx.post(f"{API}/playlists/pl1/items").mock(
        return_value=httpx.Response(201, json={"snapshot_id": "snap1"})
    )
    respx.put(f"{API}/me/player/play").mock(return_value=httpx.Response(204))


def mock_remove(*, still_there: bool = False) -> respx.Route:
    """Chime out's removal: unfollow the playlist, then confirm the library agrees."""
    route = respx.delete(f"{API}/playlists/pl1/followers").mock(
        return_value=httpx.Response(200)
    )
    respx.get(f"{API}/me/library/contains").mock(
        return_value=httpx.Response(200, json=[still_there])
    )
    return route


def chime_in(client: TestClient, **payload: object) -> httpx.Response:
    return client.post("/api/sessions", json={"count": 6, **payload})


# --------------------------------------------------------------------- chime in


def test_chiming_in_needs_a_signed_in_user(client: TestClient) -> None:
    assert client.post("/api/sessions", json={}).status_code == 401


@respx.mock
def test_chime_in_answers_with_everything_the_session_screen_draws(
    client: TestClient, signed_in: User, library: None
) -> None:
    mock_happy_path()

    response = chime_in(client, mood="flat")

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "active"
    assert body["mood_in"] == "flat"
    assert body["playlist_uri"] == "spotify:playlist:pl1"
    assert body["playlist_url"] == "https://open.spotify.com/playlist/pl1"
    assert body["device_name"] == "Laptop"
    assert body["why_text"]
    assert body["profile"]["curve"]
    assert body["kept"] is False
    assert body["summary"] is None
    assert len(body["tracks"]) == 6

    first = body["tracks"][0]
    assert first["position"] == 0
    assert first["name"]
    assert first["artists"]
    assert first["image_url"] == "https://i.scdn.co/big"
    assert first["energy"] is not None
    assert first["target"] == body["profile"]["curve"][0]
    assert first["started_at"] is None  # measured in phase 6, not now


@respx.mock
def test_no_open_spotify_hands_over_the_playlist_instead(
    client: TestClient, signed_in: User, library: None
) -> None:
    """201, not an error: the mix exists and there is a link to press play on."""
    mock_happy_path()
    respx.get(f"{API}/me/player/devices").mock(
        return_value=httpx.Response(200, json={"devices": []})
    )

    response = chime_in(client)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "created"
    assert body["needs_manual_start"] is True
    assert body["manual_start_code"] == "NO_ACTIVE_DEVICE"
    assert "playlist" in body["manual_start_reason"]
    assert body["playlist_url"] == "https://open.spotify.com/playlist/pl1"
    assert body["device_name"] is None
    assert len(body["tracks"]) == 6


@respx.mock
def test_a_waiting_session_can_be_started_once_spotify_is_open(
    client: TestClient, signed_in: User, library: None
) -> None:
    mock_happy_path()
    devices = respx.get(f"{API}/me/player/devices").mock(
        return_value=httpx.Response(200, json={"devices": []})
    )
    session_id = chime_in(client).json()["id"]

    devices.mock(
        return_value=httpx.Response(
            200,
            json={
                "devices": [
                    {"id": "d1", "name": "Laptop", "type": "Computer", "is_active": True}
                ]
            },
        )
    )

    response = client.post(f"/api/sessions/{session_id}/start")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "active"
    assert body["needs_manual_start"] is False
    assert body["device_name"] == "Laptop"


@respx.mock
def test_trying_again_with_spotify_still_shut_says_so(
    client: TestClient, signed_in: User, library: None
) -> None:
    mock_happy_path()
    respx.get(f"{API}/me/player/devices").mock(
        return_value=httpx.Response(200, json={"devices": []})
    )
    session_id = chime_in(client).json()["id"]

    response = client.post(f"/api/sessions/{session_id}/start")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "NO_ACTIVE_DEVICE"
    assert "Open Spotify" in detail["message"]


@respx.mock
def test_pressing_play_in_spotify_makes_the_session_active(
    client: TestClient, signed_in: User, library: None
) -> None:
    """The poll behind the session screen is where a hand-started session is noticed."""
    mock_happy_path()
    respx.get(f"{API}/me/player/devices").mock(
        return_value=httpx.Response(200, json={"devices": []})
    )
    chime_in(client)

    respx.get(f"{API}/me/player").mock(
        return_value=httpx.Response(
            200,
            json={
                "is_playing": True,
                "progress_ms": 1000,
                "context": {"uri": "spotify:playlist:pl1", "type": "playlist"},
                "item": {
                    "id": "s1",
                    "name": "track 1",
                    "duration_ms": 200_000,
                    "artists": [{"id": "a1", "name": "artist 1"}],
                    "album": {"name": "An album", "images": []},
                },
                "device": {"id": "d1", "name": "Phone", "type": "Smartphone"},
            },
        )
    )

    body = client.get("/api/sessions/active").json()

    assert body["session"]["status"] == "active"
    assert body["session"]["needs_manual_start"] is False
    assert body["playing"]["is_playing"] is True


@respx.mock
def test_a_non_premium_account_is_told_what_happened(
    client: TestClient, signed_in: User, library: None
) -> None:
    """``GET /me`` no longer says who has Premium, so this is where it surfaces."""
    mock_happy_path()
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

    response = chime_in(client)

    assert response.status_code == 201
    body = response.json()
    assert body["needs_manual_start"] is True
    assert body["manual_start_code"] == "PREMIUM_REQUIRED"
    assert "Premium" in body["manual_start_reason"]
    # The playlist is the whole point on a free account, so it stays.
    assert removed.call_count == 0
    assert body["playlist_url"] == "https://open.spotify.com/playlist/pl1"


def test_an_unsynced_library_says_so(client: TestClient, signed_in: User) -> None:
    response = chime_in(client)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "NO_TRACKS"


@respx.mock
def test_a_second_chime_in_points_at_the_session_already_running(
    client: TestClient, signed_in: User, library: None
) -> None:
    mock_happy_path()
    first = chime_in(client).json()

    response = chime_in(client)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "SESSION_ACTIVE"
    assert detail["session_id"] == first["id"]


@respx.mock
def test_an_unknown_mood_is_a_bad_request(
    client: TestClient, signed_in: User, library: None
) -> None:
    response = chime_in(client, mood="peckish")

    assert response.status_code == 400
    assert "peckish" in response.json()["detail"]


# ----------------------------------------------------------------- active session


def test_no_active_session_is_nulls_not_a_404(client: TestClient, signed_in: User) -> None:
    body = client.get("/api/sessions/active").json()

    assert body == {"session": None, "playing": None, "note": None}


@respx.mock
def test_the_active_session_comes_back_with_what_is_playing(
    client: TestClient, signed_in: User, library: None
) -> None:
    mock_happy_path()
    chime_in(client)
    respx.get(f"{API}/me/player").mock(
        return_value=httpx.Response(
            200,
            json={
                "is_playing": True,
                "progress_ms": 12_000,
                "device": {"id": "d1", "name": "Laptop", "type": "Computer"},
                "context": {"uri": "spotify:playlist:pl1", "type": "playlist"},
                "item": {
                    "id": "s1",
                    "name": "track 1",
                    "duration_ms": 200_000,
                    "artists": [{"id": "a1", "name": "artist 1"}],
                },
            },
        )
    )

    body = client.get("/api/sessions/active").json()

    assert body["session"]["status"] == "active"
    assert body["note"] is None
    playing = body["playing"]
    assert playing["is_playing"] is True
    assert playing["spotify_track_id"] == "s1"
    assert playing["device_name"] == "Laptop"
    assert playing["off_context"] is False


@respx.mock
def test_playback_that_wandered_off_the_playlist_is_flagged(
    client: TestClient, signed_in: User, library: None
) -> None:
    mock_happy_path()
    chime_in(client)
    respx.get(f"{API}/me/player").mock(
        return_value=httpx.Response(
            200,
            json={
                "is_playing": True,
                "context": {"uri": "spotify:album:somewhere-else", "type": "album"},
                "item": {"id": "zz", "name": "Something else", "duration_ms": 1000},
            },
        )
    )

    assert client.get("/api/sessions/active").json()["playing"]["off_context"] is True


@respx.mock
def test_nothing_playing_is_explained_rather_than_guessed_at(
    client: TestClient, signed_in: User, library: None
) -> None:
    mock_happy_path()
    chime_in(client)
    respx.get(f"{API}/me/player").mock(return_value=httpx.Response(204))

    body = client.get("/api/sessions/active").json()

    assert body["playing"] is None
    assert body["note"] == NOT_PLAYING
    assert body["session"] is not None  # the session is still a fact


@respx.mock
def test_unreadable_playback_does_not_hide_the_session(
    client: TestClient, signed_in: User, library: None
) -> None:
    """Otherwise a Spotify wobble would put Chime out out of reach."""
    mock_happy_path()
    chime_in(client)
    respx.get(f"{API}/me/player").mock(
        return_value=httpx.Response(403, json={"error": {"status": 403, "message": "nope"}})
    )

    body = client.get("/api/sessions/active").json()

    assert body["session"]["status"] == "active"
    assert body["playing"] is None
    assert body["note"] == PLAYBACK_UNREADABLE


# ------------------------------------------------------------------- one session


@respx.mock
def test_a_session_can_be_read_back_by_id(
    client: TestClient, signed_in: User, library: None
) -> None:
    mock_happy_path()
    created = chime_in(client).json()

    body = client.get(f"/api/sessions/{created['id']}").json()

    assert body["id"] == created["id"]
    assert len(body["tracks"]) == 6


def test_someone_elses_session_does_not_exist(
    client: TestClient, signed_in: User, db: DbSession
) -> None:
    from app.models import STATUS_ACTIVE, Session

    other = User(spotify_account_id="acc_other", spotify_user_id="other")
    db.add(other)
    db.commit()
    theirs = Session(
        user_id=other.id,
        status=STATUS_ACTIVE,
        type="focus",
        intent="match",
        started_at=utcnow(),
    )
    db.add(theirs)
    db.commit()

    assert client.get(f"/api/sessions/{theirs.id}").status_code == 404


def test_a_session_that_never_existed_is_a_404(client: TestClient, signed_in: User) -> None:
    assert client.get("/api/sessions/9999").status_code == 404


# ------------------------------------------------------------------- mood + end


@respx.mock
def test_a_mood_recheck_is_accepted(
    client: TestClient, signed_in: User, library: None
) -> None:
    mock_happy_path()
    created = chime_in(client, mood="flat").json()

    response = client.post(f"/api/sessions/{created['id']}/mood", json={"mood": "steady"})

    assert response.status_code == 200
    assert response.json()["mood_in"] == "flat"  # a re-check does not rewrite the start


@respx.mock
def test_an_unknown_recheck_mood_is_a_bad_request(
    client: TestClient, signed_in: User, library: None
) -> None:
    mock_happy_path()
    created = chime_in(client).json()

    response = client.post(f"/api/sessions/{created['id']}/mood", json={"mood": "peckish"})

    assert response.status_code == 400


@respx.mock
def test_chime_out_removes_the_playlist_and_summarises(
    client: TestClient, signed_in: User, library: None
) -> None:
    mock_happy_path()
    created = chime_in(client).json()
    respx.put(f"{API}/me/player/pause").mock(return_value=httpx.Response(204))
    removed = mock_remove()

    response = client.post(
        f"/api/sessions/{created['id']}/end", json={"keep": False, "mood_out": "steady"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ended"
    assert body["kept"] is False
    assert body["mood_out"] == "steady"
    assert body["summary"]["queued"] == 6
    assert body["summary"]["played"] is None  # unmeasured until phase 6
    assert body["summary"]["problems"] == []
    assert removed.call_count == 1


@respx.mock
def test_a_kept_session_is_renamed_not_removed(
    client: TestClient, signed_in: User, library: None
) -> None:
    mock_happy_path()
    created = chime_in(client).json()
    respx.put(f"{API}/me/player/pause").mock(return_value=httpx.Response(204))
    rename = respx.put(f"{API}/playlists/pl1").mock(return_value=httpx.Response(200))
    removed = mock_remove()

    body = client.post(
        f"/api/sessions/{created['id']}/end", json={"keep": True, "name": "Tuesday mornings"}
    ).json()

    assert rename.call_count == 1
    assert removed.call_count == 0
    assert body["kept"] is True
    assert body["playlist_name"] == "Tuesday mornings"


@respx.mock
def test_ending_a_finished_session_is_a_bad_request(
    client: TestClient, signed_in: User, library: None
) -> None:
    mock_happy_path()
    created = chime_in(client).json()
    respx.put(f"{API}/me/player/pause").mock(return_value=httpx.Response(204))
    mock_remove()
    client.post(f"/api/sessions/{created['id']}/end", json={})

    response = client.post(f"/api/sessions/{created['id']}/end", json={})

    assert response.status_code == 400


# -------------------------------------------------------------------- transport


@respx.mock
@pytest.mark.parametrize(
    ("action", "method", "path"),
    [
        ("next", "POST", "/me/player/next"),
        ("previous", "POST", "/me/player/previous"),
        ("pause", "PUT", "/me/player/pause"),
        ("resume", "PUT", "/me/player/play"),
    ],
)
def test_the_transport_controls_pass_straight_through(
    client: TestClient,
    signed_in: User,
    library: None,
    action: str,
    method: str,
    path: str,
) -> None:
    mock_happy_path()
    created = chime_in(client).json()
    route = respx.request(method, f"{API}{path}").mock(return_value=httpx.Response(204))
    before = route.call_count

    response = client.post(f"/api/sessions/{created['id']}/{action}")

    assert response.status_code == 204
    assert route.call_count == before + 1


@respx.mock
def test_transport_on_a_finished_session_is_a_conflict(
    client: TestClient, signed_in: User, library: None
) -> None:
    mock_happy_path()
    created = chime_in(client).json()
    respx.put(f"{API}/me/player/pause").mock(return_value=httpx.Response(204))
    mock_remove()
    client.post(f"/api/sessions/{created['id']}/end", json={})

    response = client.post(f"/api/sessions/{created['id']}/next")

    assert response.status_code == 409


@respx.mock
def test_a_transport_refusal_reaches_the_user_as_a_conflict(
    client: TestClient, signed_in: User, library: None
) -> None:
    mock_happy_path()
    created = chime_in(client).json()
    respx.post(f"{API}/me/player/next").mock(
        return_value=httpx.Response(
            404,
            json={
                "error": {
                    "status": 404,
                    "message": "No active device found",
                    "reason": "NO_ACTIVE_DEVICE",
                }
            },
        )
    )

    response = client.post(f"/api/sessions/{created['id']}/next")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "NO_ACTIVE_DEVICE"
    # Spotify's own wording, not the retry loop's "has no /me/player/next".
    assert detail["message"] == "No active device found"
