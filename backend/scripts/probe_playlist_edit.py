"""Does editing a playlist interrupt what it is playing?

    cd backend && uv run python -m scripts.probe_playlist_edit

This is the one question in phase 6 that documentation cannot answer, because it is about a
Spotify *client's* behaviour rather than the Web API's contract: mid-session adaptation appends
tracks to the playlist you are listening to right now, and if that made playback stutter or
jump, adaptation would have to queue tracks through ``POST /me/player/queue`` instead.

So it measures. With something playing from a Chime playlist it reads playback, removes the
last item, reads playback, puts it back, and reads playback again — printing whether playback
survived each edit and where the needle was. A clean result is three reads with ``playing``
true, the same track id throughout, and progress that only ever moves forwards.

Read-only apart from the one item it removes and re-adds, on a playlist you name. It refuses to
run against a playlist Chime does not own a session for, so a hand-made playlist cannot be
edited by accident.

What to do with the answer is in ``docs/PLAN.md`` phase 6: if playback survives, adaptation
edits the playlist (which is what it does today, and what keeps the session's record and the
user's playlist the same thing). If it does not, adaptation has to queue instead, and a queued
track is invisible to ``GET /me/player`` context — so the measurement would get worse.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.db.session import SessionLocal
from app.integrations.spotify import player, playlists
from app.integrations.spotify.client import SpotifyClient
from app.integrations.spotify.errors import SpotifyError
from app.models import LIVE_STATUSES, Session, User
from app.services.token_store import TokenStore


async def read(client: SpotifyClient, label: str) -> tuple[str | None, int | None]:
    """Print one playback reading. Track id and progress only: no names (CLAUDE.md rule 7)."""
    state = await player.get_playback_state(client)
    if state is None:
        print(f"{label:<18} nothing playing")
        return None, None
    context = state.context.uri if state.context else None
    print(
        f"{label:<18} playing={str(state.is_playing):<5} "
        f"track={state.track_id or '-':<24} progress={state.progress_ms or 0:>7} ms  "
        f"context={context or '-'}"
    )
    return state.track_id, state.progress_ms


async def probe(session_id: int | None) -> int:
    with SessionLocal() as db:
        statement = select(Session).where(Session.status.in_(LIVE_STATUSES))
        if session_id is not None:
            statement = select(Session).where(Session.id == session_id)
        session = db.scalar(statement.order_by(Session.started_at.desc()).limit(1))
        if session is None:
            print("No live session found. Chime in first, then run this while it plays.")
            return 1
        if not session.playlist_id:
            print(f"Session {session.id} has no playlist to edit.")
            return 1
        # Read everything needed now: the row is detached once this block ends.
        sid = session.id
        user_id = session.user_id
        playlist_id = session.playlist_id
        # The last track in the running order: the one furthest from being played, so removing
        # it for a few seconds cannot affect what is actually playing.
        last = max(session.tracks, key=lambda row: row.position, default=None)
        if last is None:
            print(f"Session {session.id} has no tracks.")
            return 1
        uri = f"spotify:track:{last.track.spotify_track_id}"
        total = len(session.tracks)

    print(f"session {sid}, playlist {playlist_id}, {total} tracks")
    print("editing the LAST item in the running order, so nothing near the needle moves.\n")

    client = SpotifyClient(TokenStore(SessionLocal, user_id))
    try:
        before = await read(client, "before")
        if before[0] is None:
            print("\nNothing is playing, so there is nothing to interrupt. Press play first.")
            return 1

        await playlists.remove_items(client, playlist_id, [uri])
        await asyncio.sleep(2)
        after_remove = await read(client, "after remove")

        await playlists.add_items(client, playlist_id, [uri])
        await asyncio.sleep(2)
        after_add = await read(client, "after re-add")
    except SpotifyError as exc:
        print(f"\nSpotify said no: {exc.code or 'error'} — {exc.message}")
        return 1
    finally:
        await client.aclose()

    same_track = before[0] == after_remove[0] == after_add[0]
    moved_forward = all(
        reading[1] is not None for reading in (before, after_remove, after_add)
    ) and before[1] <= after_remove[1] <= after_add[1]

    print()
    if same_track and moved_forward:
        print("VERDICT: editing did not interrupt playback. Adaptation can edit the playlist.")
        print("         (Same track throughout, progress only moved forwards.)")
        return 0
    print("VERDICT: playback changed across an edit. Adaptation should queue instead:")
    print("         POST /me/player/queue, scope user-modify-playback-state (already granted).")
    print("         Note in docs/PLAN.md phase 6 and open app/services/adaptation.py.")
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--session",
        type=int,
        default=None,
        help="Session id to probe. Defaults to the newest live session.",
    )
    args = parser.parse_args()
    with SessionLocal() as db:
        if db.scalar(select(User.id).limit(1)) is None:
            print("No user in the database. Sign in through the app first.")
            return 1
    return asyncio.run(probe(args.session))


if __name__ == "__main__":
    sys.exit(main())
