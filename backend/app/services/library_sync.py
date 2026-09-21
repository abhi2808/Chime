"""Library sync: liked songs, then the genres of every unique artist.

Shape of the job:

* Liked songs come newest first, so an incremental run stops at the first track it
  already has. ``full=True`` walks the whole library.
* Progress lives in ``library_sync_state``, so a run killed halfway resumes from the
  page it was on instead of starting over.
* Artists are fetched one id at a time (``GET /artists/{id}``) at low concurrency,
  because "Get Several Artists" is deprecated and off-limits. A single artist failing
  never fails the sync.
* The artist phase has a wall-clock budget and stops the moment Spotify rate limits us.
  Whatever it tagged is kept, the run ends as ``partial``, and the next sync picks up the
  artists that are still missing. Grinding through a long ``Retry-After`` per artist would
  take hours and earn more 429s. Most-referenced artists go first, so a run that gets cut
  off has still tagged the ones that matter for ranking.

Database work runs in worker threads (``asyncio.to_thread``) so the event loop stays
free for HTTP.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from time import monotonic
from urllib.parse import parse_qs, urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.config import settings
from app.db.session import SessionLocal
from app.integrations.spotify import library as spotify_library
from app.integrations.spotify.client import SpotifyClient
from app.integrations.spotify.errors import SpotifyError, SpotifyRateLimitError
from app.integrations.spotify.schemas import SavedTrackItem, SavedTracksPage, SpotifyArtist
from app.models import (
    PHASE_ARTISTS,
    PHASE_TRACKS,
    SYNC_COMPLETE,
    SYNC_ERROR,
    SYNC_PARTIAL,
    SYNC_RUNNING,
    Artist,
    LibrarySyncState,
    Track,
    UserTrack,
)
from app.services.token_store import TokenStore

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]

LIKED = "liked"
PROGRESS_FLUSH_EVERY = 10

# One task per user, so a double tap on "Sync now" cannot start two runs.
_tasks: dict[int, asyncio.Task[None]] = {}


# --------------------------------------------------------------------------- status


@dataclass(slots=True)
class SyncStatus:
    state: str
    phase: str | None
    mode: str | None
    tracks_synced: int
    tracks_total: int | None
    artists_fetched: int
    artists_total: int
    artists_failed: int
    artists_remaining: int
    liked_tracks: int
    artists_with_genres: int
    stopped_early: bool
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    resume_after: datetime | None


def get_status(db: Session, user_id: int) -> SyncStatus:
    state = db.scalar(select(LibrarySyncState).where(LibrarySyncState.user_id == user_id))
    liked = (
        db.scalar(
            select(func.count())
            .select_from(UserTrack)
            .where(UserTrack.user_id == user_id, UserTrack.source == LIKED)
        )
        or 0
    )
    with_genres = (
        db.scalar(
            select(func.count())
            .select_from(Artist)
            .where(Artist.fetched_at.is_not(None), Artist.genres.is_not(None))
        )
        or 0
    )

    running = is_running(user_id)
    if state is None:
        return SyncStatus(
            state=SYNC_RUNNING if running else "never",
            phase=None,
            mode=None,
            tracks_synced=0,
            tracks_total=None,
            artists_fetched=0,
            artists_total=0,
            artists_failed=0,
            artists_remaining=0,
            liked_tracks=liked,
            artists_with_genres=with_genres,
            stopped_early=False,
            error=None,
            started_at=None,
            finished_at=None,
            resume_after=None,
        )

    # A row left as "running" by a killed process is stale, not live.
    reported = state.state
    if reported == SYNC_RUNNING and not running:
        reported = "interrupted"

    return SyncStatus(
        state=reported,
        phase=state.phase,
        mode=state.mode,
        tracks_synced=state.tracks_synced,
        tracks_total=state.tracks_total,
        artists_fetched=state.artists_fetched,
        artists_total=state.artists_total,
        artists_failed=state.artists_failed,
        artists_remaining=max(
            0, state.artists_total - state.artists_fetched - state.artists_failed
        ),
        liked_tracks=liked,
        artists_with_genres=with_genres,
        stopped_early=state.stopped_early,
        error=state.error,
        started_at=state.started_at,
        finished_at=state.finished_at,
        resume_after=state.resume_after,
    )


# ------------------------------------------------------------------------ task glue


def is_running(user_id: int) -> bool:
    task = _tasks.get(user_id)
    return task is not None and not task.done()


def start_sync(user_id: int, *, full: bool = False) -> bool:
    """Kick off a background sync. Returns False if one is already running."""
    if is_running(user_id):
        return False
    task = asyncio.create_task(run_sync(user_id, full=full))
    _tasks[user_id] = task
    task.add_done_callback(lambda finished: _log_task_result(user_id, finished))
    return True


def _log_task_result(user_id: int, task: asyncio.Task[None]) -> None:
    if _tasks.get(user_id) is task:
        _tasks.pop(user_id, None)
    if task.cancelled():
        logger.warning("library sync cancelled", extra={"user_id": user_id})
        return
    error = task.exception()
    if error is not None:  # pragma: no cover - run_sync handles its own failures
        logger.error("library sync task crashed", exc_info=error, extra={"user_id": user_id})


# ----------------------------------------------------------------------------- run


async def run_sync(
    user_id: int,
    *,
    full: bool = False,
    session_factory: SessionFactory | None = None,
    spotify: SpotifyClient | None = None,
) -> None:
    sf: SessionFactory = session_factory or SessionLocal
    client = spotify or SpotifyClient(TokenStore(sf, user_id))
    owns_client = spotify is None

    try:
        start_offset, stop_on_known = await asyncio.to_thread(_begin, sf, user_id, full)
        logger.info(
            "library sync started",
            extra={
                "user_id": user_id,
                "mode": "full" if full else "incremental",
                "offset": start_offset,
            },
        )
        await _sync_liked_tracks(
            client, sf, user_id, start_offset=start_offset, stop_on_known=stop_on_known
        )
        artists = await _sync_artists(client, sf, user_id, full=full)
        await asyncio.to_thread(
            _update_state,
            sf,
            user_id,
            state=SYNC_PARTIAL if artists.incomplete else SYNC_COMPLETE,
            phase=None,
            error=None,
            finished_at=utcnow(),
            resume_after=_resume_at(artists.throttled_for),
        )
        logger.info(
            "library sync finished",
            extra={
                "user_id": user_id,
                "artists_fetched": artists.fetched,
                "artists_remaining": artists.remaining,
                "incomplete": artists.incomplete,
            },
        )
    except SpotifyRateLimitError as exc:
        # Hit while paging liked songs. next_offset is already stored, so the next run
        # continues from the page we were on rather than starting over.
        logger.warning(
            "library sync paused by a rate limit",
            extra={"user_id": user_id, "retry_after": exc.retry_after},
        )
        await asyncio.to_thread(
            _update_state,
            sf,
            user_id,
            state=SYNC_PARTIAL,
            error=None,
            finished_at=utcnow(),
            resume_after=_resume_at(exc.retry_after),
        )
    except asyncio.CancelledError:
        await asyncio.to_thread(
            _update_state, sf, user_id, state=SYNC_ERROR, error="Sync was cancelled"
        )
        raise
    except Exception as exc:
        message = exc.message if isinstance(exc, SpotifyError) else str(exc)
        logger.exception("library sync failed", extra={"user_id": user_id})
        await asyncio.to_thread(
            _update_state,
            sf,
            user_id,
            state=SYNC_ERROR,
            error=message[:500] or exc.__class__.__name__,
            finished_at=utcnow(),
        )
    finally:
        if owns_client:
            await client.aclose()


async def _sync_liked_tracks(
    client: SpotifyClient,
    sf: SessionFactory,
    user_id: int,
    *,
    start_offset: int,
    stop_on_known: bool,
) -> None:
    offset = start_offset
    limit = settings.liked_page_limit
    while True:
        page = await spotify_library.get_saved_tracks(client, limit=limit, offset=offset)
        result = await asyncio.to_thread(
            _persist_liked_page, sf, user_id, page.items, stop_on_known
        )
        offset = _next_page_offset(page, current=offset, limit=limit)
        await asyncio.to_thread(
            _advance_tracks_progress,
            sf,
            user_id,
            next_offset=offset,
            processed=result.processed,
            tracks_total=page.total,
            stopped_early=result.stopped,
        )
        if result.stopped or page.next is None or not page.items:
            return


def _next_page_offset(page: SavedTracksPage, *, current: int, limit: int) -> int:
    """Where the next page starts.

    Spotify's ``offset`` is an index into the list, and ``next`` already carries the
    right one, so prefer it. Advancing by the number of items received would be wrong
    for any page that came back short.
    """
    if page.next:
        parsed = parse_qs(urlparse(page.next).query).get("offset")
        if parsed:
            try:
                return int(parsed[0])
            except ValueError:
                pass
    return current + (page.limit or limit or len(page.items))


async def _sync_artists(
    client: SpotifyClient, sf: SessionFactory, user_id: int, *, full: bool
) -> ArtistPhaseResult:
    artist_ids = await asyncio.to_thread(_pending_artist_ids, sf, user_id, full)
    await asyncio.to_thread(
        _update_state,
        sf,
        user_id,
        phase=PHASE_ARTISTS,
        artists_total=len(artist_ids),
        artists_fetched=0,
        artists_failed=0,
    )
    if not artist_ids:
        return ArtistPhaseResult(fetched=0, failed=0, remaining=0)

    semaphore = asyncio.Semaphore(max(1, settings.artist_fetch_concurrency))
    counters = {"fetched": 0, "failed": 0, "pending": 0}
    lock = asyncio.Lock()
    deadline = monotonic() + max(0.0, settings.artist_phase_budget_seconds)
    stop = asyncio.Event()
    throttled_for: float | None = None
    out_of_time = False

    async def fetch_one(artist_id: str) -> None:
        nonlocal throttled_for, out_of_time
        if stop.is_set():
            return
        async with semaphore:
            if stop.is_set():
                return
            if monotonic() >= deadline:
                out_of_time = True
                stop.set()
                return
            try:
                artist = await spotify_library.get_artist(client, artist_id)
            except SpotifyRateLimitError as exc:
                # Spotify wants a long pause. Leave the rest for the next run.
                throttled_for = exc.retry_after
                stop.set()
                return
            except SpotifyError as exc:
                # One unreadable artist must not sink the sync.
                logger.warning(
                    "artist fetch failed",
                    extra={"artist_id": artist_id, "status": exc.status, "reason": exc.message},
                )
                key = "failed"
            else:
                await asyncio.to_thread(_persist_artist, sf, artist_id, artist)
                key = "fetched"
        async with lock:
            counters[key] += 1
            counters["pending"] += 1
            if counters["pending"] < PROGRESS_FLUSH_EVERY:
                return
            counters["pending"] = 0
            fetched, failed = counters["fetched"], counters["failed"]
        await asyncio.to_thread(
            _update_state, sf, user_id, artists_fetched=fetched, artists_failed=failed
        )

    await asyncio.gather(*(fetch_one(artist_id) for artist_id in artist_ids))
    await asyncio.to_thread(
        _update_state,
        sf,
        user_id,
        artists_fetched=counters["fetched"],
        artists_failed=counters["failed"],
    )
    result = ArtistPhaseResult(
        fetched=counters["fetched"],
        failed=counters["failed"],
        remaining=max(0, len(artist_ids) - counters["fetched"] - counters["failed"]),
        throttled_for=throttled_for,
        out_of_time=out_of_time,
    )
    if result.incomplete:
        logger.warning(
            "artist phase stopped early",
            extra={
                "user_id": user_id,
                "reason": "rate limit" if throttled_for is not None else "time budget",
                "retry_after": throttled_for,
                "remaining": result.remaining,
            },
        )
    return result


def _resume_at(retry_after: float | None) -> datetime | None:
    if retry_after is None or retry_after <= 0:
        return None
    return utcnow() + timedelta(seconds=retry_after)


# ------------------------------------------------------------------- database units


@dataclass(slots=True)
class PageResult:
    processed: int
    inserted: int
    stopped: bool


@dataclass(slots=True)
class ArtistPhaseResult:
    fetched: int
    failed: int
    remaining: int
    #: Retry-After from Spotify, when a rate limit is what stopped us.
    throttled_for: float | None = None
    out_of_time: bool = False

    @property
    def incomplete(self) -> bool:
        """True when artists are still untagged *and* we chose to stop."""
        return self.remaining > 0 and (self.throttled_for is not None or self.out_of_time)


def _get_or_create_state(db: Session, user_id: int) -> LibrarySyncState:
    state = db.scalar(select(LibrarySyncState).where(LibrarySyncState.user_id == user_id))
    if state is None:
        state = LibrarySyncState(user_id=user_id)
        db.add(state)
        db.flush()
    return state


def _begin(sf: SessionFactory, user_id: int, full: bool) -> tuple[int, bool]:
    """Mark the run as running and work out where to start. Returns (offset, stop_on_known)."""
    with sf() as db:
        state = _get_or_create_state(db, user_id)
        resuming = (
            not full
            and state.phase == PHASE_TRACKS
            and state.state in (SYNC_RUNNING, SYNC_ERROR, SYNC_PARTIAL)
            and state.next_offset > 0
        )
        start_offset = state.next_offset if resuming else 0

        state.state = SYNC_RUNNING
        state.mode = "full" if full else "incremental"
        state.phase = PHASE_TRACKS
        state.next_offset = start_offset
        state.stopped_early = False
        state.error = None
        state.finished_at = None
        state.resume_after = None
        state.started_at = utcnow()
        state.updated_at = utcnow()
        if not resuming:
            state.tracks_synced = 0
            state.tracks_total = None
            state.artists_total = 0
            state.artists_fetched = 0
            state.artists_failed = 0
        db.commit()
        return start_offset, not full


def _update_state(sf: SessionFactory, user_id: int, **fields: object) -> None:
    with sf() as db:
        state = _get_or_create_state(db, user_id)
        for key, value in fields.items():
            setattr(state, key, value)
        state.updated_at = utcnow()
        db.commit()


def _advance_tracks_progress(
    sf: SessionFactory,
    user_id: int,
    *,
    next_offset: int,
    processed: int,
    tracks_total: int,
    stopped_early: bool,
) -> None:
    with sf() as db:
        state = _get_or_create_state(db, user_id)
        state.next_offset = next_offset
        state.tracks_synced += processed
        state.tracks_total = tracks_total
        if stopped_early:
            state.stopped_early = True
        state.updated_at = utcnow()
        db.commit()


def _persist_liked_page(
    sf: SessionFactory,
    user_id: int,
    items: Sequence[SavedTrackItem],
    stop_on_known: bool,
) -> PageResult:
    processed = 0
    inserted = 0
    stopped = False

    with sf() as db:
        for item in items:
            track = item.track
            if track is None or not track.id or not track.name or track.is_local:
                continue

            row = db.scalar(select(Track).where(Track.spotify_track_id == track.id))
            link = None
            if row is not None:
                link = db.scalar(
                    select(UserTrack).where(
                        UserTrack.user_id == user_id,
                        UserTrack.track_id == row.id,
                        UserTrack.source == LIKED,
                    )
                )
            if link is not None and stop_on_known:
                # Liked songs are newest first, so everything past here is already stored.
                stopped = True
                break

            if row is None:
                row = Track(spotify_track_id=track.id)
                db.add(row)
            row.name = track.name
            row.artist_ids = track.artist_ids
            row.artist_names = track.artist_names
            row.album_name = track.album.name if track.album else None
            row.image_url = track.image_url
            row.duration_ms = track.duration_ms
            row.explicit = track.explicit
            row.cached_at = utcnow()
            db.flush()

            if link is None:
                db.add(
                    UserTrack(
                        user_id=user_id,
                        track_id=row.id,
                        source=LIKED,
                        liked_at=item.added_at,
                    )
                )
                inserted += 1
            elif item.added_at is not None:
                link.liked_at = item.added_at
            processed += 1
        db.commit()

    return PageResult(processed=processed, inserted=inserted, stopped=stopped)


def _pending_artist_ids(sf: SessionFactory, user_id: int, full: bool) -> list[str]:
    with sf() as db:
        rows: Iterable[list[str] | None] = db.scalars(
            select(Track.artist_ids)
            .join(UserTrack, UserTrack.track_id == Track.id)
            .where(UserTrack.user_id == user_id)
        )
        # Count how many liked tracks each artist covers, then fetch the busiest first:
        # a run cut short by a rate limit or the time budget has then tagged the artists
        # that most of the library depends on. dict insertion order breaks ties, so the
        # order stays reproducible across resumes.
        weight: dict[str, int] = {}
        for artist_ids in rows:
            for artist_id in artist_ids or []:
                weight[artist_id] = weight.get(artist_id, 0) + 1
        if not weight:
            return []
        wanted = sorted(weight, key=lambda artist_id: -weight[artist_id])
        if full:
            return wanted
        known = set(
            db.scalars(select(Artist.spotify_artist_id).where(Artist.fetched_at.is_not(None)))
        )
        return [artist_id for artist_id in wanted if artist_id not in known]


def _persist_artist(sf: SessionFactory, artist_id: str, artist: SpotifyArtist) -> None:
    with sf() as db:
        row = db.scalar(select(Artist).where(Artist.spotify_artist_id == artist_id))
        if row is None:
            row = Artist(spotify_artist_id=artist_id)
            db.add(row)
        if artist.name:
            row.name = artist.name
        # None means Spotify omitted the (deprecated) field; [] means it sent no genres.
        row.genres = artist.genres
        row.fetched_at = utcnow()
        db.commit()
