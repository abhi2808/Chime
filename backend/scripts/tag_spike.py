"""Phase 3 spike: how much of a real library can MusicBrainz tag?

    cd backend && uv run python -m scripts.tag_spike --limit 150

Prints numbers only. Tag names go to ``data/unmatched_tags.txt`` and track names go
nowhere: the report has to be safe to paste anywhere, and CLAUDE.md rule 7 keeps Spotify
content out of any model's context.

``--dry-run`` measures without writing tag rows.

Safe to interrupt: only untagged tracks are read and each one is committed as it lands, so
Ctrl+C prints the partial numbers and a re-run continues from there.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from collections.abc import Callable

import httpx
from sqlalchemy import select

from app.core.config import PROJECT_ROOT, settings
from app.db.session import SessionLocal
from app.integrations.musicbrainz import MusicBrainzClient, MusicBrainzError
from app.models import User
from app.services.track_tagger import (
    MusicBrainzTagSource,
    TagRun,
    tag_tracks,
    unknown_tracks,
    untagged_tracks,
)

UNMATCHED_FILE = PROJECT_ROOT / "data" / "unmatched_tags.txt"

BANDS = ((1.0, 1.5, "1.0-1.5 barely moving"), (1.5, 2.5, "1.5-2.5 quiet"),
         (2.5, 3.5, "2.5-3.5 middling"), (3.5, 4.5, "3.5-4.5 driving"),
         (4.5, 5.01, "4.5-5.0 flat out"))

#: Print a progress line this often. Small enough to prove it is alive within a minute.
PROGRESS_EVERY = 20


def progress_printer(total: int, started: float) -> Callable[[TagRun], None]:
    """A line every few tracks: half an hour of silence is indistinguishable from a hang.

    Counts only, like the rest of this script — the point of a progress line is "still
    working, here is when it ends", which needs no track names to say.
    """

    def show(run: TagRun) -> None:
        done = run.considered
        if done % PROGRESS_EVERY and done != total:
            return
        rate = (time.monotonic() - started) / done
        left = (total - done) * rate
        print(
            f"{done:>5}/{total}  tagged {run.tagged:<5} none {run.missing:<4}"
            f"failed {run.failed:<4}{rate:.1f}s/track  ~{left / 60:.0f} min left",
            flush=True,
        )

    return show


def report(run: TagRun, *, elapsed: float) -> None:
    print("\n--- coverage ---")
    print(f"tracks considered      {run.considered}")
    print(f"tagged (map understood){run.tagged:>6}  {run.coverage:.1%}")
    print(f"found but unmapped     {run.unmapped:>6}  tags we have no entry for")
    print(f"not in MusicBrainz     {run.missing:>6}")
    print(f"lookup failures        {run.failed:>6}")
    print(f"left alone (manual)    {run.manual:>6}")
    print(f"matched via            {dict(run.via)}")

    if run.confidence:
        print("\n--- confidence ---")
        print(f"mean   {statistics.fmean(run.confidence):.2f}")
        print(f"median {statistics.median(run.confidence):.2f}")
        print(f"below 0.34  {sum(1 for c in run.confidence if c < 0.34)}")

    if run.energy:
        print("\n--- energy spread (can the curves be filled?) ---")
        for low, high, label in BANDS:
            count = sum(1 for energy in run.energy if low <= energy < high)
            bar = "#" * round(40 * count / len(run.energy))
            print(f"{label:<22}{count:>5}  {bar}")
        print(f"mean {statistics.fmean(run.energy):.2f}")

    print("\n--- cost ---")
    print(f"elapsed {elapsed / 60:.1f} min for {run.considered} tracks")
    if run.considered:
        print(f"~{elapsed / run.considered:.1f} s per track at the configured pacing")

    if run.unmatched:
        UNMATCHED_FILE.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"{count:>5}  {tag}" for tag, count in run.unmatched.most_common()
        ]
        UNMATCHED_FILE.write_text(
            "# Tags MusicBrainz supplied that data/tag_map.yaml has no entry for.\n"
            "# Count = how many tracks wanted each one. Highest first.\n"
            + "\n".join(lines)
            + "\n",
            encoding="utf-8",
        )
        print(f"\n{len(run.unmatched)} unmapped tag names written to {UNMATCHED_FILE}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=150, help="tracks to try (default 150)")
    parser.add_argument("--dry-run", action="store_true", help="measure without writing rows")
    parser.add_argument(
        "--no-artist-fallback",
        action="store_true",
        help="recording tags only, to separate the two coverage numbers",
    )
    parser.add_argument(
        "--retry-unknown",
        action="store_true",
        help="re-check tracks a previous run found nothing for, instead of new ones",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        user = db.scalars(select(User).order_by(User.id)).first()
        if user is None:
            print("No user in the database. Log in with Spotify first.")
            return 1
        if args.retry_unknown:
            tracks = unknown_tracks(db, user.id, limit=args.limit)
            if not tracks:
                print("No tracks are marked unknown. Nothing to re-check.")
                return 0
        else:
            tracks = untagged_tracks(db, user.id, limit=args.limit)
            if not tracks:
                print(
                    "Nothing untagged. Add --retry-unknown to re-check the ones MusicBrainz"
                    " had no answer for, or clear track_tags to re-measure from scratch."
                )
                return 0

        print(f"tagging {len(tracks)} tracks via MusicBrainz")
        print(f"pacing {settings.musicbrainz_min_request_interval_ms} ms between requests")
        print(f"user agent {settings.musicbrainz_agent!r}")
        print(f"score floor {settings.musicbrainz_min_score}")
        print("(no track or artist names are printed)\n")

        started = time.monotonic()
        # Owned out here so an interrupted run can still report what it managed.
        run = TagRun()
        status = 0
        try:
            async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as http:
                client = MusicBrainzClient(client=http)
                source = MusicBrainzTagSource(
                    client, artist_fallback=not args.no_artist_fallback
                )
                await tag_tracks(
                    db,
                    tracks,
                    source,
                    run=run,
                    persist=not args.dry_run,
                    on_progress=progress_printer(len(tracks), started),
                )
        except MusicBrainzError as exc:
            print(f"stopped: {exc.message}")
            status = 1
        except (KeyboardInterrupt, asyncio.CancelledError):
            # Ctrl+C is a normal way to end a half-hour job, not a crash. Every track
            # before this one is committed, and re-running picks up the remainder.
            print(f"\nstopped after {run.considered} of {len(tracks)} tracks.")
            print("What was tagged is saved. Run it again to carry on.")
            status = 130
        finally:
            if run.considered:
                report(run, elapsed=time.monotonic() - started)
    return status


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:  # Ctrl+C before the loop owns it
        raise SystemExit(130) from None
