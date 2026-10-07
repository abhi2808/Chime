"""Was the mix actually any good? Skip rates cut by what the ranking claimed to know.

    cd backend && uv run python -m scripts.evaluate
    cd backend && uv run python -m scripts.evaluate --days 30 --min 5

Chime's ranking is a set of assertions — that a green recovery wants more energy, that a
well-tagged track is a safer bet than an untagged one, that the energy curve is worth
following. Until phase 6 measured what played, none of them could be checked. This checks
them, the only way a deterministic ranker can be checked: by comparing the skip rate across
the buckets the ranker itself used to make the decision.

How to read it. The skip rate is the number the whole thing turns on, and the baseline at the
top is what any bucket has to beat to mean anything. A cut where the rate barely moves is a
component that is not earning its weight; a cut where it moves a lot is one worth more. The
two to watch are:

* **energy fit** — ``|track energy − target at that position|``. If the close band does not
  skip less than the far band, the curve is decoration and ``WEIGHT_ENERGY`` (0.50) is
  misplaced.
* **tag confidence** — if low-confidence tracks skip no more than high-confidence ones, the
  tagging is not actually informative and the library needs more of it before the ranking can
  be trusted.

Honest about its own limits, because a number that looks precise and is not is worse than no
number. Every caveat is printed with the output: skips are *measured*, so a session played
without the app open (or through a pause the poller read as silence) contributes less; a
session ended mid-track leaves that track unjudged on purpose; and a bucket with a handful of
tracks in it is noise, which is what ``--min`` is for.

Numbers only, and cuts only by body state, mood, time and the ranker's own scores. No track,
artist, album or playlist names are read, printed or written anywhere (CLAUDE.md rule 7).
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.clock import utcnow
from app.db.session import SessionLocal
from app.models import STATUS_FAILED, Session

#: ``|energy − target|`` bands. Energy runs 1-5, so 0.5 is "on target" and 2+ is "nothing like
#: what was asked for" — which is what a thin library forces when the curve wants a 5.
ENERGY_BANDS: tuple[tuple[str, float], ...] = (
    ("on target (<0.5)", 0.5),
    ("near (0.5-1.0)", 1.0),
    ("off (1.0-2.0)", 2.0),
    ("nothing like it (2+)", float("inf")),
)

#: Tag confidence bands. Below 0.3 is effectively "we guessed".
CONFIDENCE_BANDS: tuple[tuple[str, float], ...] = (
    ("untagged (0)", 0.0),
    ("weak (0-0.4)", 0.4),
    ("fair (0.4-0.7)", 0.7),
    ("strong (0.7+)", float("inf")),
)


@dataclass(slots=True)
class Tally:
    """Judged tracks and how many of them were skipped, for one bucket."""

    judged: int = 0
    skipped: int = 0

    @property
    def rate(self) -> float:
        return self.skipped / self.judged if self.judged else 0.0


@dataclass(slots=True)
class Cut:
    """One way of slicing the same tracks."""

    name: str
    question: str
    buckets: dict[str, Tally] = field(default_factory=lambda: defaultdict(Tally))

    def add(self, bucket: str | None, *, skipped: bool) -> None:
        tally = self.buckets[bucket if bucket is not None else "(not recorded)"]
        tally.judged += 1
        tally.skipped += int(skipped)


def band(value: float, bands: tuple[tuple[str, float], ...]) -> str:
    for label, ceiling in bands:
        if value <= ceiling:
            return label
    return bands[-1][0]


def collect(db: DbSession, *, days: int) -> tuple[list[Cut], Tally, int, int]:
    """Walk every judged track in the window and drop it into each cut.

    "Judged" means the poller decided about it: ``finished_at`` is set. A track that started
    and was never closed is still playing or was closed unjudged at Chime out, and counting
    either as a listen would flatter the numbers.
    """
    since = utcnow() - timedelta(days=days)

    cuts = [
        Cut("readiness", "does the body state the mix was built for change how it lands?"),
        Cut("day part", "is some time of day harder to get right than others?"),
        Cut("session type", "which kinds of session work?"),
        Cut("intent", "does asking to shift mood work as well as asking to match it?"),
        Cut("mood in", "which mood is hardest to serve?"),
        Cut("energy fit", "does landing near the target energy actually reduce skips?"),
        Cut("tag confidence", "is the tagging informative, or is it noise with a number on it?"),
        Cut("track source", "do adapted tracks land as well as the ones chosen up front?"),
        Cut("position", "does the running order hold up, or does the tail get abandoned?"),
    ]
    by_name = {cut.name: cut for cut in cuts}
    overall = Tally()

    sessions = db.scalars(
        select(Session)
        .where(Session.started_at >= since, Session.status != STATUS_FAILED)
        .order_by(Session.started_at)
    ).all()

    counted_sessions = 0
    for session in sessions:
        body = session.body_in or {}
        judged_here = 0
        for row in session.tracks:
            if row.finished_at is None:
                continue
            skipped = bool(row.skipped)
            judged_here += 1
            overall.judged += 1
            overall.skipped += int(skipped)

            by_name["readiness"].add(body.get("readiness"), skipped=skipped)
            by_name["day part"].add(body.get("day_part"), skipped=skipped)
            by_name["session type"].add(session.type, skipped=skipped)
            by_name["intent"].add(session.intent, skipped=skipped)
            by_name["mood in"].add(session.mood_in, skipped=skipped)
            by_name["track source"].add(row.source, skipped=skipped)
            by_name["position"].add(_position_band(row.position), skipped=skipped)

            breakdown = row.score_breakdown or {}
            energy = _number(breakdown.get("energy"))
            target = _number(breakdown.get("target"))
            if energy is not None and target is not None:
                by_name["energy fit"].add(
                    band(abs(energy - target), ENERGY_BANDS), skipped=skipped
                )
            confidence = _number(breakdown.get("confidence"))
            if confidence is not None:
                by_name["tag confidence"].add(
                    band(confidence, CONFIDENCE_BANDS), skipped=skipped
                )
        if judged_here:
            counted_sessions += 1

    return cuts, overall, len(sessions), counted_sessions


def _position_band(position: int) -> str:
    if position < 5:
        return "opening (1-5)"
    if position < 15:
        return "middle (6-15)"
    return "tail (16+)"


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def report(cuts: list[Cut], overall: Tally, *, sessions: int, measured: int, minimum: int) -> None:
    print()
    print(f"{overall.judged} judged tracks across {measured} of {sessions} sessions")
    if not overall.judged:
        print()
        print("Nothing measured yet. The counters need sessions that actually played, with")
        print("the backend running so the poller could watch them (or the session screen open).")
        return
    print(f"baseline skip rate: {overall.rate:.0%}   <- every bucket below is against this")
    print(f"buckets with fewer than {minimum} judged tracks are hidden as noise")

    for cut in cuts:
        shown = {
            name: tally
            for name, tally in cut.buckets.items()
            if tally.judged >= minimum and name != "(not recorded)"
        }
        print()
        print(f"{cut.name.upper()}  — {cut.question}")
        if not shown:
            print("  not enough data yet")
            continue
        for name, tally in sorted(shown.items(), key=lambda item: -item[1].rate):
            delta = tally.rate - overall.rate
            arrow = "worse" if delta > 0.02 else ("better" if delta < -0.02 else "     ")
            print(
                f"  {name:<22} {tally.rate:>5.0%} skipped  "
                f"({tally.skipped:>4}/{tally.judged:<4})  {delta:+.0%} {arrow}"
            )

    print()
    print("Caveats, and they matter:")
    print("  * Skips are sampled, not logged. Spotify only says what is playing now, so a")
    print("    track shorter than the poll interval can be missed and a session played with")
    print("    the app shut is measured only every 20 s by the backend's own poller.")
    print("  * A session ended part way through a track leaves that track unjudged on")
    print("    purpose: stopping Chime is not rejecting a song.")
    print("  * A skip is not always a verdict. Sometimes a song is fine and the moment is not.")
    print("  * Small buckets move on one skip. Raise --min before believing a difference.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Skip rates by what the ranking knew.")
    parser.add_argument("--days", type=int, default=90, help="How far back to look.")
    parser.add_argument(
        "--min", type=int, default=10, dest="minimum", help="Hide buckets thinner than this."
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        cuts, overall, sessions, measured = collect(db, days=args.days)
    report(cuts, overall, sessions=sessions, measured=measured, minimum=args.minimum)
    return 0


if __name__ == "__main__":
    sys.exit(main())
