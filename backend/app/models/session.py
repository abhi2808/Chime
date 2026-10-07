"""Sessions: one Chime in, everything that played, and how it ended (SPEC section 4).

A session is the only row in the app that outlives the thing it describes. The Spotify
playlist is temporary by design and usually gone within the hour, so ``session_tracks``
is the record — which is what lets History "bring it back" later from our own data
rather than from a playlist that no longer exists.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.clock import utcnow
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.track import Track

#: SPEC section 6's state machine: ``created -> active -> ended``, or ``failed``.
#:
#: Not in SPEC's column list, but the machine needs somewhere to live and no combination
#: of the other columns can express it: a session that failed while creating its playlist
#: has no ``ended_at`` and no playlist, and so is indistinguishable from an active one.
STATUS_CREATED = "created"
STATUS_ACTIVE = "active"
STATUS_ENDED = "ended"
STATUS_FAILED = "failed"

STATUSES = (STATUS_CREATED, STATUS_ACTIVE, STATUS_ENDED, STATUS_FAILED)

#: Statuses a poller or "resume where I was" should treat as still running.
LIVE_STATUSES = (STATUS_CREATED, STATUS_ACTIVE)

#: How a track got into a session.
TRACK_SOURCE_LIBRARY = "library"  # chosen by the ranking at Chime in
TRACK_SOURCE_ADAPT = "adapt"  # added mid-session by an adaptation (phase 6)

TRACK_SOURCES = (TRACK_SOURCE_LIBRARY, TRACK_SOURCE_ADAPT)

#: Things worth writing down while a session runs.
EVENT_MOOD_CHECK = "mood_check"
EVENT_WHOOP_REFRESH = "whoop_refresh"
EVENT_ADAPT = "adapt"
EVENT_ERROR = "error"
#: The mix is built and in a playlist, but Spotify would not let us press play. Carries the
#: reason so the session screen can say why and offer the playlist instead.
EVENT_MANUAL_START = "manual_start"
#: History rebuilt this session's playlist. Carries the *new* playlist, because
#: ``playlist_uri`` still names the temporary one that Chime out took away, and that is a
#: fact about what happened rather than a stale value to overwrite.
EVENT_RESTORE = "restore"

EVENT_TYPES = (
    EVENT_MOOD_CHECK,
    EVENT_WHOOP_REFRESH,
    EVENT_ADAPT,
    EVENT_ERROR,
    EVENT_MANUAL_START,
    EVENT_RESTORE,
)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_CREATED, index=True)
    #: The *resolved* type. ``auto`` never reaches the database (SPEC section 2).
    type: Mapped[str] = mapped_column(String(16))
    intent: Mapped[str] = mapped_column(String(8), default="match")
    mood_in: Mapped[str | None] = mapped_column(String(16), default=None)
    mood_out: Mapped[str | None] = mapped_column(String(16), default=None)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    #: Body state at Chime in and at Chime out, stored whole. Deltas at this granularity
    #: are small (WHOOP scores a day, not a moment), but History shows them side by side.
    body_in: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    body_out: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    playlist_uri: Mapped[str | None] = mapped_column(String(64), default=None)
    playlist_name: Mapped[str | None] = mapped_column(String(255), default=None)
    kept: Mapped[bool] = mapped_column(Boolean, default=False)
    playlist_removed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    #: ``TargetProfile.as_dict()``: the brief the ranking worked to, including its curve
    #: and the plain-language notes behind ``why_text``.
    target_profile: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    why_text: Mapped[str | None] = mapped_column(Text, default=None)
    #: played, skipped, skip_rate, minutes. Computed once at Chime out.
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)

    tracks: Mapped[list[SessionTrack]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SessionTrack.position",
    )
    events: Mapped[list[SessionEvent]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SessionEvent.ts",
    )

    @property
    def playlist_id(self) -> str | None:
        """The bare id out of ``spotify:playlist:<id>``.

        Stored as a URI because that is what the player endpoints take as a
        ``context_uri``; the id is what the playlist endpoints take in their path.
        """
        if not self.playlist_uri:
            return None
        _, _, tail = self.playlist_uri.rpartition(":")
        return tail or None

    @property
    def is_live(self) -> bool:
        return self.status in LIVE_STATUSES


class SessionTrack(Base):
    """One position in a session's running order, and what actually happened to it."""

    __tablename__ = "session_tracks"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(16), default=TRACK_SOURCE_LIBRARY)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    #: When playback moved off this track. Not in SPEC's column list, and added in phase 6
    #: because the poller cannot work without it: ``skipped`` is a *decision*, and
    #: ``skipped = False`` cannot be told apart from "not decided yet" on a row that is
    #: playing right now. With this, ``started_at`` means played, ``finished_at`` means
    #: judged, and a poller that restarts mid-session does not re-judge what it already has.
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    #: Highest playback position seen on this track, which is what a snapshot poller can
    #: honestly claim. A seek backwards or a replay is not counted twice.
    played_ms: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[bool] = mapped_column(Boolean, default=False)
    #: The per-component score from ``app.services.ranking``, kept so "why this mix" and
    #: History can explain a choice months later without re-running the ranking.
    score_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)

    session: Mapped[Session] = relationship(back_populates="tracks")
    #: Eager: every screen that reads a session's tracks needs their names and artwork,
    #: and 25 lazy loads per session is the classic N+1.
    track: Mapped[Track] = relationship(lazy="joined")


class SessionEvent(Base):
    """A timeline entry. Append-only, and safe to lose: nothing reads it to make decisions."""

    __tablename__ = "session_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    type: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)

    session: Mapped[Session] = relationship(back_populates="events")
