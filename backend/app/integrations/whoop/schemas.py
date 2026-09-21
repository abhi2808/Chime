"""Typed WHOOP API v2 responses.

Two things drive the shape of these models:

* Every record carries a ``score_state`` of ``SCORED``, ``PENDING_SCORE`` or
  ``UNSCORABLE``, and ``score`` is **absent** unless it is ``SCORED``. A nap recorded
  ten minutes ago has no score, and that must not break a day's refresh.
* v2 moved activity ids from integers to UUIDs while cycle ids stayed numeric, so every
  id is coerced to ``str`` and compared as text.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

SCORED = "SCORED"
PENDING_SCORE = "PENDING_SCORE"
UNSCORABLE = "UNSCORABLE"


def _as_text(value: object) -> object:
    """Ids are numeric on cycles and UUIDs on activities; store both as text."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, int | float):
        return str(int(value))
    return value


WhoopId = Annotated[str, BeforeValidator(_as_text)]


class WhoopModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


RecordT = TypeVar("RecordT", bound=WhoopModel)


class WhoopPage(WhoopModel, Generic[RecordT]):
    """Every collection endpoint pages the same way. ``limit`` maxes out at 25."""

    records: list[RecordT] = Field(default_factory=list)
    next_token: str | None = None


class WhoopProfile(WhoopModel):
    """``GET /v2/user/profile/basic``. Read to prove a new token works, never stored."""

    user_id: WhoopId | None = None
    first_name: str | None = None
    last_name: str | None = None


class Scored(WhoopModel):
    """Shared ``score_state`` handling."""

    score_state: str | None = None

    @property
    def is_scored(self) -> bool:
        return self.score_state == SCORED


def offset_timezone(raw: str | None) -> timezone:
    """WHOOP sends the member's UTC offset as ``-05:00`` (sometimes ``-0500``)."""
    if not raw:
        return timezone.utc
    text = raw.strip()
    sign = -1 if text.startswith("-") else 1
    text = text.lstrip("+-").replace(":", "")
    if len(text) < 4 or not text.isdigit():
        return timezone.utc
    hours, minutes = int(text[:2]), int(text[2:4])
    if hours > 23 or minutes > 59:
        return timezone.utc
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


class CycleScore(WhoopModel):
    strain: float | None = None
    kilojoule: float | None = None
    average_heart_rate: int | None = None
    max_heart_rate: int | None = None


class Cycle(Scored):
    """``GET /v2/cycle``. A physiological day, which is not a calendar day.

    A cycle starts when the member wakes and the current one has no ``end``, so the open
    cycle is today's. ``score.strain`` on the open cycle is the figure that climbs
    through the day.
    """

    id: WhoopId | None = None
    start: datetime | None = None
    end: datetime | None = None
    timezone_offset: str | None = None
    score: CycleScore | None = None

    @property
    def is_open(self) -> bool:
        return self.end is None

    @property
    def local_date(self) -> date | None:
        """The member's own calendar date for this cycle, not ours.

        A cycle that starts at 06:00 in Berlin belongs to that Berlin day even when our
        server is in UTC and it is still yesterday there.
        """
        if self.start is None:
            return None
        return self.start.astimezone(offset_timezone(self.timezone_offset)).date()

    @property
    def strain(self) -> float | None:
        return self.score.strain if self.is_scored and self.score else None


class RecoveryScore(WhoopModel):
    recovery_score: float | None = None
    resting_heart_rate: float | None = None
    hrv_rmssd_milli: float | None = None
    spo2_percentage: float | None = None
    skin_temp_celsius: float | None = None
    #: True for the member's first days on the strap, when scores are not trustworthy.
    user_calibrating: bool = False


class Recovery(Scored):
    """``GET /v2/recovery``. Keyed to the cycle it belongs to, and lands after sleep."""

    cycle_id: WhoopId | None = None
    sleep_id: WhoopId | None = None
    score: RecoveryScore | None = None

    @property
    def scored_values(self) -> RecoveryScore | None:
        return self.score if self.is_scored else None


class SleepScore(WhoopModel):
    sleep_performance_percentage: float | None = None
    sleep_efficiency_percentage: float | None = None
    sleep_consistency_percentage: float | None = None
    respiratory_rate: float | None = None


class Sleep(Scored):
    """``GET /v2/activity/sleep``. Naps are included and are excluded by us."""

    id: WhoopId | None = None
    cycle_id: WhoopId | None = None
    nap: bool = False
    start: datetime | None = None
    end: datetime | None = None
    score: SleepScore | None = None

    @property
    def performance(self) -> float | None:
        if not self.is_scored or self.score is None:
            return None
        return self.score.sleep_performance_percentage


class WorkoutScore(WhoopModel):
    strain: float | None = None
    average_heart_rate: int | None = None
    max_heart_rate: int | None = None
    kilojoule: float | None = None
    percent_recorded: float | None = None


class Workout(Scored):
    """``GET /v2/activity/workout``. Only appears once the workout has finished."""

    id: WhoopId | None = None
    start: datetime | None = None
    end: datetime | None = None
    sport_name: str | None = None
    sport_id: int | None = None
    score: WorkoutScore | None = None

    @property
    def sport(self) -> str | None:
        if self.sport_name:
            return self.sport_name
        return f"sport {self.sport_id}" if self.sport_id is not None else None


def utc(moment: datetime | None) -> datetime | None:
    """Normalise to aware UTC; WHOOP sends offsets but a naive value is still possible."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)
