"""Re-apply the tag map to the whole library from stored ``track_tags.raw_tags``.

    cd backend && uv run python -m scripts.retag            # show what would change
    cd backend && uv run python -m scripts.retag --write    # change it

No network: every tag the sources gave us is already on the row, which is the whole point
of keeping ``raw_tags``. Tuning the map or the weighting is therefore a few seconds, not
the 35 minutes a re-fetch costs.

Prints numbers only — distributions before and after, and how many rows move. Tag names go
to ``data/unmatched_tags.txt`` as usual, and track names go nowhere.
"""

from __future__ import annotations

import argparse
import statistics
from collections import Counter

from sqlalchemy import select

from app.core.config import PROJECT_ROOT
from app.db.session import SessionLocal
from app.models import TrackTag
from app.models.track_tag import SOURCE_EXTERNAL, SOURCE_MANUAL, SOURCE_UNKNOWN
from app.services.tagging import TagMap, compute, load_tag_map

BANDS = ((1.0, 1.5), (1.5, 2.5), (2.5, 3.5), (3.5, 4.5), (4.5, 5.01))

INFLUENCE_FILE = PROJECT_ROOT / "data" / "tag_influence.txt"
UNMATCHED_FILE = PROJECT_ROOT / "data" / "unmatched_tags.txt"


def write_influence(influence: Counter[str], tag_map: TagMap, *, tracks: int) -> None:
    """Which map entries actually decide this library's energies, and at what value.

    A file rather than stdout, and counts rather than any kind of summary, because the
    interesting question — "is this genre's energy right?" — is one only the owner of the
    library can answer, by looking. Tag names are not printed anywhere a model can read
    them (CLAUDE.md rule 7).
    """
    lines = [
        f"{count:>5}  {count / tracks:>5.1%}  energy {tag_map.entries[name].energy:>4.1f}  {name}"
        for name, count in influence.most_common()
        if name in tag_map.entries
    ]
    INFLUENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    INFLUENCE_FILE.write_text(
        "# Map entries by how many tracks they tagged, with the energy they assign.\n"
        "# This is the list to edit if sessions feel wrong: the entries at the top decide\n"
        "# most of the library, so an energy that is 0.5 out here moves hundreds of tracks.\n"
        f"# {tracks} tracks recomputed. Columns: tracks, share, energy, tag.\n"
        + "\n".join(lines)
        + "\n",
        encoding="utf-8",
    )
    print(f"\n{len(lines)} map entries in use, written to {INFLUENCE_FILE}")


def write_unmatched(unmatched: Counter[str]) -> None:
    lines = [f"{count:>5}  {tag}" for tag, count in unmatched.most_common()]
    UNMATCHED_FILE.parent.mkdir(parents=True, exist_ok=True)
    UNMATCHED_FILE.write_text(
        "# Tags the sources supplied that data/tag_map.yaml still has no entry for,\n"
        "# after aliases, the ignore list, and reading through compound names.\n"
        "# Count = how many tracks wanted each one. Highest first.\n"
        + "\n".join(lines)
        + "\n",
        encoding="utf-8",
    )
    print(f"{len(unmatched)} unmapped tag names written to {UNMATCHED_FILE}")


def histogram(values: list[float], *, label: str) -> None:
    if not values:
        print(f"{label}: nothing to show")
        return
    print(f"\n{label}  (n={len(values)}, mean {statistics.fmean(values):.2f})")
    for low, high in BANDS:
        count = sum(1 for value in values if low <= value < high)
        bar = "#" * round(40 * count / len(values))
        share = count / len(values)
        print(f"  {low:>3.1f}-{high if high <= 5 else 5.0:<4.1f}{count:>5}  {share:>5.0%}  {bar}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="store the new values")
    args = parser.parse_args()

    tag_map = load_tag_map()
    print(f"map: {len(tag_map.entries)} tags, {len(tag_map.aliases)} aliases, "
          f"{len(tag_map.ignored)} ignored")

    with SessionLocal() as db:
        rows = db.scalars(select(TrackTag)).all()
        before_energy: list[float] = []
        after_energy: list[float] = []
        before_confidence: list[float] = []
        after_confidence: list[float] = []
        rescued = 0
        lost = 0
        moved = 0
        skipped_manual = 0
        no_raw = 0
        influence: Counter[str] = Counter()
        unmatched: Counter[str] = Counter()

        for row in rows:
            if row.source == SOURCE_MANUAL:
                skipped_manual += 1
                continue
            if not row.raw_tags:
                # Either the source found nothing at all, or it predates raw_tags. Both
                # need a re-fetch, not a re-compute, so leave them exactly as they are.
                no_raw += 1
                continue

            tagging = compute(row.raw_tags, tag_map)
            influence.update(tagging.matched)
            unmatched.update(tagging.unmatched)
            was_known = row.source != SOURCE_UNKNOWN
            before_energy.append(row.energy)
            before_confidence.append(row.confidence)
            after_energy.append(tagging.energy)
            after_confidence.append(tagging.confidence)

            if tagging.is_known and not was_known:
                rescued += 1
            elif was_known and not tagging.is_known:
                lost += 1
            if abs(tagging.energy - row.energy) >= 0.05:
                moved += 1

            if args.write:
                row.energy = tagging.energy
                row.affinities = dict(tagging.affinities)
                row.confidence = tagging.confidence
                row.source = SOURCE_EXTERNAL if tagging.is_known else SOURCE_UNKNOWN
        if args.write:
            db.commit()

    print(f"\nrows {len(rows)}  recomputed {len(after_energy)}  "
          f"left alone: manual {skipped_manual}, no stored tags {no_raw}")
    print(f"energy moved by 0.05 or more: {moved}")
    print(f"unknown -> tagged: {rescued}    tagged -> unknown: {lost}")

    histogram(before_energy, label="energy before")
    histogram(after_energy, label="energy after")
    if before_confidence:
        print(
            f"\nconfidence  before mean {statistics.fmean(before_confidence):.2f} "
            f"median {statistics.median(before_confidence):.2f}"
            f"   ->   after mean {statistics.fmean(after_confidence):.2f} "
            f"median {statistics.median(after_confidence):.2f}"
        )
    if after_energy:
        write_influence(influence, tag_map, tracks=len(after_energy))
        write_unmatched(unmatched)
    if not args.write:
        print("\nNo tag rows were changed. Re-run with --write to keep this.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
