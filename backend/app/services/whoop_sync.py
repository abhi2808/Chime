"""Pull WHOOP into ``whoop_daily`` and ``whoop_workouts``.

:func:`refresh_body_data` is deliberately the only entry point. A poller, a webhook (once
there is public HTTPS to receive one) and an on-demand read from the body-state endpoint
all call the same function, so there is one code path to reason about.

What WHOOP actually gives us, and what that means here:

* A **cycle** is a physiological day that starts when you wake, so it lines up with
  neither UTC midnight nor the server's timezone. The cycle with no ``end`` is today, and
  its strain climbs through the day — that is the one figure worth re-reading often.
* **Recovery** is scored once, after a sleep, and links a cycle to the sleep it came
  from. That link is how sleep performance gets attached to the right day.
* **Workouts** appear only once finished. There is no live workout and no live heart
  rate, so "minutes since last workout" is the closest thing to a live signal we have.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import as_utc, utcnow
from app.core.config import settings
from app.db.session import SessionLocal
from app.integrations.whoop import api as whoop_api
from app.integrations.whoop.client import WhoopClient
from app.integrations.whoop.errors import WhoopAuthError, WhoopError
from app.integrations.whoop.schemas import Cycle, Recovery, Sleep, Workout, utc
from app.models import OAuthToken, WhoopDaily, WhoopWorkout
from app.services.token_store import TokenStore

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]

PROVIDER = "whoop"


@dataclass(slots=True)
class RefreshResult:
    """What a refresh did, so callers can report honestly rather than guess."""

    days: int = 0
    workouts: int = 0
    skipped: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def is_connected(db: Session, user_id: int) -> bool:
    return (
        db.scalar(
            select(OAuthToken.id).where(
                OAuthToken.user_id == user_id, OAuthToken.provider == PROVIDER
            )
        )
        is not None
    )


def latest_day(db: Session, user_id: int) -> WhoopDaily | None:
    """The most recent stored WHOOP day, which is normally the one in progress."""
    return db.scalar(
        select(WhoopDaily)
        .where(WhoopDaily.user_id == user_id)
        .order_by(WhoopDaily.date.desc())
        .limit(1)
    )


def is_fresh(day: WhoopDaily | None, *, ttl_seconds: int | None = None) -> bool:
    if day is None:
        return False
    ttl = settings.body_state_ttl_seconds if ttl_seconds is None else ttl_seconds
    fetched_at = as_utc(day.fetched_at)
    return fetched_at is not None and utcnow() - fetched_at < timedelta(seconds=ttl)


async def refresh_body_data(
    user_id: int,
    *,
    force: bool = False,
    session_factory: SessionFactory = SessionLocal,
) -> RefreshResult:
    """Read the last couple of days from WHOOP and store what the engine needs.

    Returns rather than raises for anything except a broken connection: a mix should
    still be buildable from mood and time of day when WHOOP is having a bad morning.
    """
    if not force:
        fresh = await asyncio.to_thread(_cached_is_fresh, session_factory, user_id)
        if fresh:
            return RefreshResult(skipped=True)

    since = utcnow() - timedelta(hours=settings.whoop_lookback_hours)
    tokens = TokenStore(session_factory, user_id, PROVIDER)

    try:
        async with WhoopClient(tokens) as client:
            cycles = await whoop_api.get_cycles(client, start=since)
            recoveries = await whoop_api.get_recoveries(client, start=since)
            sleeps = await whoop_api.get_sleeps(client, start=since)
            workouts = await whoop_api.get_workouts(client, start=since)
    except WhoopAuthError:
        # The grant is gone; the user has to reconnect and only they can fix it.
        raise
    except WhoopError as exc:
        logger.warning(
            "whoop refresh failed, serving what is already stored",
            extra={"user_id": user_id, "error": exc.message},
        )
        return RefreshResult(error=exc.message)

    days, saved_workouts = await asyncio.to_thread(
        _persist, session_factory, user_id, cycles, recoveries, sleeps, workouts
    )
    logger.info(
        "whoop refreshed",
        extra={"user_id": user_id, "days": days, "workouts": saved_workouts},
    )
    return RefreshResult(days=days, workouts=saved_workouts)


def _cached_is_fresh(session_factory: SessionFactory, user_id: int) -> bool:
    with session_factory() as db:
        return is_fresh(latest_day(db, user_id))


def _persist(
    session_factory: SessionFactory,
    user_id: int,
    cycles: Sequence[Cycle],
    recoveries: Sequence[Recovery],
    sleeps: Sequence[Sleep],
    workouts: Sequence[Workout],
) -> tuple[int, int]:
    with session_factory() as db:
        days = _upsert_days(db, user_id, cycles, recoveries, sleeps)
        saved = _upsert_workouts(db, user_id, workouts)
        db.commit()
        return days, saved


def _upsert_days(
    db: Session,
    user_id: int,
    cycles: Sequence[Cycle],
    recoveries: Sequence[Recovery],
    sleeps: Sequence[Sleep],
) -> int:
    recovery_by_cycle = {r.cycle_id: r for r in recoveries if r.cycle_id}
    sleep_by_id = {s.id: s for s in sleeps if s.id}

    written = 0
    for cycle in cycles:
        day_date = cycle.local_date
        if day_date is None:
            continue

        row = db.scalar(
            select(WhoopDaily).where(
                WhoopDaily.user_id == user_id, WhoopDaily.date == day_date
            )
        )
        if row is None:
            row = WhoopDaily(user_id=user_id, date=day_date)
            db.add(row)

        row.cycle_id = cycle.id
        row.timezone_offset = cycle.timezone_offset
        row.cycle_open = cycle.is_open
        # Only overwrite with a real number. An unscored re-read of a day we already
        # scored must not blank it out.
        _set_if_known(row, "day_strain", cycle.strain)

        recovery = recovery_by_cycle.get(cycle.id) if cycle.id else None
        values = recovery.scored_values if recovery else None
        if values is not None:
            _set_if_known(row, "recovery", values.recovery_score)
            _set_if_known(row, "hrv_ms", values.hrv_rmssd_milli)
            _set_if_known(row, "rhr", values.resting_heart_rate)
            _set_if_known(row, "spo2", values.spo2_percentage)
            _set_if_known(row, "skin_temp_c", values.skin_temp_celsius)
            row.calibrating = values.user_calibrating

        sleep = _sleep_for(cycle, recovery, sleep_by_id, sleeps)
        if sleep is not None:
            _set_if_known(row, "sleep_performance", sleep.performance)

        row.fetched_at = utcnow()
        written += 1
    return written


def _sleep_for(
    cycle: Cycle,
    recovery: Recovery | None,
    sleep_by_id: dict[str, Sleep],
    sleeps: Iterable[Sleep],
) -> Sleep | None:
    """Find the night that produced this cycle's recovery.

    ``recovery.sleep_id`` is the authoritative link. Without a scored recovery yet, fall
    back to the cycle's own longest non-nap sleep.
    """
    if recovery is not None and recovery.sleep_id:
        linked = sleep_by_id.get(recovery.sleep_id)
        if linked is not None:
            return linked
    candidates = [s for s in sleeps if s.cycle_id == cycle.id and not s.nap and s.is_scored]
    if not candidates:
        return None
    return max(candidates, key=lambda s: s.performance or 0.0)


def _upsert_workouts(db: Session, user_id: int, workouts: Sequence[Workout]) -> int:
    written = 0
    for workout in workouts:
        if not workout.id:
            continue
        row = db.scalar(
            select(WhoopWorkout).where(
                WhoopWorkout.user_id == user_id, WhoopWorkout.whoop_id == workout.id
            )
        )
        if row is None:
            row = WhoopWorkout(user_id=user_id, whoop_id=workout.id)
            db.add(row)

        row.start = utc(workout.start)
        row.end = utc(workout.end)
        row.sport = workout.sport
        score = workout.score if workout.is_scored else None
        if score is not None:
            _set_if_known(row, "strain", score.strain)
            _set_if_known(row, "avg_hr", score.average_heart_rate)
            _set_if_known(row, "max_hr", score.max_heart_rate)
        row.fetched_at = utcnow()
        written += 1
    return written


def _set_if_known(row: object, field: str, value: float | int | None) -> None:
    """Assign only when WHOOP actually sent a value, so a pending score never erases."""
    if value is not None:
        setattr(row, field, value)


def last_workout_end(db: Session, user_id: int) -> datetime | None:
    return as_utc(
        db.scalar(
            select(WhoopWorkout.end)
            .where(WhoopWorkout.user_id == user_id, WhoopWorkout.end.is_not(None))
            .order_by(WhoopWorkout.end.desc())
            .limit(1)
        )
    )


