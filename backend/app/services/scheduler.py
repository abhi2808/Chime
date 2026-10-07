"""The live loop: three background jobs that keep a session honest (SPEC section 6).

* **Playback**, every ``PLAYBACK_POLL_SECONDS`` (20). Reads what is playing and folds it into
  the session's rows, which is the only way the behaviour counters and ``played``/``skipped``
  ever get written. Also what notices a session someone started by hand in Spotify.
* **Adaptation**, every ``SESSION_POLL_SECONDS`` (300). Checks SPEC's four triggers and changes
  what is coming up if any of them fired.
* **WHOOP**, every ``WHOOP_POLL_SECONDS`` (900). Refreshes body data so a recovery or day_part
  change can *be* a trigger, rather than being noticed only when the next session starts.

Three things this is deliberately careful about:

**One failing session must not stop the others.** Every job iterates users, and each iteration
is wrapped: a Spotify grant that has expired on one account, or a WHOOP outage, logs and the
loop carries on. An exception escaping a job would only be logged by APScheduler anyway, but
it would abandon every session after the failing one.

**Nothing here polls for a user who is not listening.** All three jobs work from the list of
live sessions, so an idle Chime makes no outbound requests at all. That is what keeps a
20-second poll inside Spotify's rate limit and a 15-minute WHOOP poll inside 10,000 a day.

**It must be safe to run none of it.** ``ENABLE_SCHEDULER=false`` turns the whole thing off,
which is how the tests run and how a second process avoids polling the same session twice.
Everything still works without it, just more coarsely: ``GET /api/sessions/active`` records
playback from the snapshot it already fetches, so a session with its screen open is measured
whether the scheduler exists or not. Only adaptation genuinely needs the loop.
"""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.config import settings
from app.db.session import SessionLocal
from app.integrations.spotify.client import SpotifyClient
from app.integrations.spotify.errors import SpotifyError
from app.integrations.whoop.errors import WhoopAuthError
from app.models import EVENT_WHOOP_REFRESH, LIVE_STATUSES, Session, SessionEvent
from app.services import adaptation, playback, whoop_sync
from app.services.token_store import TokenStore

logger = logging.getLogger(__name__)

JOB_PLAYBACK = "playback"
JOB_ADAPT = "adapt"
JOB_WHOOP = "whoop"

_scheduler: AsyncIOScheduler | None = None


def start() -> AsyncIOScheduler | None:
    """Start the loop, or return ``None`` when it is switched off.

    ``coalesce`` and ``max_instances=1`` between them mean a slow tick is skipped rather than
    queued: two playback polls running at once would race on the same rows, and a backlog of
    them after a laptop wakes from sleep would all be reporting the same snapshot anyway.
    """
    global _scheduler
    if not settings.enable_scheduler:
        logger.info("the live loop is switched off (ENABLE_SCHEDULER)")
        return None
    if _scheduler is not None:
        return _scheduler

    scheduler = AsyncIOScheduler(
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 60}
    )
    scheduler.add_job(
        tick_playback, "interval", seconds=settings.playback_poll_seconds, id=JOB_PLAYBACK
    )
    scheduler.add_job(
        tick_adaptation, "interval", seconds=settings.session_poll_seconds, id=JOB_ADAPT
    )
    scheduler.add_job(tick_whoop, "interval", seconds=settings.whoop_poll_seconds, id=JOB_WHOOP)
    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "the live loop is running",
        extra={
            "playback_seconds": settings.playback_poll_seconds,
            "session_seconds": settings.session_poll_seconds,
            "whoop_seconds": settings.whoop_poll_seconds,
        },
    )
    return scheduler


def shutdown() -> None:
    """Stop the loop. ``wait=False`` so a shutdown is not held up by a poll in flight."""
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
    logger.info("the live loop has stopped")


# ----------------------------------------------------------------------- ticks


async def tick_playback() -> int:
    """Read playback for every live session. Returns how many were read.

    One Spotify client per session rather than one per tick: a client is bound to a user's
    tokens, and on a personal app "every live session" is almost always exactly one.
    """
    read = 0
    for session_id, user_id in _live_sessions():
        try:
            read += await _poll_one(session_id, user_id)
        except Exception:  # noqa: BLE001 - a job that raises abandons the sessions after it
            logger.exception("playback poll failed", extra={"session_id": session_id})
    return read


async def _poll_one(session_id: int, user_id: int) -> int:
    client = SpotifyClient(TokenStore(SessionLocal, user_id))
    try:
        with SessionLocal() as db:
            session = db.get(Session, session_id)
            if session is None or not session.is_live:
                # Chimed out between listing the sessions and getting here.
                return 0
            observed = await playback.poll(db, session, spotify=client)
        return 0 if observed is None else 1
    except SpotifyError as exc:
        # Typed failures are expected weather: a paused account, a revoked grant, a 502 from
        # Spotify. None of them is a reason to touch a row or to stop the loop.
        logger.info(
            "could not poll playback",
            extra={"session_id": session_id, "error": exc.message},
        )
        return 0
    finally:
        await client.aclose()


async def tick_adaptation() -> int:
    """Give every live session a chance to change its mind. Returns how many did."""
    adapted = 0
    for session_id, user_id in _live_sessions():
        try:
            adapted += await _adapt_one(session_id, user_id)
        except Exception:  # noqa: BLE001
            logger.exception("adaptation failed", extra={"session_id": session_id})
    return adapted


async def _adapt_one(session_id: int, user_id: int) -> int:
    client = SpotifyClient(TokenStore(SessionLocal, user_id))
    try:
        with SessionLocal() as db:
            session = db.get(Session, session_id)
            if session is None or not session.is_live:
                return 0
            result = await adaptation.adapt(db, session, spotify=client)
        return 0 if result is None else 1
    except SpotifyError as exc:
        # The playlist edit failed. The session plays on with what it already has, which is
        # a worse mix than intended but still a mix; the next tick will try again.
        logger.info(
            "could not adapt a session",
            extra={"session_id": session_id, "error": exc.message},
        )
        return 0
    finally:
        await client.aclose()


async def tick_whoop() -> int:
    """Refresh WHOOP for everyone with a session running. Returns how many changed.

    Only for live sessions, and only when the cache is stale — ``refresh_body_data`` decides
    that. Everywhere else, body data is read on demand at Chime in, so polling a user who is
    not listening would spend WHOOP's budget on an answer nobody asked for.
    """
    changed = 0
    for user_id, session_ids in _live_by_user().items():
        try:
            result = await whoop_sync.refresh_body_data(user_id)
        except WhoopAuthError:
            # Only the user can fix a dead grant, and the app already tells them so when they
            # next look at the body card. Nothing to do here but not crash.
            logger.info("whoop needs reconnecting", extra={"user_id": user_id})
            continue
        except Exception:  # noqa: BLE001
            logger.exception("whoop poll failed", extra={"user_id": user_id})
            continue

        if result.skipped or not result.ok or not (result.days or result.workouts):
            # Nothing new. Writing an event here would fill a session's timeline with
            # "refreshed WHOOP" every fifteen minutes and say nothing.
            continue
        changed += 1
        await asyncio.to_thread(_record_refresh, session_ids, result)
    return changed


def _record_refresh(session_ids: list[int], result: whoop_sync.RefreshResult) -> None:
    """Note on each live session that its body data moved underneath it.

    Worth recording because it is the honest explanation for an adaptation that follows: the
    session's energy changed and the user did nothing.
    """
    with SessionLocal() as db:
        for session_id in session_ids:
            db.add(
                SessionEvent(
                    session_id=session_id,
                    type=EVENT_WHOOP_REFRESH,
                    payload={"days": result.days, "workouts": result.workouts},
                )
            )
        db.commit()


# --------------------------------------------------------------------- helpers


def _live_sessions() -> list[tuple[int, int]]:
    """``(session_id, user_id)`` for every session in progress.

    Ids rather than rows, and the session closed before any await: each job opens its own
    short-lived database session per item, so nothing here holds a connection open across a
    Spotify request.
    """
    with SessionLocal() as db:
        return [(row.id, row.user_id) for row in _live(db)]


def _live_by_user() -> dict[int, list[int]]:
    grouped: dict[int, list[int]] = {}
    for session_id, user_id in _live_sessions():
        grouped.setdefault(user_id, []).append(session_id)
    return grouped


def _live(db: DbSession) -> list[Session]:
    return list(
        db.scalars(
            select(Session).where(Session.status.in_(LIVE_STATUSES)).order_by(Session.id)
        ).all()
    )
