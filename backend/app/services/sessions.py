"""The session engine: Chime in, mood re-check, Chime out (SPEC section 6).

State machine: ``created -> active -> ended``, or ``failed``.

The order of operations is the design. Everything that can be worked out locally — body
state, profile, ranking — happens before Spotify is touched at all, and the session row is
written before the playlist exists. So a failure half way through leaves a session that
says what it was trying to do rather than an orphaned playlist nobody asked for.

The playlist itself is the fallback for the one part Chime cannot guarantee. Spotify only
lets an app press play on a Premium account with the app already open somewhere, and
neither of those can be checked in advance, so a refused play does not throw the mix away:
the session stays ``created``, the playlist stays in the library, and the user presses play
in Spotify (or opens Spotify and asks us to try again). What does undo the playlist is a
failure that leaves nothing usable — a playlist we could not fill, or an expired login.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.clock import as_utc, utcnow
from app.db.session import SessionLocal
from app.integrations.spotify import player, playlists
from app.integrations.spotify.client import SpotifyClient
from app.integrations.spotify.errors import (
    SpotifyAuthError,
    SpotifyError,
    SpotifyNoActiveDeviceError,
    SpotifyPremiumRequiredError,
    SpotifyRestrictedDeviceError,
)
from app.integrations.whoop.schemas import offset_timezone
from app.models import (
    EVENT_ERROR,
    EVENT_MANUAL_START,
    EVENT_MOOD_CHECK,
    STATUS_ACTIVE,
    STATUS_CREATED,
    STATUS_ENDED,
    STATUS_FAILED,
    TRACK_SOURCE_LIBRARY,
    Session,
    SessionEvent,
    SessionTrack,
    Track,
)
from app.services import behavior, body_state, playback, ranking
from app.services.profile_rules import MOODS, TargetProfile, build_profile
from app.services.token_store import TokenStore

logger = logging.getLogger(__name__)

#: About 25 tracks, which SPEC puts at roughly 90 minutes.
DEFAULT_TRACK_COUNT = 25

#: How many previous sessions count against freshness (SPEC section 5).
FRESHNESS_SESSIONS = 3

#: A live session older than this was abandoned, not left running. Without this a crash
#: during a session would block every future Chime in, since only one runs at a time.
STALE_SESSION_HOURS = 8

#: What the playlist description says. No track or artist data — it is written from the
#: body state and the mood only.
DESCRIPTION = "Made by Chime for how you were feeling. Temporary unless you keep it."

#: Why the mix is built but not playing, per reason. Spotify only lets an app press play on
#: a Premium account with the app already open somewhere, and neither of those can be
#: checked in advance (``GET /me`` no longer says, and nothing reports an open app). So
#: instead of throwing the session away, we hand over the playlist and let the user press
#: play in Spotify — which is the one thing that always works.
MANUAL_REASONS = {
    "NO_ACTIVE_DEVICE": (
        "Spotify wasn't open anywhere, so Chime couldn't press play. The mix is waiting in "
        "a playlist — open it in Spotify, or open Spotify and try again here."
    ),
    "PREMIUM_REQUIRED": (
        "Spotify only lets apps control playback on Premium accounts. The mix is built and "
        "waiting in a playlist — open it in Spotify and press play there."
    ),
    "DEVICE_RESTRICTED": (
        "That Spotify device won't take commands from other apps. The mix is waiting in a "
        "playlist — open it in Spotify and press play there."
    ),
    "PLAYBACK_REFUSED": (
        "Spotify wouldn't start playback. The mix is waiting in a playlist — open it in "
        "Spotify and press play there."
    ),
}


class SessionError(RuntimeError):
    """A session could not be started or ended. Carries a message meant for the user."""


class NoTracksError(SessionError):
    """The library has nothing to play: an empty or unsynced account."""


class SessionAlreadyLiveError(SessionError):
    """One session at a time. Carries the live one so the UI can offer to open it."""

    def __init__(self, message: str, session: Session) -> None:
        super().__init__(message)
        self.session = session


@dataclass(frozen=True, slots=True)
class ManualStart:
    """The mix exists, Spotify would not play it, and the user can from here."""

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class StartResult:
    """What Chime in produced, including where it ended up playing.

    ``manual`` set means the playlist is there but nothing is playing yet: a session in the
    ``created`` state waiting for a press of play in Spotify itself.
    """

    session: Session
    device_name: str | None = None
    manual: ManualStart | None = None


# ------------------------------------------------------------------- reading


def active_session(db: DbSession, user_id: int) -> Session | None:
    """The session still running for this user, if there is one.

    Ends anything left over from a previous run of the app first: a session with no
    process watching it is not active, whatever its row says.
    """
    _close_stale(db, user_id)
    return db.scalar(
        select(Session)
        .where(Session.user_id == user_id, Session.status.in_((STATUS_CREATED, STATUS_ACTIVE)))
        .order_by(Session.started_at.desc())
    )


def get_session(db: DbSession, user_id: int, session_id: int) -> Session | None:
    """One session, scoped to its owner. Every read goes through here for that reason."""
    return db.scalar(
        select(Session).where(Session.id == session_id, Session.user_id == user_id)
    )


def recent_track_ids(
    db: DbSession, user_id: int, *, sessions: int = FRESHNESS_SESSIONS
) -> set[int]:
    """Tracks used by the last few sessions, which freshness penalises (SPEC section 5)."""
    recent = db.scalars(
        select(Session.id)
        .where(Session.user_id == user_id)
        .order_by(Session.started_at.desc())
        .limit(sessions)
    ).all()
    if not recent:
        return set()
    return set(
        db.scalars(select(SessionTrack.track_id).where(SessionTrack.session_id.in_(recent))).all()
    )


def _close_stale(db: DbSession, user_id: int) -> None:
    cutoff = utcnow() - timedelta(hours=STALE_SESSION_HOURS)
    stale = db.scalars(
        select(Session).where(
            Session.user_id == user_id,
            Session.status.in_((STATUS_CREATED, STATUS_ACTIVE)),
            Session.started_at < cutoff,
        )
    ).all()
    for session in stale:
        # Ended, not failed: it did run. The playlist is left alone deliberately — this is
        # not the user asking to tidy up, and removing something silently hours later
        # would be the wrong kind of surprise.
        session.status = STATUS_ENDED
        session.ended_at = as_utc(session.started_at) or utcnow()
        session.summary = {**(session.summary or {}), "abandoned": True}
        logger.info("closed an abandoned session", extra={"session_id": session.id})
    if stale:
        db.commit()


# ------------------------------------------------------------------- chime in


async def chime_in(
    db: DbSession,
    user_id: int,
    *,
    mood: str | None = None,
    session_type: str | None = None,
    intent: str = "match",
    count: int = DEFAULT_TRACK_COUNT,
    spotify: SpotifyClient | None = None,
) -> StartResult:
    """SPEC section 6's six steps, in order."""
    live = active_session(db, user_id)
    if live is not None:
        raise SessionAlreadyLiveError("A session is already running.", live)
    if mood is not None and mood not in MOODS:
        raise SessionError(f"Unknown mood {mood!r}")

    # 1 + 2: WHOOP (refreshed only if stale), then the profile. Neither can fail the
    # session: a disconnected WHOOP just means mood and time of day carry it.
    state = await body_state.read(user_id)
    try:
        profile = build_profile(state, mood=mood, session_type=session_type, intent=intent)
    except ValueError as exc:
        raise SessionError(str(exc)) from exc

    # 3: rank. Nothing external yet, so a library problem costs nothing to discover.
    pool = ranking.candidates_for(db, user_id)
    if not pool:
        raise NoTracksError(
            "There are no songs to choose from yet. Sync your library from settings first."
        )
    order = ranking.rank(pool, profile, count=count, recent_track_ids=recent_track_ids(db, user_id))
    if not order:
        raise NoTracksError("Nothing in your library fits this session.")

    session = _persist_start(db, user_id, profile=profile, mood=mood, state=state, order=order)

    client = spotify or SpotifyClient(TokenStore(SessionLocal, user_id))
    try:
        return await _publish(client, db, session, order=order)
    except (SpotifyError, SessionError) as exc:
        _fail(db, session, exc)
        raise
    finally:
        if spotify is None:
            await client.aclose()


def _persist_start(
    db: DbSession,
    user_id: int,
    *,
    profile: TargetProfile,
    mood: str | None,
    state: body_state.BodyState,
    order: list[ranking.Ranked],
) -> Session:
    """Write the session and its running order before anything external happens.

    So that a failure a moment later has somewhere to record itself, and so the playlist
    Spotify is about to be asked for is never the only record that a session was tried.
    """
    session = Session(
        user_id=user_id,
        status=STATUS_CREATED,
        type=profile.type,
        intent=profile.intent,
        mood_in=mood,
        started_at=utcnow(),
        body_in=_body_json(state),
        target_profile=profile.as_dict(positions=len(order)),
        why_text=why_text(profile),
    )
    db.add(session)
    db.flush()  # assigns the id the tracks below need

    for item in order:
        db.add(
            SessionTrack(
                session_id=session.id,
                position=item.position,
                track_id=item.candidate.track_id,
                source=TRACK_SOURCE_LIBRARY,
                score_breakdown=item.breakdown,
            )
        )
    db.commit()
    db.refresh(session)
    return session


async def _publish(
    client: SpotifyClient,
    db: DbSession,
    session: Session,
    *,
    order: list[ranking.Ranked],
) -> StartResult:
    """Steps 4 and 5: a playlist with the tracks in it, playing if Spotify allows it."""
    name = playlist_name(db, session)
    playlist = await playlists.create_playlist(client, name=name, description=DESCRIPTION)
    if not playlist.id or not playlist.uri:
        raise SessionError("Spotify created a playlist but did not say where it is.")

    session.playlist_uri = playlist.uri
    session.playlist_name = playlist.name or name
    db.commit()

    uris = [f"spotify:track:{item.candidate.spotify_track_id}" for item in order]
    try:
        await playlists.add_items(client, playlist.id, uris)
    except SpotifyError:
        # An empty playlist is no use to anybody, so this one goes back out of the library.
        await _discard_playlist(client, session)
        raise

    try:
        device_name = await _begin_playback(client, db, session)
    except SpotifyAuthError:
        # Nothing works from here, a link included: the Spotify login itself has gone.
        await _discard_playlist(client, session)
        raise
    except SpotifyError as exc:
        return StartResult(session=session, manual=_record_manual(db, session, exc))

    return StartResult(session=session, device_name=device_name)


async def _begin_playback(client: SpotifyClient, db: DbSession, session: Session) -> str | None:
    """Find a device and start this session's playlist on it. Raises if Spotify refuses.

    Marks the session active, which is the one thing that distinguishes a session playing
    from a session waiting to be started by hand.
    """
    if not session.playlist_uri:
        raise SessionError("This session has no playlist to play.")

    devices = await player.get_devices(client)
    device = player.pick_device(devices)
    if device is None or not device.id:
        raise SpotifyNoActiveDeviceError(
            "Spotify isn't open on any device. Open Spotify, play anything for a second to "
            "wake it up, then try again.",
            code="NO_ACTIVE_DEVICE",
        )

    if not device.is_active:
        await player.transfer_playback(client, device.id)
    await player.start_playback(client, context_uri=session.playlist_uri, device_id=device.id)

    session.status = STATUS_ACTIVE
    db.commit()
    db.refresh(session)
    return device.name


async def start_playback(
    db: DbSession,
    user_id: int,
    session: Session,
    *,
    spotify: SpotifyClient | None = None,
) -> StartResult:
    """Try again on a session that is built but waiting (the "Try again" button).

    Records why it failed again before raising, so the screen's explanation is the current
    one rather than the reason from the original Chime in.
    """
    if session.status == STATUS_ACTIVE:
        return StartResult(session=session)
    if not session.is_live:
        raise SessionError("That session has already ended.")

    client = spotify or SpotifyClient(TokenStore(SessionLocal, user_id))
    try:
        device_name = await _begin_playback(client, db, session)
    except SpotifyError as exc:
        if not isinstance(exc, SpotifyAuthError):
            _record_manual(db, session, exc)
        raise
    finally:
        if spotify is None:
            await client.aclose()

    return StartResult(session=session, device_name=device_name)


def manual_start(db: DbSession, session: Session) -> ManualStart | None:
    """Why a built session is not playing, if that is where it is stuck.

    Derived rather than stored on the row: ``created`` plus a playlist can only mean the
    playlist was made and playback never started. The reason is on the last event.
    """
    if session.status != STATUS_CREATED or not session.playlist_uri:
        return None
    event = db.scalar(
        select(SessionEvent)
        .where(SessionEvent.session_id == session.id, SessionEvent.type == EVENT_MANUAL_START)
        .order_by(SessionEvent.ts.desc(), SessionEvent.id.desc())
        .limit(1)
    )
    payload = (event.payload or {}) if event is not None else {}
    code = str(payload.get("code") or "PLAYBACK_REFUSED")
    fallback = MANUAL_REASONS.get(code, MANUAL_REASONS["PLAYBACK_REFUSED"])
    return ManualStart(code=code, message=str(payload.get("message") or fallback))


def _record_manual(db: DbSession, session: Session, exc: SpotifyError) -> ManualStart:
    code = _manual_code(exc)
    manual = ManualStart(code=code, message=MANUAL_REASONS[code])
    db.add(
        SessionEvent(
            session_id=session.id,
            type=EVENT_MANUAL_START,
            payload={"code": code, "message": manual.message, "spotify_code": exc.code},
        )
    )
    db.commit()
    logger.info(
        "a session is waiting to be started by hand",
        extra={"session_id": session.id, "code": code},
    )
    return manual


def _manual_code(exc: SpotifyError) -> str:
    if isinstance(exc, SpotifyNoActiveDeviceError):
        return "NO_ACTIVE_DEVICE"
    if isinstance(exc, SpotifyPremiumRequiredError):
        return "PREMIUM_REQUIRED"
    if isinstance(exc, SpotifyRestrictedDeviceError):
        return "DEVICE_RESTRICTED"
    return "PLAYBACK_REFUSED"


def _fail(db: DbSession, session: Session, exc: Exception) -> None:
    session.status = STATUS_FAILED
    session.ended_at = utcnow()
    db.add(
        SessionEvent(
            session_id=session.id,
            type=EVENT_ERROR,
            payload={"error": type(exc).__name__, "message": str(exc)},
        )
    )
    db.commit()


async def _discard_playlist(client: SpotifyClient, session: Session) -> None:
    """Best effort: a cleanup that fails must not replace the error that caused it."""
    if not session.playlist_id:
        return
    try:
        await playlists.remove_playlist(client, session.playlist_id)
    except SpotifyError as exc:
        logger.warning(
            "could not remove a session playlist",
            extra={"session_id": session.id, "error": exc.message},
        )


async def _playlist_is_gone(client: SpotifyClient, session: Session) -> bool:
    """Confirm a removal actually happened, rather than taking the 200 on trust.

    One extra read at Chime out, spent because this is the promise the product makes in one
    sentence ("removes the playlist unless you keep it") and it was quietly broken for two
    real sessions before anyone noticed. Now a removal that does not remove says so on the
    spot, in the summary, instead of leaving playlists behind for someone to find later.

    A failure to *check* is not a failure to remove: the 200 stands, and this returns True.
    """
    if not session.playlist_uri:
        return True
    try:
        answers = await playlists.is_in_library(client, [session.playlist_uri])
    except SpotifyError as exc:
        logger.info(
            "could not confirm a playlist removal",
            extra={"session_id": session.id, "error": exc.message},
        )
        return True
    return not (answers and answers[0])


# ------------------------------------------------------------------ mood check


def record_mood(db: DbSession, session: Session, mood: str) -> Session:
    """A mid-session mood check. Recorded now; it becomes an adaptation trigger in phase 6."""
    if mood not in MOODS:
        raise SessionError(f"Unknown mood {mood!r}")
    if not session.is_live:
        raise SessionError("That session has already ended.")
    db.add(SessionEvent(session_id=session.id, type=EVENT_MOOD_CHECK, payload={"mood": mood}))
    db.commit()
    db.refresh(session)
    return session


# ------------------------------------------------------------------ chime out


async def chime_out(
    db: DbSession,
    user_id: int,
    session: Session,
    *,
    keep: bool = False,
    name: str | None = None,
    mood_out: str | None = None,
    pause: bool = True,
    spotify: SpotifyClient | None = None,
) -> Session:
    """SPEC section 6's Chime out, in its four steps.

    The session is ended in the database whatever Spotify does. A playlist we could not
    rename or remove is a mess to apologise for, not a reason to keep someone trapped in a
    session they have said they are finished with.
    """
    if mood_out is not None and mood_out not in MOODS:
        raise SessionError(f"Unknown mood {mood_out!r}")
    if not session.is_live:
        raise SessionError("That session has already ended.")

    client = spotify or SpotifyClient(TokenStore(SessionLocal, user_id))
    problems: list[str] = []
    try:
        if pause:
            try:
                await player.pause(client)
            except SpotifyError as exc:
                # Nothing playing, or playback moved elsewhere. Not worth failing over.
                logger.info(
                    "could not pause at chime out",
                    extra={"session_id": session.id, "error": exc.message},
                )

        if keep:
            kept_name = (name or "").strip() or _kept_name(db, session)
            try:
                if session.playlist_id:
                    await playlists.rename_playlist(client, session.playlist_id, name=kept_name)
                session.playlist_name = kept_name
                session.kept = True
            except SpotifyError as exc:
                problems.append("We kept the playlist but couldn't rename it.")
                session.kept = True
                logger.warning(
                    "could not rename a kept playlist",
                    extra={"session_id": session.id, "error": exc.message},
                )
        elif session.playlist_id:
            try:
                await playlists.remove_playlist(client, session.playlist_id)
            except SpotifyError as exc:
                problems.append(
                    "We couldn't remove the playlist from Spotify. You can delete it yourself."
                )
                logger.warning(
                    "could not remove a session playlist",
                    extra={"session_id": session.id, "error": exc.message},
                )
            else:
                if await _playlist_is_gone(client, session):
                    session.playlist_removed_at = utcnow()
                else:
                    problems.append(
                        "Spotify still has the playlist in your library. "
                        "You can remove it there."
                    )
    finally:
        if spotify is None:
            await client.aclose()

    # The track playing at Chime out has nothing to move off it, so this is the only thing
    # that ever closes it — and it must happen before the summary counts what played.
    playback.finish_open(db, session)
    if session.kept:
        behavior.record_keep(db, session)

    # 1: a final body snapshot. Daily-level, so expect small deltas.
    state = await body_state.read(user_id)

    session.mood_out = mood_out
    session.ended_at = utcnow()
    session.status = STATUS_ENDED
    session.body_out = _body_json(state)
    session.summary = summarise(db, session, problems=problems)
    db.commit()
    db.refresh(session)
    return session


def summarise(
    db: DbSession, session: Session, *, problems: list[str] | None = None
) -> dict[str, object]:
    """Minutes and track counts (SPEC section 6, step 2).

    ``played`` and ``skipped`` come from ``session_tracks``, which the phase 6 poller fills
    in (:mod:`app.services.playback`). A session where nothing was measured still reports
    them as unmeasured rather than as zero — playback can be unreadable for an entire
    session, and "0 played" would be a claim about listening rather than about measuring.
    """
    tracks = db.scalars(
        select(SessionTrack).where(SessionTrack.session_id == session.id)
    ).all()
    started = as_utc(session.started_at)
    ended = as_utc(session.ended_at) or utcnow()
    minutes = round(max(0.0, (ended - started).total_seconds()) / 60, 1) if started else 0.0

    played = sum(1 for track in tracks if track.started_at is not None)
    skipped = sum(1 for track in tracks if track.skipped)
    measured = played > 0

    summary: dict[str, object] = {
        "minutes": minutes,
        "queued": len(tracks),
        "played": played if measured else None,
        "skipped": skipped if measured else None,
        "skip_rate": round(skipped / played, 3) if measured and played else None,
    }
    if problems:
        summary["problems"] = problems
    return summary


# ------------------------------------------------------------------- wording


def why_text(profile: TargetProfile) -> str:
    """One or two plain sentences for "why this mix".

    Built from the profile's own notes, which are written where the decisions are made, so
    the explanation cannot drift from the behaviour. SPEC allows an LLM to write this from
    the same non-Spotify inputs; this is the template it falls back to, and for now it is
    the only one.
    """
    if profile.notes:
        return " ".join(profile.notes)
    shape = "climbs" if profile.end > profile.start else "comes down"
    if profile.end == profile.start:
        shape = "holds steady"
    return f"A {profile.type.replace('_', ' ')} mix that {shape}."


def playlist_name(db: DbSession, session: Session) -> str:
    """``Chime · <Type> · <time>`` (SPEC section 6, step 4), on the member's own clock."""
    spoken = session.type.replace("_", " ").capitalize()
    local = _local_start(db, session)
    return f"Chime · {spoken} · {local.strftime('%I:%M %p').lstrip('0').lower()}"


def _kept_name(db: DbSession, session: Session) -> str:
    """The default name for a playlist the user decided to keep.

    Dropping the "Chime ·" prefix on purpose: once it is theirs it is a playlist, not a
    session, and it should not look like something the app might come back and tidy away.
    """
    spoken = session.type.replace("_", " ").capitalize()
    local = _local_start(db, session)
    # %-d is glibc only and this is developed on Windows, so strip the zero by hand.
    return f"{spoken} · {local.strftime('%d %b').lstrip('0')}"


def _local_start(db: DbSession, session: Session) -> datetime:
    """When the session started, on the clock the *user* was looking at.

    A WHOOP day starts when they wake and their UTC offset arrives with the cycle. Without
    WHOOP there is nothing better than UTC — which is fine, because this only ever decides
    what a playlist is called.
    """
    started = as_utc(session.started_at) or utcnow()
    return started.astimezone(offset_timezone(body_state.latest_offset(db, session.user_id)))


def _body_json(state: body_state.BodyState) -> dict[str, object]:
    """Body state as stored on the session. Dates become strings; JSON has no date type."""
    return {
        "connected": state.connected,
        "has_data": state.has_data,
        "recovery": state.recovery,
        "hrv_ms": state.hrv_ms,
        "rhr": state.rhr,
        "sleep_performance": state.sleep_performance,
        "day_strain": state.day_strain,
        "minutes_since_last_workout": state.minutes_since_last_workout,
        "readiness": state.readiness,
        "day_part": state.day_part,
        "calibrating": state.calibrating,
        "date": state.date.isoformat() if state.date else None,
    }


def track_rows(db: DbSession, session_id: int) -> list[tuple[SessionTrack, Track]]:
    """A session's running order with its track metadata, in playing order."""
    rows = db.execute(
        select(SessionTrack, Track)
        .join(Track, Track.id == SessionTrack.track_id)
        .where(SessionTrack.session_id == session_id)
        .order_by(SessionTrack.position)
    ).all()
    return [(session_track, track) for session_track, track in rows]
