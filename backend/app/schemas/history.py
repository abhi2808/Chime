"""Request and response shapes for History (SPEC section 7).

The list deliberately does **not** reuse ``SessionResponse``: that shape carries every track,
its score breakdown, both body states and the target profile, which is a lot of JSON per row
for a screen that draws a card. What a card needs is the figures it prints and a few covers.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field


class SessionListItem(BaseModel):
    """One card in the list."""

    id: int
    status: str
    type: str
    intent: str
    mood_in: str | None = None
    mood_out: str | None = None
    started_at: dt.datetime
    ended_at: dt.datetime | None = None
    playlist_name: str | None = None
    playlist_url: str | None = None
    kept: bool = False
    why_text: str | None = None
    minutes: float = 0.0
    queued: int = 0
    #: Null until something measures them (phase 6), which is not the same as zero.
    played: int | None = None
    skipped: int | None = None
    #: Up to four distinct album covers, in playing order.
    images: list[str] = Field(default_factory=list)


class SessionListResponse(BaseModel):
    """``GET /api/sessions``. ``total`` is the filtered count, so "load more" knows when to stop."""

    sessions: list[SessionListItem] = Field(default_factory=list)
    total: int = 0
    limit: int = 20
    offset: int = 0


class WeekSummaryResponse(BaseModel):
    """``GET /api/sessions/week``: the line above the list.

    ``note`` is there because a week with nothing in it, and a week whose sessions never
    recorded a second mood, both have to say something other than zero.
    """

    days: int = 7
    sessions: int = 0
    minutes: float = 0.0
    shift_from: str | None = None
    shift_to: str | None = None
    shift_count: int = 0
    note: str | None = None


class RestoreResponse(BaseModel):
    """``POST /api/sessions/{id}/restore``: the new playlist, which stays in the library."""

    playlist_uri: str
    playlist_url: str
    name: str
    tracks: int
