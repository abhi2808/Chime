from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base

# ``datetime`` is aliased because this table has a column literally called ``date``, and
# a bare ``Mapped[date]`` annotation would resolve against that column instead.


class WhoopDaily(Base):
    """One row per user per WHOOP day, holding only the figures the engine reads.

    ``date`` is the *member's* local date for the cycle, not ours: a WHOOP day starts
    when you wake, so it neither matches UTC midnight nor the server's timezone.

    Raw payloads are deliberately not stored. Every figure is nullable because WHOOP
    fills a day in over time — strain climbs from the moment you wake, recovery only
    lands after a sleep is scored, and a day mid-morning legitimately has neither.
    """

    __tablename__ = "whoop_daily"
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_whoop_daily_user_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    #: WHOOP's own cycle id, so a re-read updates the day instead of duplicating it.
    cycle_id: Mapped[str | None] = mapped_column(String(64), default=None)
    #: The member's UTC offset for this cycle, e.g. ``-05:00``. Kept because "what part
    #: of the day is it for them" cannot be answered from the server's clock.
    timezone_offset: Mapped[str | None] = mapped_column(String(16), default=None)
    recovery: Mapped[float | None] = mapped_column(Float, default=None)
    hrv_ms: Mapped[float | None] = mapped_column(Float, default=None)
    rhr: Mapped[float | None] = mapped_column(Float, default=None)
    sleep_performance: Mapped[float | None] = mapped_column(Float, default=None)
    day_strain: Mapped[float | None] = mapped_column(Float, default=None)
    spo2: Mapped[float | None] = mapped_column(Float, default=None)
    skin_temp_c: Mapped[float | None] = mapped_column(Float, default=None)
    #: True while WHOOP is still calibrating to the member; scores are not trustworthy.
    calibrating: Mapped[bool] = mapped_column(default=False)
    #: Set while the cycle is still open, i.e. this is the day in progress.
    cycle_open: Mapped[bool] = mapped_column(default=False)
    fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class WhoopWorkout(Base):
    """A finished workout. WHOOP does not expose one that is still in progress."""

    __tablename__ = "whoop_workouts"
    __table_args__ = (
        UniqueConstraint("user_id", "whoop_id", name="uq_whoop_workouts_user_whoop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    #: UUID in API v2.
    whoop_id: Mapped[str] = mapped_column(String(64))
    start: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True
    )
    end: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    strain: Mapped[float | None] = mapped_column(Float, default=None)
    avg_hr: Mapped[int | None] = mapped_column(Integer, default=None)
    max_hr: Mapped[int | None] = mapped_column(Integer, default=None)
    sport: Mapped[str | None] = mapped_column(String(64), default=None)
    fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
