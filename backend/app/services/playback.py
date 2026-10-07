"""Measuring what actually played (SPEC section 6, "while active").

Spotify has no "what happened" endpoint — only "what is happening right now" — so this is a
sampler, and everything about it follows from that:

* **Progress is not cumulative.** ``progress_ms`` is where the needle is, so a replay or a
  seek backwards would double-count. We keep the *highest* position seen, which is the
  strongest honest claim about a track from a series of snapshots.
* **A track is judged when playback leaves it**, not while it is on. So a row needs a
  ``finished_at``: ``skipped = False`` on a row that is playing right now means "nothing
  decided", and on a row that has ended means "listened to". One column removes the
  ambiguity, and makes the poller safe to restart mid-session.
* **Anything shorter than the poll interval can be missed entirely.** At 20 s that is a
  20-second interlude, which is the price of sampling. The session screen polls
  ``/api/sessions/active``, which records through here too, so a screen that is open
  measures far more finely than the scheduler alone.
* **Silence is not an ending.** A pause, a 204, or a reading that fails leaves every row
  exactly as it was. Playback comes back, and a track marked skipped because someone took a
  phone call would be a lie that then feeds the ranking for months.

The other half of the job is the behaviour counters. This is the only place
``user_tracks.plays``/``completes``/``fast_skips`` are written from listening, so it is what
finally gives :func:`app.services.ranking.behavior_boost` something to work with.

Promoting a session from ``created`` to ``active`` lives here too, rather than in the session
engine, because pressing play inside Spotify tells us nothing directly: the only evidence a
hand-started session ever gives is a snapshot showing our own playlist playing. That also
keeps the dependency pointing one way — the engine calls into measurement at Chime out, and
measurement never calls back.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.clock import utcnow
from app.integrations.spotify import player
from app.integrations.spotify.client import SpotifyClient
from app.integrations.spotify.errors import SpotifyError
from app.integrations.spotify.schemas import PlaybackState
from app.models import STATUS_ACTIVE, STATUS_CREATED, Session, SessionTrack, Track
from app.services import behavior

logger = logging.getLogger(__name__)

#: SPEC: a skip is "moved on before ~10 s or before 30% played". Anything over about half a
#: minute long makes the fraction the binding one, so the floor only matters for short
#: tracks — where 30% of 20 seconds would call six seconds a listen.
SKIP_FRACTION = 0.30
MIN_LISTEN_MS = 10_000

#: A track with no duration in our cache: fall back to the flat floor rather than to a
#: fraction of zero, which would count every play as complete.
UNKNOWN_DURATION_MS = 0


@dataclass(frozen=True, slots=True)
class Observation:
    """What one snapshot changed. Mostly for tests, logs and the dev API to read."""

    #: Position of the row playback is on, if it is one of ours.
    playing: int | None = None
    #: Rows judged by this snapshot, and which of them were judged skips.
    finished: tuple[int, ...] = ()
    skipped: tuple[int, ...] = ()
    #: Playing, but not out of this session's playlist.
    off_context: bool = False
    #: Nothing playing at all, or a track we do not have a row for.
    idle: bool = False
    #: This snapshot is what turned a hand-started session active.
    promoted: bool = False


def record(db: DbSession, session: Session, state: PlaybackState | None) -> Observation:
    """Fold one playback snapshot into this session's rows.

    Called from two places on purpose: the scheduler's tick, and every
    ``GET /api/sessions/active`` the session screen makes. Both hand over the same snapshot
    they already had, so measuring costs no extra Spotify requests anywhere.
    """
    if state is None or not state.is_playing:
        # Paused, stopped, or Spotify said nothing. Leave every row alone: playback comes
        # back, and a pause is not a skip.
        return Observation(idle=True)

    context_uri = state.context.uri if state.context else None
    # A hand-started session announces itself here and nowhere else.
    promoted = promote(db, session, context_uri=context_uri)

    if session.playlist_uri and context_uri and context_uri != session.playlist_uri:
        # They have wandered off to something else. Nothing to measure, and nothing to judge
        # either: whatever we were on is still where we left it, in case they come back.
        return Observation(off_context=True)

    current = _current_row(db, session, state.track_id)
    if current is None:
        return Observation(idle=True, promoted=promoted)

    now = utcnow()
    finished, skipped = _finish_others(db, session, keep=current.id, at=now)

    if current.started_at is None:
        current.started_at = now
    progress = max(0, state.progress_ms or 0)
    if progress > current.played_ms:
        current.played_ms = progress
    db.commit()

    return Observation(
        playing=current.position,
        finished=tuple(finished),
        skipped=tuple(skipped),
        promoted=promoted,
    )


def promote(db: DbSession, session: Session, *, context_uri: str | None) -> bool:
    """Move a session the user started by hand from ``created`` to ``active``.

    Pressing play inside Spotify never reaches us, so the first snapshot showing our own
    playlist playing is the whole of the evidence that a session began.
    """
    if session.status != STATUS_CREATED or not session.playlist_uri:
        return False
    if context_uri != session.playlist_uri:
        return False
    session.status = STATUS_ACTIVE
    db.commit()
    db.refresh(session)
    logger.info("a session was started from Spotify", extra={"session_id": session.id})
    return True


async def poll(
    db: DbSession, session: Session, *, spotify: SpotifyClient
) -> Observation | None:
    """Read playback once and record it. ``None`` when Spotify could not be read.

    The distinction matters: "nothing is playing" is a measurement, and "Spotify did not
    answer" is not, and neither of them is a reason to touch a row.
    """
    try:
        state = await player.get_playback_state(spotify)
    except SpotifyError as exc:
        logger.info(
            "could not read playback while polling",
            extra={"session_id": session.id, "error": exc.message},
        )
        return None
    return record(db, session, state)


def finish_open(db: DbSession, session: Session, *, at: datetime | None = None) -> list[int]:
    """Close off whatever was still playing. Chime out's last act of measurement.

    Without this the track playing when someone chimes out would stay open for ever, since
    nothing ever moves off it, and it would never count towards ``played``.

    Deliberately *unjudged*: a session ended half way through a track is the user finishing
    with Chime, not rejecting the song. Marking that a skip would put a black mark against
    whatever tends to be playing at bedtime, every single night, and the ranking would slowly
    learn to avoid it.
    """
    moment = at or utcnow()
    finished, _ = _finish_others(db, session, keep=None, at=moment, judge=False)
    if finished:
        db.commit()
    return finished


def is_skip(played_ms: int, duration_ms: int) -> bool:
    """SPEC's rule, in one place so the poller and the reports cannot disagree."""
    if duration_ms <= UNKNOWN_DURATION_MS:
        return played_ms < MIN_LISTEN_MS
    return played_ms < max(MIN_LISTEN_MS, duration_ms * SKIP_FRACTION)


def counts(db: DbSession, session_id: int) -> tuple[int, int]:
    """``(played, skipped)`` for a session, as the summary and the screens report them."""
    rows = db.scalars(select(SessionTrack).where(SessionTrack.session_id == session_id)).all()
    return (
        sum(1 for row in rows if row.started_at is not None),
        sum(1 for row in rows if row.skipped),
    )


def recent_skips(
    db: DbSession, session_id: int, *, window: int = 5, since: datetime | None = None
) -> tuple[int, int]:
    """Skips out of the last few *judged* tracks — SPEC's "3+ skips in the last 5".

    Judged rather than started, because the track playing right now has not had its chance
    yet and counting it as a non-skip would hide a run of skips from the trigger.

    ``since`` is how adaptation avoids reacting to the same run of skips every five minutes:
    the skips that caused an adaptation are already answered, and only what happened after it
    is news.
    """
    statement = select(SessionTrack).where(
        SessionTrack.session_id == session_id, SessionTrack.finished_at.is_not(None)
    )
    if since is not None:
        statement = statement.where(SessionTrack.finished_at > since)
    rows = db.scalars(
        statement.order_by(SessionTrack.finished_at.desc(), SessionTrack.id.desc()).limit(window)
    ).all()
    return sum(1 for row in rows if row.skipped), len(rows)


# ------------------------------------------------------------------- internals


def _current_row(db: DbSession, session: Session, spotify_track_id: str | None) -> SessionTrack | None:
    """The row for the track playing now, preferring one that has not been judged yet.

    A session can hold the same track twice (History's "bring it back" can rebuild anything,
    and a short library repeats), so identity by Spotify id is ambiguous. The first unjudged
    row is the right guess: playback walks the playlist in order.
    """
    if not spotify_track_id:
        return None
    rows = db.execute(
        select(SessionTrack)
        .join(Track, Track.id == SessionTrack.track_id)
        .where(
            SessionTrack.session_id == session.id,
            Track.spotify_track_id == spotify_track_id,
        )
        .order_by(SessionTrack.position)
    ).scalars().all()
    if not rows:
        return None
    return next((row for row in rows if row.finished_at is None), rows[-1])


def _finish_others(
    db: DbSession, session: Session, *, keep: int | None, at: datetime, judge: bool = True
) -> tuple[list[int], list[int]]:
    """Close every started-but-unjudged row except the one playing now.

    Usually that is exactly one row — the track we have just moved off. It can be more after
    a restart, or when several tracks went by between two polls, and those are judged on
    whatever we last saw of them, which is the honest answer rather than a guess.

    ``judge=False`` closes a row without deciding anything about it and without touching the
    behaviour counters. Chime out uses it (see :func:`finish_open`).
    """
    rows = db.execute(
        select(SessionTrack, Track)
        .join(Track, Track.id == SessionTrack.track_id)
        .where(
            SessionTrack.session_id == session.id,
            SessionTrack.started_at.is_not(None),
            SessionTrack.finished_at.is_(None),
        )
        .order_by(SessionTrack.position)
    ).all()

    finished: list[int] = []
    skipped: list[int] = []
    for row, track in rows:
        if keep is not None and row.id == keep:
            continue
        row.finished_at = at
        finished.append(row.position)
        if not judge:
            continue
        row.skipped = is_skip(row.played_ms, track.duration_ms)
        if row.skipped:
            skipped.append(row.position)
        behavior.record_finish(
            db,
            session.user_id,
            row.track_id,
            played_ms=row.played_ms,
            skipped=row.skipped,
            at=at,
        )
    return finished, skipped
