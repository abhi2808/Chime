"""Tag sources, and the job that walks a library through one.

The two sources are deliberately different shapes:

* :class:`SpotifyGenreTagSource` is local and free — it reads the ``artists.genres`` we
  already cached. On this app that column is empty on every row, because Spotify has
  stopped sending ``genres`` even though its docs still list the field as deprecated
  rather than removed. The source stays because the documented path may come back, and
  because another account may still receive it.
* :class:`MusicBrainzTagSource` is a network call per track, paced at one per second.

Nothing here reaches an LLM. Track and artist names go to MusicBrainz, which is a
database lookup, not a model (CLAUDE.md rule 7).
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.musicbrainz import MusicBrainzClient, MusicBrainzError
from app.integrations.musicbrainz import tags as mb
from app.models import Artist, Track, TrackTag, UserTrack
from app.models.track_tag import SOURCE_EXTERNAL, SOURCE_MANUAL, SOURCE_MAP, SOURCE_UNKNOWN
from app.services.tagging import NOTHING, SourceTags, TagMap, Tagging, compute, load_tag_map

logger = logging.getLogger(__name__)


class SpotifyGenreTagSource:
    """Artist genres already in our cache. No network, no rate limit."""

    name = SOURCE_MAP

    def __init__(self, db: Session) -> None:
        self._db = db

    async def tags_for(self, *, title: str, artist: str | None = None) -> SourceTags:
        if not artist:
            return NOTHING
        genres = self._db.scalar(select(Artist.genres).where(Artist.name == artist))
        if not genres:
            return NOTHING
        # Spotify gives no weights, so every genre it lists counts fully.
        return SourceTags(pairs=tuple((genre, 1.0) for genre in genres), via="genres")


class MusicBrainzTagSource:
    """Recording tags, falling back to artist tags.

    Recording tags are specific but sparse; artist tags are dense but describe a career
    rather than a song. Trying the recording first and the artist second is the only
    ordering that gets both, and the artist cache means a 30-track artist costs one
    extra request, not thirty.
    """

    name = SOURCE_EXTERNAL

    def __init__(self, client: MusicBrainzClient, *, artist_fallback: bool = True) -> None:
        self._client = client
        self._artist_fallback = artist_fallback
        self._artist_cache: dict[str, tuple[tuple[str, float], ...]] = {}

    async def tags_for(self, *, title: str, artist: str | None = None) -> SourceTags:
        pairs = await mb.recording_tags(self._client, title=title, artist=artist)
        if pairs:
            return SourceTags(pairs=tuple(pairs), via="recording")
        if not (self._artist_fallback and artist):
            return NOTHING
        cached = self._artist_cache.get(artist)
        if cached is None:
            cached = tuple(await mb.artist_tags(self._client, name=artist))
            self._artist_cache[artist] = cached
        return SourceTags(pairs=cached, via="artist") if cached else NOTHING


@dataclass
class TagRun:
    """Numbers only. Tag *names* go to a file for a human, never into a report."""

    considered: int = 0
    #: Stored with a non-zero confidence: the map understood at least one tag.
    tagged: int = 0
    #: The source had tags but the map knew none of them.
    unmapped: int = 0
    #: The source had nothing at all.
    missing: int = 0
    #: Left alone because a human set them.
    manual: int = 0
    failed: int = 0
    via: Counter[str] = field(default_factory=Counter)
    #: Normalized tags the map has no entry for -> how many tracks wanted them.
    unmatched: Counter[str] = field(default_factory=Counter)
    energy: list[float] = field(default_factory=list)
    confidence: list[float] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        return self.tagged / self.considered if self.considered else 0.0


def untagged_tracks(db: Session, user_id: int, *, limit: int | None = None) -> Sequence[Track]:
    """Liked tracks with no tag row yet, oldest liked first so runs resume predictably."""
    statement = (
        select(Track)
        .join(UserTrack, UserTrack.track_id == Track.id)
        .outerjoin(TrackTag, TrackTag.track_id == Track.id)
        .where(UserTrack.user_id == user_id, TrackTag.id.is_(None))
        .order_by(UserTrack.liked_at.desc().nulls_last(), Track.id)
    )
    if limit is not None:
        statement = statement.limit(limit)
    return db.scalars(statement).all()


def unknown_tracks(db: Session, user_id: int, *, limit: int | None = None) -> Sequence[Track]:
    """Tracks a previous run looked up and found nothing for.

    Worth re-checking occasionally but not on every run: MusicBrainz is a growing
    database, so today's miss can be next year's hit, and 12% of a real library is missing
    from it.
    """
    statement = (
        select(Track)
        .join(UserTrack, UserTrack.track_id == Track.id)
        .join(TrackTag, TrackTag.track_id == Track.id)
        .where(UserTrack.user_id == user_id, TrackTag.source == SOURCE_UNKNOWN)
        .order_by(TrackTag.updated_at.asc().nulls_first(), Track.id)
    )
    if limit is not None:
        statement = statement.limit(limit)
    return db.scalars(statement).all()


def store(db: Session, track_id: int, tagging: Tagging, source: str) -> TrackTag | None:
    """Upsert a tag row. A manual row is never overwritten (SPEC section 5, step 4)."""
    row = db.scalar(select(TrackTag).where(TrackTag.track_id == track_id))
    if row is not None and row.source == SOURCE_MANUAL:
        return None
    if row is None:
        row = TrackTag(track_id=track_id)
        db.add(row)
    row.energy = tagging.energy
    row.affinities = dict(tagging.affinities)
    row.source = source if tagging.is_known else SOURCE_UNKNOWN
    row.confidence = tagging.confidence
    row.raw_tags = [[tag, weight] for tag, weight in tagging.raw] or None
    return row


async def tag_tracks(
    db: Session,
    tracks: Iterable[Track],
    source: object,
    *,
    tag_map: TagMap | None = None,
    persist: bool = True,
    run: TagRun | None = None,
    on_progress: Callable[[TagRun], None] | None = None,
) -> TagRun:
    """Tag each track through ``source``, storing the result.

    One failure costs one track: a MusicBrainz hiccup on track 400 must not throw away
    the 399 rows already written, so the loop counts the error and carries on. Each track
    is committed on its own for the same reason — a run of a thousand tracks takes half an
    hour and will be interrupted sooner or later.

    Pass ``run`` to keep the tally on the way out: an interrupted run still did real work,
    and the caller can only print its numbers if it owns the object they live in.
    ``on_progress`` is called after every track, because half an hour of silence looks
    identical to a hang.
    """
    tag_map = tag_map or load_tag_map()
    run = run if run is not None else TagRun()

    for track in tracks:
        run.considered += 1
        await _tag_one(db, track, source, tag_map, run, persist=persist)
        if on_progress is not None:
            on_progress(run)

    return run


async def _tag_one(
    db: Session,
    track: Track,
    source: object,
    tag_map: TagMap,
    run: TagRun,
    *,
    persist: bool,
) -> None:
    """One track's worth of the loop above, so every outcome updates the tally once."""
    artist = track.artist_names[0] if track.artist_names else None
    try:
        found = await source.tags_for(title=track.name, artist=artist)
    except MusicBrainzError as exc:
        run.failed += 1
        logger.warning("tag lookup failed", extra={"track_id": track.id, "error": exc.message})
        return

    if not found.found:
        # SPEC section 4: a row with source = unknown is how "we looked and found nothing"
        # is told apart from "never looked". Without it every later run pays 1.8 s to be
        # told nothing again; with it, re-checking is a deliberate --retry-unknown.
        run.missing += 1
        if persist:
            store(db, track.id, compute((), tag_map), SOURCE_UNKNOWN)
            db.commit()
        return
    run.via[found.via] += 1

    tagging = compute(found.pairs, tag_map)
    run.unmatched.update(tagging.unmatched)
    if tagging.is_known:
        run.tagged += 1
        run.energy.append(tagging.energy)
        run.confidence.append(tagging.confidence)
    else:
        run.unmapped += 1

    if persist:
        if store(db, track.id, tagging, getattr(source, "name", SOURCE_UNKNOWN)) is None:
            run.manual += 1
        db.commit()
