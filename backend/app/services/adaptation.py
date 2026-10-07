"""Changing a session's mind part way through (SPEC section 6, "while active").

SPEC gives four triggers and one action. The triggers: a mood re-check, a readiness or
day_part change, three skips in the last five, or fewer than three tracks left to play. The
action: append new tracks, and remove *upcoming unplayed* ones — never replace a playlist
while it is playing.

Three rules hold the whole thing together:

* **Only react to what has happened since the last adaptation.** Otherwise the same run of
  skips, or the same mood check, would re-trigger every five minutes for the rest of the
  session and the mix would churn. The last ``adapt`` event is the watermark for all four
  triggers, which is why they are read from one event rather than one rule at a time.
* **Add before removing.** A failed append then leaves the playlist exactly as it was; a
  failed removal leaves a longer playlist whose old tracks still play. Removing first and then
  failing to add would leave someone listening to a playlist that runs out.
* **Continue the curve, do not restart it.** An adaptation fills the tail of a session, so it
  samples the target curve from where the session has got to. A fresh ``profile.curve(count)``
  would start the ramp again — dropping a workout back to its opening energy half an hour in.

What an adaptation does *not* touch: anything already played, the track playing now, and
``sessions.target_profile`` — the profile on the row is the brief the session began with,
which is a fact about how it started and stays true. Each adaptation records its own numbers
on its own ``adapt`` event instead.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.core.clock import as_utc
from app.integrations.spotify import playlists
from app.integrations.spotify.client import SpotifyClient
from app.models import (
    EVENT_ADAPT,
    EVENT_MOOD_CHECK,
    STATUS_ACTIVE,
    TRACK_SOURCE_ADAPT,
    Session,
    SessionEvent,
    SessionTrack,
)
from app.services import body_state, playback, ranking, sessions
from app.services.profile_rules import TargetProfile, build_profile

logger = logging.getLogger(__name__)

#: SPEC's trigger names, as they appear on the ``adapt`` event payload.
TRIGGER_MOOD = "mood"
TRIGGER_BODY = "body"
TRIGGER_SKIPS = "skips"
TRIGGER_RUNNING_OUT = "running_out"

#: SPEC: "fewer than 3 upcoming tracks" and "3+ skips in the last 5".
MIN_UPCOMING = 3
SKIP_WINDOW = 5
SKIP_TRIGGER = 3

#: How many unplayed tracks an adaptation aims to leave ahead of the listener. Enough that the
#: next one is not immediately due again, few enough that a mood check five minutes later is
#: not fighting twenty tracks nobody asked for.
TARGET_UPCOMING = 10

#: The triggers that mean the *plan* changed rather than the queue running low. Only these
#: clear out what was coming; the others just top it up.
REPLANNING_TRIGGERS = frozenset({TRIGGER_MOOD, TRIGGER_BODY, TRIGGER_SKIPS})


@dataclass(frozen=True, slots=True)
class Result:
    """What one adaptation did, as recorded on the event and returned to the caller."""

    triggers: tuple[str, ...]
    added: int
    removed: int
    mood: str | None = None
    readiness: str | None = None
    day_part: str | None = None
    #: The fresh profile's plain-language reasons, so the timeline can say why.
    notes: tuple[str, ...] = field(default_factory=tuple)


async def adapt(
    db: DbSession, session: Session, *, spotify: SpotifyClient, force: bool = False
) -> Result | None:
    """Evaluate the triggers and, if any fired, change what is coming up.

    ``None`` means nothing needed doing, which is the usual answer: on a session that is going
    well this runs every five minutes and does nothing at all.
    """
    if session.status != STATUS_ACTIVE or not session.playlist_id:
        # A session still at `created` is not playing, so there is no "upcoming" to change and
        # no reason to edit a playlist the user may be one tap away from starting.
        return None

    last = _last_adapt(db, session)
    since = as_utc(last.ts) if last is not None else None
    state = body_state.build(db, session.user_id)  # local only; the WHOOP poller refreshes
    mood = _current_mood(db, session)
    upcoming = _upcoming(db, session)
    triggers = _triggers(db, session, state=state, last=last, since=since, upcoming=upcoming)
    if not triggers and not force:
        return None

    # Only a change of plan throws away what was coming. Running low just adds to it.
    replanning = force or bool(REPLANNING_TRIGGERS & set(triggers))
    trimming = upcoming if replanning else []
    wanted = TARGET_UPCOMING - (len(upcoming) - len(trimming))
    if wanted <= 0:
        return None

    profile = build_profile(state, mood=mood, session_type=session.type, intent=session.intent)
    order = _choose(db, session, profile, count=wanted)
    if not order:
        # A library too small to fill the tail with anything it has not already used. Leave
        # the session exactly as it is: repeating what was just skipped would be worse.
        logger.info(
            "an adaptation found nothing new to add",
            extra={"session_id": session.id, "triggers": list(triggers)},
        )
        return None

    # Add first: a failed append leaves the playlist untouched, where a failed removal only
    # leaves it longer than intended and still playing.
    await playlists.add_items(
        spotify,
        session.playlist_id,
        [f"spotify:track:{item.candidate.spotify_track_id}" for item in order],
    )
    if trimming:
        await playlists.remove_items(
            spotify, session.playlist_id, [_uri_of(row) for row in trimming]
        )

    result = Result(
        triggers=triggers,
        added=len(order),
        removed=len(trimming),
        mood=mood,
        readiness=state.readiness,
        day_part=state.day_part,
        notes=profile.notes,
    )
    _persist(db, session, order=order, trimmed=trimming, result=result, profile=profile)
    logger.info(
        "adapted a session",
        extra={
            "session_id": session.id,
            "triggers": list(triggers),
            "added": result.added,
            "removed": result.removed,
        },
    )
    return result


# -------------------------------------------------------------------- triggers


def _triggers(
    db: DbSession,
    session: Session,
    *,
    state: body_state.BodyState,
    last: SessionEvent | None,
    since: datetime | None,
    upcoming: list[SessionTrack],
) -> tuple[str, ...]:
    """Which of SPEC's four conditions are true *and* new since the last adaptation."""
    fired: list[str] = []

    if _mood_checked_since(db, session, since=since):
        fired.append(TRIGGER_MOOD)

    previous = _previous_body(session, last=last)
    if previous is not None and previous != (state.readiness, state.day_part):
        fired.append(TRIGGER_BODY)

    skips, judged = playback.recent_skips(db, session.id, window=SKIP_WINDOW, since=since)
    if judged >= SKIP_TRIGGER and skips >= SKIP_TRIGGER:
        fired.append(TRIGGER_SKIPS)

    if len(upcoming) < MIN_UPCOMING:
        fired.append(TRIGGER_RUNNING_OUT)

    return tuple(fired)


def _last_adapt(db: DbSession, session: Session) -> SessionEvent | None:
    """The most recent adaptation: both the watermark and the plan currently in force."""
    return db.scalar(
        select(SessionEvent)
        .where(SessionEvent.session_id == session.id, SessionEvent.type == EVENT_ADAPT)
        .order_by(SessionEvent.ts.desc(), SessionEvent.id.desc())
        .limit(1)
    )


def _mood_checked_since(db: DbSession, session: Session, *, since: datetime | None) -> bool:
    statement = select(SessionEvent.id).where(
        SessionEvent.session_id == session.id, SessionEvent.type == EVENT_MOOD_CHECK
    )
    if since is not None:
        statement = statement.where(SessionEvent.ts > since)
    return db.scalar(statement.limit(1)) is not None


def _current_mood(db: DbSession, session: Session) -> str | None:
    """The mood to rank against: the latest re-check, else the one Chime in was given.

    Not filtered by ``since``: an old mood check is not a *trigger* any more, but it is still
    the most recent thing the user said about how they feel, and a top-up should honour it.
    """
    event = db.scalar(
        select(SessionEvent)
        .where(SessionEvent.session_id == session.id, SessionEvent.type == EVENT_MOOD_CHECK)
        .order_by(SessionEvent.ts.desc(), SessionEvent.id.desc())
        .limit(1)
    )
    mood = (event.payload or {}).get("mood") if event is not None else None
    return str(mood) if mood else session.mood_in


def _previous_body(
    session: Session, *, last: SessionEvent | None
) -> tuple[str | None, str | None] | None:
    """The body state the plan in force was made against: the last adaptation's, else the
    session's own start.

    ``None`` when neither records anything to compare, which stops a missing reading from
    reading as a change. ``body_in`` always carries a day_part, so in practice this only
    happens to a session whose start was never snapshotted.
    """
    payload = (last.payload or {}) if last is not None else (session.body_in or {})
    readiness = payload.get("readiness")
    day_part = payload.get("day_part")
    if readiness is None and day_part is None:
        return None
    return (
        str(readiness) if readiness is not None else None,
        str(day_part) if day_part is not None else None,
    )


# ---------------------------------------------------------------------- doing it


def _upcoming(db: DbSession, session: Session) -> list[SessionTrack]:
    """Rows nothing has played yet, in playing order.

    ``started_at is None`` is the whole definition, and it is why the poller writes that column
    even for a track nobody skipped: it is what separates "coming up" from "already happened"
    without having to trust a position against Spotify's own cursor.
    """
    return list(
        db.scalars(
            select(SessionTrack)
            .where(SessionTrack.session_id == session.id, SessionTrack.started_at.is_(None))
            .order_by(SessionTrack.position)
        ).all()
    )


def _choose(
    db: DbSession, session: Session, profile: TargetProfile, *, count: int
) -> list[ranking.Ranked]:
    """Rank fresh candidates for the tail of the session.

    Everything this session has already used is excluded outright rather than left to the
    freshness component to discourage: a track that was just skipped coming straight back
    would read as a bug, however well it scores.
    """
    used = set(
        db.scalars(
            select(SessionTrack.track_id).where(SessionTrack.session_id == session.id)
        ).all()
    )
    pool = [
        candidate
        for candidate in ranking.candidates_for(db, session.user_id)
        if candidate.track_id not in used
    ]
    if not pool:
        return []

    played = _played_count(db, session)
    # Sample the curve over the session as it will end up, and take only the part still ahead,
    # so the shape carries on from here instead of starting again.
    curve = profile.curve(played + count)[played:]
    return ranking.rank(
        pool,
        profile,
        count=count,
        recent_track_ids=sessions.recent_track_ids(db, session.user_id),
        curve=curve,
    )


def _played_count(db: DbSession, session: Session) -> int:
    """How far into the session we are, counted in tracks that have had their turn."""
    return int(
        db.scalar(
            select(func.count(SessionTrack.id)).where(
                SessionTrack.session_id == session.id, SessionTrack.started_at.is_not(None)
            )
        )
        or 0
    )


def _persist(
    db: DbSession,
    session: Session,
    *,
    order: list[ranking.Ranked],
    trimmed: list[SessionTrack],
    result: Result,
    profile: TargetProfile,
) -> None:
    """Write the new rows, drop the trimmed ones, and record the event.

    Trimmed rows are deleted rather than flagged: nobody ever heard them, and keeping them
    would put songs into History's record of what was listened to. Positions are not
    renumbered — ``position`` is only ever used for ordering, so the gaps cost nothing.
    """
    shape = profile.as_dict(positions=1)
    next_position = 1 + int(
        db.scalar(
            select(func.max(SessionTrack.position)).where(
                SessionTrack.session_id == session.id
            )
        )
        or 0
    )
    for offset, item in enumerate(order):
        db.add(
            SessionTrack(
                session_id=session.id,
                position=next_position + offset,
                track_id=item.candidate.track_id,
                source=TRACK_SOURCE_ADAPT,
                score_breakdown={**item.breakdown, "target": item.target},
            )
        )
    for row in trimmed:
        db.delete(row)

    db.add(
        SessionEvent(
            session_id=session.id,
            type=EVENT_ADAPT,
            # Numbers, moods and body state only: no track or artist names anywhere near a
            # payload that an LLM might later be asked to summarise (CLAUDE.md rule 7).
            payload={
                "triggers": list(result.triggers),
                "added": result.added,
                "removed": result.removed,
                "mood": result.mood,
                "readiness": result.readiness,
                "day_part": result.day_part,
                "energy_start": shape["energy_start"],
                "energy_end": shape["energy_end"],
                "notes": list(result.notes),
            },
        )
    )
    db.commit()
    db.refresh(session)


def _uri_of(row: SessionTrack) -> str:
    """A session row's Spotify URI. ``SessionTrack.track`` is eager-loaded, so this is free."""
    return f"spotify:track:{row.track.spotify_track_id}"
