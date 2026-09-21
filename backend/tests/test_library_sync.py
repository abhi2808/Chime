"""Library sync against fixture responses: upserts, the incremental stop, resilience."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.integrations.spotify.client import SpotifyClient
from app.models import (
    SYNC_COMPLETE,
    SYNC_ERROR,
    SYNC_PARTIAL,
    Artist,
    LibrarySyncState,
    Track,
    User,
    UserTrack,
)
from app.services import library_sync

TRACKS_URL = "https://api.spotify.com/v1/me/tracks"


class FakeTokens:
    async def get_access_token(self, *, force_refresh: bool = False) -> str:
        return "access-token"


def track(
    track_id: str,
    name: str,
    artists: list[tuple[str, str]],
    *,
    is_local: bool = False,
) -> dict[str, Any]:
    return {
        "id": track_id,
        "name": name,
        "duration_ms": 214_000,
        "explicit": False,
        "is_local": is_local,
        "artists": [{"id": artist_id, "name": artist_name} for artist_id, artist_name in artists],
        "album": {
            "id": f"al_{track_id}",
            "name": f"Album for {name}",
            "images": [
                {"url": f"https://i.scdn.co/{track_id}-640", "width": 640, "height": 640},
                {"url": f"https://i.scdn.co/{track_id}-64", "width": 64, "height": 64},
            ],
        },
        # Fields Spotify marks deprecated; we must ignore them rather than store them.
        "popularity": 42,
        "preview_url": None,
        "available_markets": ["GB"],
    }


def page(items: list[dict[str, Any]], *, offset: int, total: int, has_next: bool) -> dict[str, Any]:
    return {
        "items": items,
        "limit": 50,
        "offset": offset,
        "total": total,
        "next": f"{TRACKS_URL}?offset={offset + 50}&limit=50" if has_next else None,
    }


def saved(track_payload: dict[str, Any], added_at: str = "2026-09-01T10:00:00Z") -> dict[str, Any]:
    return {"added_at": added_at, "track": track_payload}


def mock_artists(**genres: list[str] | None) -> None:
    """Route each artist id to a fixture; ``None`` omits the deprecated genres field."""
    for artist_id, artist_genres in genres.items():
        body: dict[str, Any] = {"id": artist_id, "name": f"Artist {artist_id}"}
        if artist_genres is not None:
            body["genres"] = artist_genres
        respx.get(f"https://api.spotify.com/v1/artists/{artist_id}").mock(
            return_value=httpx.Response(200, json=body)
        )


async def run(user_id: int, *, full: bool = False) -> None:
    async with SpotifyClient(FakeTokens()) as client:
        await library_sync.run_sync(
            user_id, full=full, session_factory=SessionLocal, spotify=client
        )


@respx.mock
async def test_first_sync_stores_tracks_links_and_artist_genres(db: Session, user: User) -> None:
    respx.get(TRACKS_URL, params={"limit": 50, "offset": 0}).mock(
        return_value=httpx.Response(
            200,
            json=page(
                [
                    saved(track("t1", "First", [("a1", "Alpha"), ("a2", "Beta")])),
                    saved(track("t2", "Second", [("a1", "Alpha")])),
                ],
                offset=0,
                total=3,
                has_next=True,
            ),
        )
    )
    respx.get(TRACKS_URL, params={"limit": 50, "offset": 50}).mock(
        return_value=httpx.Response(
            200,
            json=page(
                [saved(track("t3", "Third", [("a3", "Gamma")]))],
                offset=50,
                total=3,
                has_next=False,
            ),
        )
    )
    mock_artists(a1=["indie rock"], a2=["ambient", "downtempo"], a3=None)

    await run(user.id)

    tracks = db.scalars(select(Track).order_by(Track.spotify_track_id)).all()
    assert [row.spotify_track_id for row in tracks] == ["t1", "t2", "t3"]
    first = tracks[0]
    assert first.name == "First"
    assert first.artist_ids == ["a1", "a2"]
    assert first.artist_names == ["Alpha", "Beta"]
    assert first.album_name == "Album for First"
    assert first.image_url == "https://i.scdn.co/t1-640"  # largest image kept
    assert first.duration_ms == 214_000

    links = db.scalars(select(UserTrack)).all()
    assert len(links) == 3
    assert {link.source for link in links} == {"liked"}
    assert all(link.liked_at is not None for link in links)

    artists = {row.spotify_artist_id: row for row in db.scalars(select(Artist)).all()}
    assert set(artists) == {"a1", "a2", "a3"}
    assert artists["a2"].genres == ["ambient", "downtempo"]
    assert artists["a3"].genres is None  # field absent: deprecated and may vanish
    assert all(row.fetched_at is not None for row in artists.values())

    state = db.scalar(select(LibrarySyncState))
    assert state is not None
    assert state.state == SYNC_COMPLETE
    assert state.mode == "incremental"
    assert state.tracks_synced == 3
    assert state.tracks_total == 3
    assert state.artists_total == 3
    assert state.artists_fetched == 3
    assert state.artists_failed == 0
    assert state.finished_at is not None


@respx.mock
async def test_incremental_resync_stops_at_the_first_known_liked_song(
    db: Session, user: User
) -> None:
    first_page = respx.get(TRACKS_URL, params={"limit": 50, "offset": 0}).mock(
        side_effect=[
            httpx.Response(
                200,
                json=page(
                    [saved(track("t1", "First", [("a1", "Alpha")]))],
                    offset=0,
                    total=1,
                    has_next=False,
                ),
            ),
            # Second run, newest first: one new like on top of the one we already have,
            # and a full page so Spotify offers a 'next'.
            httpx.Response(
                200,
                json=page(
                    [
                        saved(track("t9", "Brand new", [("a9", "Omega")])),
                        saved(track("t1", "First", [("a1", "Alpha")])),
                    ],
                    offset=0,
                    total=2,
                    has_next=True,
                ),
            ),
        ]
    )
    second_page = respx.get(TRACKS_URL, params={"limit": 50, "offset": 50})
    mock_artists(a1=["indie rock"], a9=["synthpop"])

    await run(user.id)
    await run(user.id)

    assert first_page.call_count == 2
    assert second_page.call_count == 0  # stopped instead of walking the whole library
    assert len(db.scalars(select(UserTrack)).all()) == 2

    state = db.scalar(select(LibrarySyncState))
    assert state is not None
    assert state.stopped_early is True
    assert state.tracks_synced == 1  # only the new one was processed
    assert state.artists_total == 1  # a1 was already fetched, so only a9 this time
    assert state.state == SYNC_COMPLETE


@respx.mock
async def test_full_resync_walks_everything_and_refetches_artists(
    db: Session, user: User
) -> None:
    respx.get(TRACKS_URL, params={"limit": 50, "offset": 0}).mock(
        return_value=httpx.Response(
            200,
            json=page(
                [saved(track("t1", "First", [("a1", "Alpha")]))],
                offset=0,
                total=1,
                has_next=False,
            ),
        )
    )
    # Spotify answers differently the second time: genres are deprecated and volatile.
    respx.get("https://api.spotify.com/v1/artists/a1").mock(
        side_effect=[
            httpx.Response(200, json={"id": "a1", "name": "Alpha", "genres": []}),
            httpx.Response(200, json={"id": "a1", "name": "Alpha", "genres": ["indie rock"]}),
        ]
    )

    await run(user.id)
    assert db.scalar(select(Artist).where(Artist.spotify_artist_id == "a1")).genres == []

    await run(user.id, full=True)
    db.expire_all()

    assert len(db.scalars(select(UserTrack)).all()) == 1  # upsert, not duplicate
    artist = db.scalar(select(Artist).where(Artist.spotify_artist_id == "a1"))
    assert artist is not None
    assert artist.genres == ["indie rock"]

    state = db.scalar(select(LibrarySyncState))
    assert state is not None
    assert state.mode == "full"
    assert state.stopped_early is False
    assert state.tracks_synced == 1


@respx.mock
async def test_local_and_empty_entries_are_skipped(db: Session, user: User) -> None:
    respx.get(TRACKS_URL, params={"limit": 50, "offset": 0}).mock(
        return_value=httpx.Response(
            200,
            json=page(
                [
                    saved(track("t1", "Keeper", [("a1", "Alpha")])),
                    saved(track("t2", "Local file", [("a1", "Alpha")], is_local=True)),
                    {"added_at": "2026-09-01T10:00:00Z", "track": None},
                ],
                offset=0,
                total=3,
                has_next=False,
            ),
        )
    )
    mock_artists(a1=["indie rock"])

    await run(user.id)

    assert [row.spotify_track_id for row in db.scalars(select(Track)).all()] == ["t1"]
    state = db.scalar(select(LibrarySyncState))
    assert state is not None
    assert state.state == SYNC_COMPLETE
    assert state.tracks_synced == 1


@respx.mock
async def test_one_unreadable_artist_does_not_fail_the_sync(db: Session, user: User) -> None:
    respx.get(TRACKS_URL, params={"limit": 50, "offset": 0}).mock(
        return_value=httpx.Response(
            200,
            json=page(
                [saved(track("t1", "First", [("a1", "Alpha"), ("a2", "Beta")]))],
                offset=0,
                total=1,
                has_next=False,
            ),
        )
    )
    mock_artists(a1=["indie rock"])
    respx.get("https://api.spotify.com/v1/artists/a2").mock(return_value=httpx.Response(404))

    await run(user.id)

    state = db.scalar(select(LibrarySyncState))
    assert state is not None
    assert state.state == SYNC_COMPLETE
    assert state.artists_fetched == 1
    assert state.artists_failed == 1
    assert db.scalar(select(Artist).where(Artist.spotify_artist_id == "a2")) is None


@respx.mock
async def test_a_failed_page_records_the_error_and_keeps_its_place(
    db: Session, user: User
) -> None:
    respx.get(TRACKS_URL, params={"limit": 50, "offset": 0}).mock(
        return_value=httpx.Response(
            200,
            json=page(
                [saved(track("t1", "First", [("a1", "Alpha")]))],
                offset=0,
                total=60,
                has_next=True,
            ),
        )
    )
    respx.get(TRACKS_URL, params={"limit": 50, "offset": 50}).mock(
        return_value=httpx.Response(403, json={"error": {"status": 403, "message": "nope"}})
    )

    await run(user.id)

    state = db.scalar(select(LibrarySyncState))
    assert state is not None
    assert state.state == SYNC_ERROR
    assert state.error == "nope"
    assert state.next_offset == 50  # resumes from the page it failed on
    assert len(db.scalars(select(UserTrack)).all()) == 1


@respx.mock
async def test_an_interrupted_run_resumes_from_its_offset(db: Session, user: User) -> None:
    # Stand in for a process killed mid-sync: state left running, part way through.
    db.add(
        LibrarySyncState(
            user_id=user.id,
            state="running",
            phase="tracks",
            mode="incremental",
            next_offset=50,
            tracks_synced=50,
        )
    )
    db.commit()

    from_start = respx.get(TRACKS_URL, params={"limit": 50, "offset": 0})
    resumed = respx.get(TRACKS_URL, params={"limit": 50, "offset": 50}).mock(
        return_value=httpx.Response(
            200,
            json=page(
                [saved(track("t51", "Fifty first", [("a1", "Alpha")]))],
                offset=50,
                total=51,
                has_next=False,
            ),
        )
    )
    mock_artists(a1=["indie rock"])

    await run(user.id)

    assert from_start.call_count == 0
    assert resumed.call_count == 1
    db.expire_all()
    state = db.scalar(select(LibrarySyncState))
    assert state is not None
    assert state.state == SYNC_COMPLETE
    assert state.tracks_synced == 51  # kept the count from before the interruption


@respx.mock
async def test_an_unreadable_artist_body_costs_one_artist_not_the_sync(
    db: Session, user: User
) -> None:
    respx.get(TRACKS_URL, params={"limit": 50, "offset": 0}).mock(
        return_value=httpx.Response(
            200,
            json=page(
                [saved(track("t1", "First", [("a1", "Alpha"), ("a2", "Beta")]))],
                offset=0,
                total=1,
                has_next=False,
            ),
        )
    )
    mock_artists(a1=["indie rock"])
    # A 200 with nothing in it: the body cannot be parsed into an artist.
    respx.get("https://api.spotify.com/v1/artists/a2").mock(return_value=httpx.Response(200))

    await run(user.id)

    db.expire_all()
    state = db.scalar(select(LibrarySyncState))
    assert state is not None
    assert state.state == SYNC_COMPLETE
    assert state.artists_fetched == 1
    assert state.artists_failed == 1


@respx.mock
async def test_a_rate_limited_artist_phase_keeps_what_it_got_and_stops(
    db: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A long Retry-After ends the run as partial instead of grinding artist by artist."""
    monkeypatch.setattr(settings, "artist_fetch_concurrency", 1)

    respx.get(TRACKS_URL, params={"limit": 50, "offset": 0}).mock(
        return_value=httpx.Response(
            200,
            json=page(
                [
                    saved(track("t1", "First", [("a1", "Alpha")])),
                    saved(track("t2", "Second", [("a1", "Alpha"), ("a2", "Beta")])),
                ],
                offset=0,
                total=2,
                has_next=False,
            ),
        )
    )
    mock_artists(a1=["indie rock"])
    throttled = respx.get("https://api.spotify.com/v1/artists/a2").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "600"})
    )

    await run(user.id)

    assert throttled.call_count == 1  # asked once, took the hint
    db.expire_all()
    state = db.scalar(select(LibrarySyncState))
    assert state is not None
    assert state.state == SYNC_PARTIAL
    assert state.error is None  # being throttled is not a failure
    assert state.resume_after is not None
    assert state.artists_fetched == 1
    assert state.artists_failed == 0  # the throttled artist is still pending, not failed

    status = library_sync.get_status(db, user.id)
    assert status.artists_remaining == 1
    # The tracks are all in, so the library is usable right now.
    assert status.liked_tracks == 2
    assert status.artists_with_genres == 1


@respx.mock
async def test_the_next_run_picks_up_the_artists_that_were_left(db: Session, user: User) -> None:
    body = page(
        [saved(track("t1", "First", [("a1", "Alpha"), ("a2", "Beta")]))],
        offset=0,
        total=1,
        has_next=False,
    )
    # One route, two answers: re-registering the same pattern would never win.
    respx.get(TRACKS_URL, params={"limit": 50, "offset": 0}).mock(
        side_effect=[httpx.Response(200, json=body), httpx.Response(200, json=body)]
    )
    # Registered directly rather than through mock_artists, so the route object is here
    # to assert on; re-registering the same pattern would shadow the first mock.
    first = respx.get("https://api.spotify.com/v1/artists/a1").mock(
        return_value=httpx.Response(
            200, json={"id": "a1", "name": "Alpha", "genres": ["indie rock"]}
        )
    )
    second = respx.get("https://api.spotify.com/v1/artists/a2").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "600"}),
            httpx.Response(200, json={"id": "a2", "name": "Beta", "genres": ["ambient"]}),
        ]
    )

    await run(user.id)
    await run(user.id)

    assert second.call_count == 2
    assert first.call_count == 1  # an artist already stored is not fetched again
    db.expire_all()
    state = db.scalar(select(LibrarySyncState))
    assert state is not None
    assert state.state == SYNC_COMPLETE
    assert state.resume_after is None
    beta = db.scalar(select(Artist).where(Artist.spotify_artist_id == "a2"))
    assert beta is not None
    assert beta.genres == ["ambient"]


@respx.mock
async def test_the_artist_phase_gives_up_when_it_runs_out_of_time(
    db: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "artist_phase_budget_seconds", 0.0)

    respx.get(TRACKS_URL, params={"limit": 50, "offset": 0}).mock(
        return_value=httpx.Response(
            200,
            json=page(
                [saved(track("t1", "First", [("a1", "Alpha")]))],
                offset=0,
                total=1,
                has_next=False,
            ),
        )
    )
    never = respx.get("https://api.spotify.com/v1/artists/a1")

    await run(user.id)

    assert never.call_count == 0
    db.expire_all()
    state = db.scalar(select(LibrarySyncState))
    assert state is not None
    assert state.state == SYNC_PARTIAL
    assert state.resume_after is None  # nothing to wait for, just try again later
    assert len(db.scalars(select(UserTrack)).all()) == 1  # the songs still landed


@respx.mock
async def test_artists_are_fetched_most_referenced_first(
    db: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """So a run that gets cut off has tagged the artists the library leans on."""
    monkeypatch.setattr(settings, "artist_fetch_concurrency", 1)
    order: list[str] = []

    def record(artist_id: str) -> Any:
        def handler(_request: httpx.Request) -> httpx.Response:
            order.append(artist_id)
            return httpx.Response(200, json={"id": artist_id, "name": artist_id, "genres": []})

        return handler

    respx.get(TRACKS_URL, params={"limit": 50, "offset": 0}).mock(
        return_value=httpx.Response(
            200,
            json=page(
                [
                    # a2 is seen first, a1 is referenced three times.
                    saved(track("t1", "First", [("a2", "Beta"), ("a1", "Alpha")])),
                    saved(track("t2", "Second", [("a1", "Alpha")])),
                    saved(track("t3", "Third", [("a1", "Alpha")])),
                ],
                offset=0,
                total=3,
                has_next=False,
            ),
        )
    )
    for artist_id in ("a1", "a2"):
        respx.get(f"https://api.spotify.com/v1/artists/{artist_id}").mock(
            side_effect=record(artist_id)
        )

    await run(user.id)

    assert order == ["a1", "a2"]


@respx.mock
async def test_status_endpoint_reports_progress(client: Any, db: Session, user: User) -> None:
    respx.get(TRACKS_URL, params={"limit": 50, "offset": 0}).mock(
        return_value=httpx.Response(
            200,
            json=page(
                [saved(track("t1", "First", [("a1", "Alpha")]))],
                offset=0,
                total=1,
                has_next=False,
            ),
        )
    )
    mock_artists(a1=["indie rock"])
    await run(user.id)

    from app.core.cookies import dumps

    client.cookies.set("chime_session", dumps("chime.session", {"uid": user.id}))
    response = client.get("/api/library/status")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "complete"
    assert body["liked_tracks"] == 1
    assert body["tracks_total"] == 1
    assert body["artists_fetched"] == 1
    assert body["artists_with_genres"] == 1


async def test_status_for_a_user_who_never_synced(client: Any, db: Session, user: User) -> None:
    from app.core.cookies import dumps

    client.cookies.set("chime_session", dumps("chime.session", {"uid": user.id}))

    body = client.get("/api/library/status").json()

    assert body["state"] == "never"
    assert body["liked_tracks"] == 0


@respx.mock
async def test_a_second_sync_is_not_started_while_one_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_sync(user_id: int, *, full: bool = False) -> None:
        started.set()
        await release.wait()

    monkeypatch.setattr(library_sync, "run_sync", slow_sync)

    assert library_sync.start_sync(1) is True
    await started.wait()
    assert library_sync.start_sync(1) is False
    assert library_sync.is_running(1) is True

    release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert library_sync.is_running(1) is False
