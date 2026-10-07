"""History: every session that ever ran, and bringing one back (SPEC section 7).

Everything here reads rows Phase 4 already wrote — this phase adds no columns. Two things
are worth knowing before changing it:

* **Minutes come off the stored summary where there is one.** Recomputing them per row
  would mean a query per session for a list of twenty, and a session that was ended hours
  ago has already had its minutes settled. Only a live session is measured against the
  clock, because its summary does not exist yet.
* **"Bring it back" makes a new playlist and leaves the old URI alone.** The playlist a
  removed session points at is gone from the library, and that is a fact about what
  happened. The new one is recorded as a ``restore`` event, so a session can be brought back
  more than once without the row lying about which playlist it made.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session as DbSession

from app.core.clock import as_utc, utcnow
from app.db.session import SessionLocal
from app.integrations.spotify import playlists
from app.integrations.spotify.client import SpotifyClient
from app.models import (
    EVENT_RESTORE,
    STATUS_FAILED,
    Session,
    SessionEvent,
    SessionTrack,
    Track,
)
from app.services import sessions
from app.services.token_store import TokenStore

logger = logging.getLogger(__name__)

#: How many covers the artwork strip on a session card shows.
ARTWORK = 4

#: The default window for the summary above the list.
SUMMARY_DAYS = 7

#: What a brought-back playlist says about itself. No track or artist data, as ever.
RESTORE_DESCRIPTION = "Brought back by Chime from a session on {date}."


class HistoryError(RuntimeError):
    """Something could not be read or rebuilt. Carries a message meant for the user."""


@dataclass(frozen=True, slots=True)
class Filters:
    """SPEC section 7's filters for ``GET /api/sessions``.

    ``start`` and ``end`` are whole days on the user's own clock, sent by the browser as
    dates. ``end`` is inclusive, because a filter that quietly drops today would be worse
    than one that is a few hours generous at the edges.
    """

    type: str | None = None
    mood_in: str | None = None
    kept: bool | None = None
    start: dt.date | None = None
    end: dt.date | None = None
    #: A failed session played nothing, so it is noise in a list of what you listened to.
    include_failed: bool = False


@dataclass(slots=True)
class Row:
    """One session as a card: the figures it prints and nothing else."""

    session: Session
    queued: int = 0
    images: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class WeekSummary:
    """The quiet line above the list. ``note`` explains an empty week rather than zeroes."""

    days: int
    sessions: int
    minutes: float
    shift_from: str | None = None
    shift_to: str | None = None
    shift_count: int = 0
    note: str | None = None


@dataclass(frozen=True, slots=True)
class Restored:
    """A playlist rebuilt from a session's stored tracks."""

    playlist_uri: str
    playlist_id: str
    name: str
    tracks: int


# --------------------------------------------------------------------- the list


def list_sessions(
    db: DbSession,
    user_id: int,
    *,
    filters: Filters | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Row], int]:
    """A page of sessions, newest first, and how many there are in total."""
    filters = filters or Filters()
    listed = db.scalars(
        _filtered(select(Session), user_id, filters)
        .order_by(Session.started_at.desc(), Session.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    total = db.scalar(
        _filtered(select(func.count()).select_from(Session), user_id, filters)
    )

    rows = [Row(session=session) for session in listed]
    _add_tracks(db, rows)
    return rows, int(total or 0)


def _filtered(statement: Select, user_id: int, filters: Filters) -> Select:
    statement = statement.where(Session.user_id == user_id)
    if not filters.include_failed:
        statement = statement.where(Session.status != STATUS_FAILED)
    if filters.type:
        statement = statement.where(Session.type == filters.type)
    if filters.mood_in:
        statement = statement.where(Session.mood_in == filters.mood_in)
    if filters.kept is not None:
        statement = statement.where(Session.kept.is_(filters.kept))
    if filters.start:
        statement = statement.where(Session.started_at >= _day_start(filters.start))
    if filters.end:
        statement = statement.where(
            Session.started_at < _day_start(filters.end + dt.timedelta(days=1))
        )
    return statement


def _day_start(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time.min, tzinfo=dt.UTC)


def _add_tracks(db: DbSession, rows: list[Row]) -> None:
    """Fill in each row's track count and first few covers in one query, not one per row."""
    if not rows:
        return
    by_id = {row.session.id: row for row in rows}
    listed = db.execute(
        select(SessionTrack.session_id, Track.image_url)
        .join(Track, Track.id == SessionTrack.track_id)
        .where(SessionTrack.session_id.in_(by_id))
        .order_by(SessionTrack.session_id, SessionTrack.position)
    ).all()

    for session_id, image_url in listed:
        row = by_id[session_id]
        row.queued += 1
        # Four different covers read as "this is what it was"; four copies of one read as a
        # rendering bug.
        if image_url and len(row.images) < ARTWORK and image_url not in row.images:
            row.images.append(image_url)


def minutes_of(session: Session) -> float:
    """How long a session ran, from its summary where it has one."""
    summary = session.summary or {}
    stored = summary.get("minutes")
    if isinstance(stored, (int, float)) and not isinstance(stored, bool):
        return round(float(stored), 1)
    started = as_utc(session.started_at)
    if started is None:
        return 0.0
    ended = as_utc(session.ended_at) or utcnow()
    return round(max(0.0, (ended - started).total_seconds()) / 60, 1)


def count_of(session: Session, key: str) -> int | None:
    """``played`` or ``skipped`` from the summary, or None while nothing has measured them."""
    value = (session.summary or {}).get(key)
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


# ------------------------------------------------------------------ week summary


def week_summary(db: DbSession, user_id: int, *, days: int = SUMMARY_DAYS) -> WeekSummary:
    """Sessions, time and the commonest mood shift over the last few days."""
    since = utcnow() - dt.timedelta(days=days)
    listed = db.scalars(
        select(Session).where(
            Session.user_id == user_id,
            Session.status != STATUS_FAILED,
            Session.started_at >= since,
        )
    ).all()

    if not listed:
        return WeekSummary(
            days=days,
            sessions=0,
            minutes=0.0,
            note=f"Nothing in the last {days} days.",
        )

    shifts = Counter(
        (session.mood_in, session.mood_out)
        for session in listed
        if session.mood_in and session.mood_out
    )
    minutes = round(sum(minutes_of(session) for session in listed), 1)

    if not shifts:
        # Real sessions, but none of them recorded both ends. Saying "no shift" would read
        # as "you did not change", which is not what the data says.
        return WeekSummary(
            days=days,
            sessions=len(listed),
            minutes=minutes,
            note="No mood shift to show: these sessions did not record both ends.",
        )

    (mood_in, mood_out), count = shifts.most_common(1)[0]
    return WeekSummary(
        days=days,
        sessions=len(listed),
        minutes=minutes,
        shift_from=mood_in,
        shift_to=mood_out,
        shift_count=count,
    )


# ---------------------------------------------------------------------- detail


def events(db: DbSession, session_id: int) -> list[SessionEvent]:
    """A session's timeline, oldest first."""
    return list(
        db.scalars(
            select(SessionEvent)
            .where(SessionEvent.session_id == session_id)
            .order_by(SessionEvent.ts, SessionEvent.id)
        ).all()
    )


def latest_restore(timeline: list[SessionEvent]) -> dict | None:
    """The last "bring it back" out of an already-read timeline, so it costs no query."""
    for event in reversed(timeline):
        if event.type == EVENT_RESTORE and event.payload:
            return dict(event.payload)
    return None


# -------------------------------------------------------------- bring it back


async def restore(
    db: DbSession,
    user_id: int,
    session: Session,
    *,
    spotify: SpotifyClient | None = None,
) -> Restored:
    """Recreate a session's playlist from our own rows.

    Deliberately a *new* playlist that stays in the library: the user asked for this one, so
    it is not the temporary kind that Chime out takes away again.
    """
    rows = sessions.track_rows(db, session.id)
    if not rows:
        raise HistoryError("This session has no songs recorded, so there is nothing to rebuild.")

    name = session.playlist_name or sessions.playlist_name(db, session)
    started = as_utc(session.started_at) or utcnow()
    description = RESTORE_DESCRIPTION.format(date=started.date().isoformat())

    client = spotify or SpotifyClient(TokenStore(SessionLocal, user_id))
    try:
        playlist = await playlists.create_playlist(client, name=name, description=description)
        if not playlist.id or not playlist.uri:
            raise HistoryError("Spotify created a playlist but did not say where it is.")
        uris = [f"spotify:track:{track.spotify_track_id}" for _, track in rows]
        await playlists.add_items(client, playlist.id, uris)
    finally:
        if spotify is None:
            await client.aclose()

    restored = Restored(
        playlist_uri=playlist.uri,
        playlist_id=playlist.id,
        name=playlist.name or name,
        tracks=len(rows),
    )
    db.add(
        SessionEvent(
            session_id=session.id,
            type=EVENT_RESTORE,
            payload={
                "playlist_uri": restored.playlist_uri,
                "playlist_id": restored.playlist_id,
                "name": restored.name,
                "tracks": restored.tracks,
            },
        )
    )
    db.commit()
    logger.info(
        "a session was brought back as a playlist",
        extra={"session_id": session.id, "tracks": restored.tracks},
    )
    return restored


# ------------------------------------------------------------------- forgetting


def delete_session(db: DbSession, session: Session) -> None:
    """Forget a session. Tracks and events go with it; Spotify is not touched.

    A kept playlist belongs to the user now, and deleting our record of a session is not
    permission to reach into their library.
    """
    if session.is_live:
        raise HistoryError("That session is still running. Chime out first.")
    db.delete(session)
    db.commit()
