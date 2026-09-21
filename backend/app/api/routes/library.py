from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.library import LibrarySyncStatus, SyncStartResponse
from app.services import library_sync

router = APIRouter(prefix="/library", tags=["library"])


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED, response_model=SyncStartResponse)
async def start_sync(
    user: CurrentUser,
    db: DbSession,
    full: bool = Query(False, description="Walk the whole library instead of stopping at the first known liked song."),
) -> SyncStartResponse:
    started = library_sync.start_sync(user.id, full=full)
    status_now = library_sync.get_status(db, user.id)
    return SyncStartResponse(started=started, **asdict(status_now))


@router.get("/status", response_model=LibrarySyncStatus)
def sync_status(user: CurrentUser, db: DbSession) -> LibrarySyncStatus:
    return LibrarySyncStatus.model_validate(library_sync.get_status(db, user.id))
