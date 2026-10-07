"""The behaviour counters on ``user_tracks`` (SPEC section 5, step 5).

These four numbers — ``plays``, ``completes``, ``fast_skips``, ``kept_count`` — are the only
learning in Chime, and they are plain arithmetic rather than a model: a completion counts 1,
keeping a playlist counts 2, a fast skip costs 2, and the whole thing decays with a 60-day
half life in :func:`app.services.ranking.behavior_boost`. Nothing here trains anything, and
no Spotify content leaves the database, which is what CLAUDE.md rule 7 requires.

Until phase 6 nothing wrote them, so ``behavior_boost`` answered "no evidence either way"
for every track in the library and 15% of the score was inert. This module is where that
stops. It is deliberately separate from the poller that calls it, so that Chime out can bump
``kept_count`` without the session engine and the poller having to import each other.

A (user, track) pair can own several ``user_tracks`` rows — SPEC keys them by source, so a
track that is both liked and in a playlist appears twice. Behaviour is a fact about the
track, not about where it was found, so every row for the pair gets the same update.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.clock import utcnow
from app.models import Session, SessionTrack, UserTrack

logger = logging.getLogger(__name__)

#: SPEC section 5: a skip under 10 seconds is the one that says "not this".
FAST_SKIP_MS = 10_000


def record_finish(
    db: DbSession,
    user_id: int,
    track_id: int,
    *,
    played_ms: int,
    skipped: bool,
    at: datetime | None = None,
) -> None:
    """One track has been listened to and judged. Bumps the counters for it.

    ``plays`` counts every track that started, whatever happened next, so it stays a
    denominator. ``completes`` and ``fast_skips`` are the two the score actually reads, and
    a skip somewhere in the middle counts as neither: it is weak evidence at best, and
    treating "I'd had enough after two minutes" as a rejection would be wrong.
    """
    rows = db.scalars(
        select(UserTrack).where(UserTrack.user_id == user_id, UserTrack.track_id == track_id)
    ).all()
    if not rows:
        # A track played from our playlist that is no longer in the library: the user
        # unliked it mid-session, or it arrived from somewhere we do not track. Nothing to
        # count it against, and inventing a row would put it back in the candidate pool.
        return

    moment = at or utcnow()
    for row in rows:
        row.plays += 1
        row.last_played_at = moment
        if not skipped:
            row.completes += 1
        elif played_ms < FAST_SKIP_MS:
            row.fast_skips += 1
    db.commit()


def record_keep(db: DbSession, session: Session) -> int:
    """The user kept this session's playlist, so every track in it earns a keep.

    Worth twice a completion in the score: pressing keep is a deliberate statement about a
    whole mix, where listening through a track is only the absence of a skip. Counted once
    per session — a kept playlist is one decision, however many times it is played later.
    """
    track_ids = list(
        db.scalars(select(SessionTrack.track_id).where(SessionTrack.session_id == session.id)).all()
    )
    if not track_ids:
        return 0
    rows = db.scalars(
        select(UserTrack).where(
            UserTrack.user_id == session.user_id, UserTrack.track_id.in_(track_ids)
        )
    ).all()
    for row in rows:
        row.kept_count += 1
    db.commit()
    logger.info(
        "counted a kept playlist towards behaviour",
        extra={"session_id": session.id, "tracks": len(track_ids)},
    )
    return len(track_ids)
