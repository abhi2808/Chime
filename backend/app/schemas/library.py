from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LibrarySyncStatus(BaseModel):
    """Progress for the library sync.

    ``state`` is one of never | idle | running | complete | partial | error | interrupted:

    * "partial" means the run stopped on purpose (Spotify rate limited us, or the artist
      phase used up its time budget). Everything it fetched is stored and usable, and
      ``artists_remaining`` says how much the next run has left to do.
    * "interrupted" means a previous process died mid-run and the next sync will resume.
    """

    model_config = ConfigDict(from_attributes=True)

    state: str
    phase: str | None = None
    mode: str | None = None
    tracks_synced: int = 0
    tracks_total: int | None = None
    artists_fetched: int = 0
    artists_total: int = 0
    artists_failed: int = 0
    artists_remaining: int = 0
    liked_tracks: int = 0
    artists_with_genres: int = 0
    stopped_early: bool = False
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    #: When Spotify said it would answer again; null when nothing is waiting on a limit.
    resume_after: datetime | None = None


class SyncStartResponse(LibrarySyncStatus):
    started: bool
