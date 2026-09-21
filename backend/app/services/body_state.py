"""Turn stored WHOOP data into the body state the engine reads (SPEC section 2).

Two rules this module exists to enforce:

* **WHOOP is context, never a live signal.** There is no stress score and no live heart
  rate in the API, so nothing here is presented as one.
* **A missing WHOOP is not an error.** Chime in has to work on mood and time of day
  alone, so every field is optional and the response says what it does not know.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from app.core.clock import as_utc, utcnow
from app.db.session import SessionLocal
from app.integrations.whoop.errors import WhoopAuthError
from app.integrations.whoop.schemas import offset_timezone
from app.models import WhoopDaily
from app.services import whoop_sync

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]

Readiness = Literal["low", "medium", "high"]
DayPart = Literal["early_morning", "morning", "afternoon", "evening", "late_night"]

#: WHOOP's own recovery bands: red under 34, yellow to 66, green above.
LOW_RECOVERY = 34.0
HIGH_RECOVERY = 66.0

#: Hour boundaries in the member's local time. SPEC names the buckets but not the hours.
_DAY_PARTS: tuple[tuple[int, DayPart], ...] = (
    (5, "late_night"),  # 00:00-04:59
    (8, "early_morning"),  # 05:00-07:59
    (12, "morning"),  # 08:00-11:59
    (17, "afternoon"),  # 12:00-16:59
    (22, "evening"),  # 17:00-21:59
)

NOT_CONNECTED = "WHOOP isn't connected, so this mix uses your mood and the time of day."
NO_DATA = "WHOOP is connected but hasn't sent anything yet. Wear it overnight and check back."
CALIBRATING = "WHOOP is still calibrating to you, so treat these scores as rough."
STALE = "WHOOP didn't answer just now, so these figures may be older than usual."
RECONNECT = "WHOOP needs reconnecting. Open settings and connect it again."


@dataclass(slots=True)
class BodyState:
    """SPEC's body_state, plus the metadata a screen needs to explain itself.

    ``mood`` is absent on purpose: it comes from the user at Chime in, not from WHOOP.
    """

    day_part: DayPart
    connected: bool = False
    has_data: bool = False
    recovery: float | None = None
    hrv_ms: float | None = None
    rhr: float | None = None
    sleep_performance: float | None = None
    day_strain: float | None = None
    minutes_since_last_workout: int | None = None
    readiness: Readiness | None = None
    calibrating: bool = False
    date: dt.date | None = None
    fetched_at: dt.datetime | None = None
    note: str | None = None
    #: The grant is gone, so a screen should offer "Reconnect" rather than "Refresh".
    #: Distinct from ``connected``, which stays true while a dead token is still stored.
    needs_reconnect: bool = False


def readiness_for(recovery: float | None) -> Readiness | None:
    """WHOOP's bands, applied exactly as documented: low <34, medium 34-66, high >66."""
    if recovery is None:
        return None
    if recovery < LOW_RECOVERY:
        return "low"
    if recovery > HIGH_RECOVERY:
        return "high"
    return "medium"


def day_part_for(moment: dt.datetime, offset: str | None = None) -> DayPart:
    """Which part of the day it is *for the member*.

    The offset comes from their latest WHOOP cycle. Without WHOOP we fall back to UTC,
    which is wrong for most of the world — so a session started without WHOOP should not
    lean hard on day_part.
    """
    local = moment.astimezone(offset_timezone(offset))
    for boundary, name in _DAY_PARTS:
        if local.hour < boundary:
            return name
    return "late_night"  # 22:00-23:59


def build(db: Session, user_id: int, *, note: str | None = None) -> BodyState:
    """Assemble body state from what is already stored. Never calls WHOOP."""
    connected = whoop_sync.is_connected(db, user_id)
    day = whoop_sync.latest_day(db, user_id)
    offset = day.timezone_offset if day else None
    state = BodyState(day_part=day_part_for(utcnow(), offset), connected=connected)

    if day is None:
        state.note = note or (NOT_CONNECTED if not connected else NO_DATA)
        return state

    state.has_data = True
    state.date = day.date
    state.recovery = day.recovery
    state.hrv_ms = day.hrv_ms
    state.rhr = day.rhr
    state.sleep_performance = day.sleep_performance
    state.day_strain = day.day_strain
    state.calibrating = day.calibrating
    state.readiness = readiness_for(day.recovery)
    state.fetched_at = as_utc(day.fetched_at)
    state.minutes_since_last_workout = _minutes_since_workout(db, user_id)
    state.note = note or (CALIBRATING if day.calibrating else None)
    return state


async def read(
    user_id: int,
    *,
    force: bool = False,
    session_factory: SessionFactory = SessionLocal,
) -> BodyState:
    """Refresh if the cache is stale, then build. This is what the API serves.

    A refresh failure is reported in ``note`` rather than raised, so the screen shows
    yesterday's figures with an explanation instead of an error.
    """
    note: str | None = None
    needs_reconnect = False
    with session_factory() as db:
        connected = whoop_sync.is_connected(db, user_id)

    if connected:
        try:
            result = await whoop_sync.refresh_body_data(
                user_id, force=force, session_factory=session_factory
            )
            if not result.ok:
                note = STALE
        except WhoopAuthError as exc:
            # The grant is gone. Say so plainly; only a reconnect fixes it.
            logger.info(
                "whoop grant is no longer valid", extra={"user_id": user_id, "error": exc.message}
            )
            note = RECONNECT
            needs_reconnect = True

    with session_factory() as db:
        state = build(db, user_id, note=note)
    state.needs_reconnect = needs_reconnect
    return state


def _minutes_since_workout(db: Session, user_id: int) -> int | None:
    end = whoop_sync.last_workout_end(db, user_id)
    if end is None:
        return None
    minutes = (utcnow() - end).total_seconds() / 60
    # A workout still being uploaded can carry an end a few seconds in the future.
    return max(0, int(minutes))


def latest_offset(db: Session, user_id: int) -> str | None:
    """The member's UTC offset, for callers that need their clock rather than ours."""
    day: WhoopDaily | None = whoop_sync.latest_day(db, user_id)
    return day.timezone_offset if day else None
