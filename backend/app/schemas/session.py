"""Request and response shapes for the session endpoints (SPEC section 7)."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field

from app.services.profile_rules import DEFAULT_INTENT, DEFAULT_TYPE


class ChimeInRequest(BaseModel):
    """``POST /api/sessions``.

    ``mood`` is optional, and the sheet lets it be skipped: the engine has a defined answer
    without one (SPEC section 3), working from body data and the time of day alone. Note
    that ``intent="shift"`` does nothing without a mood — there is no curve to move away
    from — so the caller is the one that has to say so.
    """

    mood: str | None = None
    type: str = DEFAULT_TYPE
    intent: str = DEFAULT_INTENT
    count: int = Field(default=25, ge=1, le=100)


class MoodRequest(BaseModel):
    """``POST /api/sessions/{id}/mood`` — a re-check part way through."""

    mood: str


class ChimeOutRequest(BaseModel):
    """``POST /api/sessions/{id}/end``."""

    keep: bool = False
    #: Only read when ``keep``; blank means the default name.
    name: str | None = None
    mood_out: str | None = None
    pause: bool = True


class SessionTrackResponse(BaseModel):
    position: int
    track_id: int
    spotify_track_id: str
    name: str
    artists: list[str] = Field(default_factory=list)
    album: str | None = None
    image_url: str | None = None
    duration_ms: int = 0
    source: str = "library"
    #: Filled in by the phase 6 poller; null means "not measured", not "not played".
    started_at: dt.datetime | None = None
    played_ms: int = 0
    skipped: bool = False
    #: The track's energy and the target at this position, for the Why this mix panel.
    energy: float | None = None
    target: float | None = None


class SessionSummary(BaseModel):
    """What the Chime out card shows. Counts are null while unmeasured (see phase 6)."""

    minutes: float = 0.0
    queued: int = 0
    played: int | None = None
    skipped: int | None = None
    skip_rate: float | None = None
    #: Anything that went wrong at Chime out and is worth saying out loud.
    problems: list[str] = Field(default_factory=list)
    abandoned: bool = False


class SessionEventResponse(BaseModel):
    """One line of a session's timeline, for the History detail page.

    ``payload`` is passed through as stored. It is written by us, never by a user, and the
    screen reads the few keys it knows and ignores the rest.
    """

    ts: dt.datetime
    type: str
    payload: dict | None = None


class SessionResponse(BaseModel):
    """One session, with enough on it to draw the whole Session screen."""

    id: int
    status: str
    type: str
    intent: str
    mood_in: str | None = None
    mood_out: str | None = None
    started_at: dt.datetime
    ended_at: dt.datetime | None = None
    playlist_uri: str | None = None
    playlist_name: str | None = None
    playlist_url: str | None = None
    kept: bool = False
    why_text: str | None = None
    #: ``TargetProfile.as_dict()``: type, intent, mood, curve, ceiling, affinities, notes.
    profile: dict | None = None
    body_in: dict | None = None
    body_out: dict | None = None
    summary: SessionSummary | None = None
    tracks: list[SessionTrackResponse] = Field(default_factory=list)
    #: Where Chime in ended up playing, when it has just started. Not stored.
    device_name: str | None = None
    #: The mix is built and in the playlist, but Spotify would not let us press play (no
    #: open app, or no Premium). The session is waiting for a press of play in Spotify —
    #: ``playlist_url`` is where — or for "Try again" once Spotify is open.
    needs_manual_start: bool = False
    #: What to tell the user about that, written to be shown verbatim.
    manual_start_reason: str | None = None
    #: NO_ACTIVE_DEVICE | PREMIUM_REQUIRED | DEVICE_RESTRICTED | PLAYBACK_REFUSED.
    manual_start_code: str | None = None
    #: The timeline, on the detail page only. Empty while a session is running, because
    #: ``/active`` polls every few seconds and nothing on that screen shows it.
    events: list[SessionEventResponse] = Field(default_factory=list)
    #: Set once History has brought this session back: ``playlist_uri`` still names the
    #: temporary playlist that Chime out removed, so the rebuilt one needs its own field.
    restored_playlist_url: str | None = None
    restored_playlist_name: str | None = None


class NowPlaying(BaseModel):
    """A read of ``GET /me/player``, for the mini player.

    Read on demand rather than pushed: the polling loop that keeps this live is phase 6, and
    a screen that asks when it is opened is better than a screen that shows nothing.
    """

    is_playing: bool = False
    progress_ms: int | None = None
    spotify_track_id: str | None = None
    name: str | None = None
    artists: list[str] = Field(default_factory=list)
    image_url: str | None = None
    duration_ms: int = 0
    device_name: str | None = None
    #: True when playback has wandered off this session's playlist.
    off_context: bool = False


class ActiveSessionResponse(BaseModel):
    """``GET /api/sessions/active``: null session when nothing is running."""

    session: SessionResponse | None = None
    playing: NowPlaying | None = None
    #: Why there is no playback to report, in the user's terms. Shown verbatim.
    note: str | None = None
