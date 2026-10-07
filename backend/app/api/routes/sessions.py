"""Chime in, mood re-check, Chime out, and History (SPEC section 7).

Thin: every decision is in ``app.services.sessions`` or ``app.services.history``. What lives
here is the mapping from rows to the shapes the screens want, and the translation of typed
Spotify failures into status codes with a message worth showing.

History's endpoints share this router rather than getting their own, because ``/week`` and
``/{session_id}`` are the same shape to a router and only declaration order tells them
apart. Split across two routers, whichever mounted first would win and ``week`` would be
parsed as a session id.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.db.session import SessionLocal
from app.integrations.spotify import player
from app.integrations.spotify.client import SpotifyClient
from app.integrations.spotify.errors import (
    SpotifyAuthError,
    SpotifyError,
    SpotifyNoActiveDeviceError,
    SpotifyPremiumRequiredError,
    SpotifyRestrictedDeviceError,
)
from app.integrations.spotify.schemas import PlaybackState
from app.models import Session, SessionTrack, Track
from app.schemas.history import (
    RestoreResponse,
    SessionListItem,
    SessionListResponse,
    WeekSummaryResponse,
)
from app.schemas.session import (
    ActiveSessionResponse,
    ChimeInRequest,
    ChimeOutRequest,
    MoodRequest,
    NowPlaying,
    SessionEventResponse,
    SessionResponse,
    SessionSummary,
    SessionTrackResponse,
)
from app.services import history, playback, sessions
from app.services.token_store import TokenStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])

#: A playlist's page, for "Open in Spotify". Built rather than stored: it is derivable.
PLAYLIST_URL = "https://open.spotify.com/playlist/{id}"

NOT_PLAYING = "Nothing is playing on Spotify right now."
PLAYBACK_UNREADABLE = "Spotify didn't say what's playing. The session is still running."


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def chime_in(payload: ChimeInRequest, user: CurrentUser, db: DbSession) -> SessionResponse:
    """Build a mix for right now, put it in a playlist, and start it playing.

    A Spotify that will not press play is not a failure here: the answer carries the
    playlist, `needs_manual_start` and a reason, and the session waits (see the module
    docstring in ``app.services.sessions``).
    """
    try:
        result = await sessions.chime_in(
            db,
            user.id,
            mood=payload.mood,
            session_type=payload.type,
            intent=payload.intent,
            count=payload.count,
        )
    except sessions.SessionAlreadyLiveError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(exc), "session_id": exc.session.id, "code": "SESSION_ACTIVE"},
        ) from exc
    except sessions.NoTracksError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(exc), "code": "NO_TRACKS"},
        ) from exc
    except sessions.SessionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SpotifyError as exc:
        raise _spotify_http_error(exc) from exc

    return _session_response(db, result.session, device_name=result.device_name)


@router.get("", response_model=SessionListResponse)
def list_sessions(
    user: CurrentUser,
    db: DbSession,
    type: str | None = None,
    mood_in: str | None = None,
    kept: bool | None = None,
    start: dt.date | None = Query(default=None, alias="from"),
    end: dt.date | None = Query(default=None, alias="to"),
    include_failed: bool = False,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> SessionListResponse:
    """Every session, newest first, with SPEC's filters.

    ``from`` and ``to`` are whole days and ``to`` is inclusive. A failed session is left out
    unless asked for: it played nothing, so it is noise in a record of what you listened to.
    """
    rows, total = history.list_sessions(
        db,
        user.id,
        filters=history.Filters(
            type=type,
            mood_in=mood_in,
            kept=kept,
            start=start,
            end=end,
            include_failed=include_failed,
        ),
        limit=limit,
        offset=offset,
    )
    return SessionListResponse(
        sessions=[_list_item(row) for row in rows], total=total, limit=limit, offset=offset
    )


@router.get("/week", response_model=WeekSummaryResponse)
def read_week(
    user: CurrentUser, db: DbSession, days: int = Query(default=7, ge=1, le=90)
) -> WeekSummaryResponse:
    """Sessions, minutes and the commonest mood shift over the last few days."""
    summary = history.week_summary(db, user.id, days=days)
    return WeekSummaryResponse(
        days=summary.days,
        sessions=summary.sessions,
        minutes=summary.minutes,
        shift_from=summary.shift_from,
        shift_to=summary.shift_to,
        shift_count=summary.shift_count,
        note=summary.note,
    )


@router.get("/active", response_model=ActiveSessionResponse)
async def read_active(user: CurrentUser, db: DbSession) -> ActiveSessionResponse:
    """The session in progress and what it is playing, or nulls if there is none."""
    session = sessions.active_session(db, user.id)
    if session is None:
        return ActiveSessionResponse()

    playing: NowPlaying | None = None
    note: str | None = None
    client = SpotifyClient(TokenStore(SessionLocal, user.id))
    try:
        state = await player.get_playback_state(client)
        # Measured from the snapshot this screen already asked for, so the poll a user is
        # looking at costs Spotify nothing extra and measures far more finely than the
        # background scheduler on its own. It is also where a session started by hand in
        # Spotify is noticed.
        playback.record(db, session, state)
        if state is None:
            note = NOT_PLAYING
        else:
            playing = _now_playing(state, session)
    except SpotifyError as exc:
        # A session is a database fact; playback is a reading that can fail. Losing the
        # second must not hide the first, or Chime out becomes unreachable.
        logger.info(
            "could not read playback for an active session",
            extra={"session_id": session.id, "error": exc.message},
        )
        note = PLAYBACK_UNREADABLE
    finally:
        await client.aclose()

    return ActiveSessionResponse(
        session=_session_response(db, session), playing=playing, note=note
    )


@router.get("/{session_id}", response_model=SessionResponse)
def read_session(session_id: int, user: CurrentUser, db: DbSession) -> SessionResponse:
    """One session, whether it is running or long finished. Carries its timeline."""
    return _session_response(db, _require(db, user.id, session_id), with_events=True)


@router.post("/{session_id}/restore", response_model=RestoreResponse)
async def restore_session(
    session_id: int, user: CurrentUser, db: DbSession
) -> RestoreResponse:
    """Bring a session back as a playlist, rebuilt from our own rows.

    A new playlist every time, and one that stays: the temporary one this session made is
    gone, and the user asking for it back is not asking for something Chime will tidy away.
    """
    session = _require(db, user.id, session_id)
    try:
        restored = await history.restore(db, user.id, session)
    except history.HistoryError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except SpotifyError as exc:
        raise _spotify_http_error(exc) from exc
    return RestoreResponse(
        playlist_uri=restored.playlist_uri,
        playlist_url=PLAYLIST_URL.format(id=restored.playlist_id),
        name=restored.name,
        tracks=restored.tracks,
    )


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: int, user: CurrentUser, db: DbSession) -> None:
    """Forget a session. Spotify is untouched — a kept playlist is the user's now."""
    session = _require(db, user.id, session_id)
    try:
        history.delete_session(db, session)
    except history.HistoryError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{session_id}/start", response_model=SessionResponse)
async def start_playback(session_id: int, user: CurrentUser, db: DbSession) -> SessionResponse:
    """Try again to play a session that is built but waiting.

    For after Spotify has been opened: the playlist already exists, so this only looks for a
    device and presses play. A refusal answers 409 with a code, like Chime in's does.
    """
    session = _require(db, user.id, session_id)
    try:
        result = await sessions.start_playback(db, user.id, session)
    except sessions.SessionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except SpotifyError as exc:
        raise _spotify_http_error(exc) from exc
    return _session_response(db, result.session, device_name=result.device_name)


@router.post("/{session_id}/mood", response_model=SessionResponse)
def check_mood(
    session_id: int, payload: MoodRequest, user: CurrentUser, db: DbSession
) -> SessionResponse:
    """Say how you feel now, part way through."""
    session = _require(db, user.id, session_id)
    try:
        sessions.record_mood(db, session, payload.mood)
    except sessions.SessionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _session_response(db, session)


@router.post("/{session_id}/end", response_model=SessionResponse)
async def chime_out(
    session_id: int, payload: ChimeOutRequest, user: CurrentUser, db: DbSession
) -> SessionResponse:
    """End the session: keep the playlist or take it back out of the library."""
    session = _require(db, user.id, session_id)
    try:
        ended = await sessions.chime_out(
            db,
            user.id,
            session,
            keep=payload.keep,
            name=payload.name,
            mood_out=payload.mood_out,
            pause=payload.pause,
        )
    except sessions.SessionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SpotifyAuthError as exc:
        raise _spotify_http_error(exc) from exc
    return _session_response(db, ended)


@router.post("/{session_id}/next", status_code=status.HTTP_204_NO_CONTENT)
async def skip_forward(session_id: int, user: CurrentUser, db: DbSession) -> None:
    """Next track. Chime does not choose this — the user does, and phase 6 will notice."""
    await _player_command(user.id, _require(db, user.id, session_id), player.next_track)


@router.post("/{session_id}/previous", status_code=status.HTTP_204_NO_CONTENT)
async def skip_back(session_id: int, user: CurrentUser, db: DbSession) -> None:
    await _player_command(user.id, _require(db, user.id, session_id), player.previous_track)


@router.post("/{session_id}/pause", status_code=status.HTTP_204_NO_CONTENT)
async def pause(session_id: int, user: CurrentUser, db: DbSession) -> None:
    await _player_command(user.id, _require(db, user.id, session_id), player.pause)


@router.post("/{session_id}/resume", status_code=status.HTTP_204_NO_CONTENT)
async def resume(session_id: int, user: CurrentUser, db: DbSession) -> None:
    await _player_command(user.id, _require(db, user.id, session_id), player.resume)


# ------------------------------------------------------------------- helpers


async def _player_command(
    user_id: int, session: Session, command: Callable[[SpotifyClient], Awaitable[None]]
) -> None:
    if not session.is_live:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That session has already ended."
        )
    client = SpotifyClient(TokenStore(SessionLocal, user_id))
    try:
        await command(client)
    except SpotifyError as exc:
        raise _spotify_http_error(exc) from exc
    finally:
        await client.aclose()


def _require(db: DbSession, user_id: int, session_id: int) -> Session:
    session = sessions.get_session(db, user_id, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such session.")
    return session


def _spotify_http_error(exc: SpotifyError) -> HTTPException:
    """Turn a typed Spotify failure into a status and a sentence worth showing.

    The two that matter are the two we cannot check for in advance: Premium (``GET /me``
    no longer says) and an open Spotify app (nothing else can tell us). Both are 409 —
    the request was fine, the world is not ready for it.
    """
    if isinstance(exc, SpotifyNoActiveDeviceError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": exc.message, "code": "NO_ACTIVE_DEVICE"},
        )
    if isinstance(exc, SpotifyPremiumRequiredError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    "Spotify only allows apps to control playback on Premium accounts. "
                    "The mix is built, but Chime can't press play."
                ),
                "code": "PREMIUM_REQUIRED",
            },
        )
    if isinstance(exc, SpotifyRestrictedDeviceError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "That device won't accept commands from other apps.",
                "code": "DEVICE_RESTRICTED",
            },
        )
    if isinstance(exc, SpotifyAuthError):
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Spotify needs signing in again.", "code": "REAUTH"},
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={"message": exc.message, "code": exc.code or "SPOTIFY_ERROR"},
    )


def _session_response(
    db: DbSession,
    session: Session,
    *,
    device_name: str | None = None,
    with_events: bool = False,
) -> SessionResponse:
    # Only asked for while a session is stuck at `created`, so the common path pays nothing.
    manual = sessions.manual_start(db, session)
    # Two more queries, and `/active` polls this every few seconds, so only the detail page
    # asks for them.
    timeline = history.events(db, session.id) if with_events else []
    restored = history.latest_restore(timeline)
    return SessionResponse(
        id=session.id,
        status=session.status,
        type=session.type,
        intent=session.intent,
        mood_in=session.mood_in,
        mood_out=session.mood_out,
        started_at=session.started_at,
        ended_at=session.ended_at,
        playlist_uri=session.playlist_uri,
        playlist_name=session.playlist_name,
        playlist_url=(
            # Dropped once Chime out has taken the playlist out of the library: the link
            # would open a Spotify page saying it does not exist. History offers "bring it
            # back" instead.
            PLAYLIST_URL.format(id=session.playlist_id)
            if session.playlist_id and not session.playlist_removed_at
            else None
        ),
        kept=session.kept,
        why_text=session.why_text,
        profile=session.target_profile,
        body_in=session.body_in,
        body_out=session.body_out,
        summary=SessionSummary.model_validate(session.summary) if session.summary else None,
        tracks=[
            _track_response(session_track, track)
            for session_track, track in sessions.track_rows(db, session.id)
        ],
        device_name=device_name,
        needs_manual_start=manual is not None,
        manual_start_reason=manual.message if manual else None,
        manual_start_code=manual.code if manual else None,
        events=[
            SessionEventResponse(ts=event.ts, type=event.type, payload=event.payload)
            for event in timeline
        ],
        restored_playlist_url=(
            PLAYLIST_URL.format(id=restored["playlist_id"])
            if restored and restored.get("playlist_id")
            else None
        ),
        restored_playlist_name=restored.get("name") if restored else None,
    )


def _list_item(row: history.Row) -> SessionListItem:
    session = row.session
    return SessionListItem(
        id=session.id,
        status=session.status,
        type=session.type,
        intent=session.intent,
        mood_in=session.mood_in,
        mood_out=session.mood_out,
        started_at=session.started_at,
        ended_at=session.ended_at,
        playlist_name=session.playlist_name,
        playlist_url=(
            # Only worth offering while the playlist is still there: once Chime out has
            # removed it the link leads to a page that says the playlist does not exist.
            PLAYLIST_URL.format(id=session.playlist_id)
            if session.playlist_id and not session.playlist_removed_at
            else None
        ),
        kept=session.kept,
        why_text=session.why_text,
        minutes=history.minutes_of(session),
        queued=row.queued,
        played=history.count_of(session, "played"),
        skipped=history.count_of(session, "skipped"),
        images=row.images,
    )


def _track_response(session_track: SessionTrack, track: Track) -> SessionTrackResponse:
    breakdown = session_track.score_breakdown or {}
    return SessionTrackResponse(
        position=session_track.position,
        track_id=track.id,
        spotify_track_id=track.spotify_track_id,
        name=track.name,
        artists=list(track.artist_names or ()),
        album=track.album_name,
        image_url=track.image_url,
        duration_ms=track.duration_ms,
        source=session_track.source,
        started_at=session_track.started_at,
        played_ms=session_track.played_ms,
        skipped=session_track.skipped,
        energy=_number(breakdown.get("energy")),
        target=_number(breakdown.get("target")),
    )


def _now_playing(state: PlaybackState, session: Session) -> NowPlaying:
    track = state.item
    context_uri = state.context.uri if state.context else None
    return NowPlaying(
        is_playing=state.is_playing,
        progress_ms=state.progress_ms,
        spotify_track_id=track.id if track else None,
        name=track.name if track else None,
        artists=list(track.artist_names) if track else [],
        image_url=track.image_url if track else None,
        duration_ms=track.duration_ms if track else 0,
        device_name=state.device.name if state.device else None,
        off_context=bool(
            session.playlist_uri and context_uri and context_uri != session.playlist_uri
        ),
    )


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
