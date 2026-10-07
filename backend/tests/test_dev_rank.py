"""The dev ranking view: /api/dev/rank.

It exists so Phase 3 can be checked before there is a session or playback, so what these
tests care about is that it explains itself and never needs WHOOP to answer.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.cookies import dumps
from app.models import Track, TrackTag, User, UserTrack


def sign_in(client: TestClient, user: User) -> None:
    client.cookies.set(settings.session_cookie_name, dumps("chime.session", {"uid": user.id}))


def library(db: Session, user: User, count: int = 30) -> None:
    """A spread of energies across a handful of artists, half of it tagged."""
    for index in range(count):
        track = Track(
            spotify_track_id=f"s{index}",
            name=f"track {index}",
            artist_ids=[f"a{index % 5}"],
            artist_names=[f"artist {index % 5}"],
            duration_ms=200_000,
        )
        db.add(track)
        db.flush()
        db.add(UserTrack(user_id=user.id, track_id=track.id, source="liked"))
        if index % 2 == 0:
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


def test_it_needs_a_signed_in_user(client: TestClient) -> None:
    assert client.get("/api/dev/rank").status_code == 401


def test_it_ranks_without_whoop_connected(client: TestClient, db: Session, user: User) -> None:
    """Chime in has to work on mood and time of day alone, and so does this."""
    library(db, user)
    sign_in(client, user)

    response = client.get("/api/dev/rank", params={"mood": "flat", "count": 10})

    assert response.status_code == 200
    payload = response.json()
    assert payload["body"]["connected"] is False
    assert len(payload["tracks"]) == 10
    assert payload["pool"] == {
        "size": 30,
        "tagged": 15,
        "untagged": 15,
        "mean_confidence": 0.4,
    }


def test_every_track_explains_itself(client: TestClient, db: Session, user: User) -> None:
    library(db, user)
    sign_in(client, user)

    payload = client.get("/api/dev/rank", params={"type": "focus", "count": 5}).json()

    first = payload["tracks"][0]
    assert first["position"] == 0
    assert first["artists"]
    breakdown = first["breakdown"]
    assert set(breakdown) == {
        "energy_fit",
        "affinity",
        "behavior",
        "freshness",
        "score",
        "energy",
        "confidence",
        "target",
        "tags",
    }
    assert breakdown["target"] == payload["profile"]["curve"][0]


def test_the_profile_comes_back_with_its_reasons(
    client: TestClient, db: Session, user: User
) -> None:
    library(db, user)
    sign_in(client, user)

    payload = client.get(
        "/api/dev/rank", params={"type": "auto", "mood": "fired_up", "count": 6}
    ).json()

    profile = payload["profile"]
    assert profile["type"] == "workout"  # fired up asks for one
    assert profile["intent"] == "match"
    assert len(profile["curve"]) == 6
    assert profile["notes"]


def test_an_empty_library_answers_rather_than_failing(
    client: TestClient, db: Session, user: User
) -> None:
    sign_in(client, user)

    response = client.get("/api/dev/rank", params={"mood": "steady"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["tracks"] == []
    assert payload["pool"]["size"] == 0


def test_a_nonsense_mood_is_a_bad_request_not_a_crash(
    client: TestClient, db: Session, user: User
) -> None:
    sign_in(client, user)

    response = client.get("/api/dev/rank", params={"mood": "peckish"})

    assert response.status_code == 400
    assert "peckish" in response.json()["detail"]


def test_it_only_shows_the_signed_in_user_their_own_library(
    client: TestClient, db: Session, user: User
) -> None:
    other = User(spotify_account_id="acc_other", spotify_user_id="other")
    db.add(other)
    db.commit()
    library(db, other, count=10)
    sign_in(client, user)

    assert client.get("/api/dev/rank").json()["pool"]["size"] == 0
