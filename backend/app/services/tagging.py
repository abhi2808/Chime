"""Deterministic track tagging (SPEC section 5).

Spotify exposes no audio features and its ``genres`` field is deprecated (and, on our
app, absent), so a track's energy comes from tags run through ``data/tag_map.yaml``.

Nothing here talks to a network or an LLM: it is a pure mapping from
``[(tag, weight), ...]`` to an energy, a set of affinities, and a confidence. Tag
*supply* is a :class:`TagSource`; tag *meaning* is the map. That split is what lets the
engine work with MusicBrainz, with Spotify genres, or with nothing at all.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import yaml

from app.core.config import settings

#: The affinity dimensions a target profile can ask for (SPEC section 3).
AFFINITIES = ("calm", "focus", "workout", "wind_down", "wake_up")

ENERGY_MIN = 1.0
ENERGY_MAX = 5.0
#: What an untagged track is assumed to be: dead centre, and trusted least.
NEUTRAL_ENERGY = 3.0

#: Matched weight at which we stop gaining confidence from sheer quantity of tags. Source
#: weights are relative to the entity's strongest tag, so one well-agreed tag the map
#: understands in full is enough to be confident.
CONFIDENCE_SATURATION = 1.0

#: What each tag counts for, by its rank in the source's own ordering, in pairs.
#:
#: A flat average is what flattens the library: eight tags averaged towards 3 turn every
#: track into a middling one, and then no session can climb or descend. An entity's first
#: two tags are what it *is*; the rest are increasingly qualifiers, moods and stray votes.
#: Ranks beyond this table are dropped rather than given a tiny weight — they would only
#: pull the average back to the middle, which is the thing being fixed.
RANK_WEIGHTS = (1.0, 1.0, 0.55, 0.55, 0.3, 0.3, 0.15, 0.15)

#: How much of a tag's meaning survives being read out of a longer phrase containing it.
#: "melodic death metal" is death metal; "german hip hop" is hip hop. Good enough to use,
#: not good enough to trust like an entry written by hand.
INHERITED_FACTOR = 0.75

_PUNCTUATION = re.compile(r"[^a-z0-9&+]+")


def normalize(tag: str) -> str:
    """Fold a tag to its lookup key.

    Tag vocabularies disagree about case, hyphens and ampersands ("Hip-Hop", "hip hop",
    "R&B", "rhythm & blues"), and none of that is a musical difference.
    """
    return _PUNCTUATION.sub(" ", tag.strip().lower()).strip()


@dataclass(frozen=True, slots=True)
class TagEntry:
    """One row of the map: what a tag means."""

    energy: float
    #: How much this entry counts in an average. Umbrella tags are deliberately light.
    weight: float = 1.0
    affinities: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TagMap:
    entries: Mapping[str, TagEntry]
    #: Alternative spelling -> canonical key, applied after :func:`normalize`.
    aliases: Mapping[str, str] = field(default_factory=dict)
    #: Tags that are real but say nothing about energy: nationalities, roles, eras,
    #: formats. Skipped entirely rather than counted as tags we failed to understand.
    ignored: frozenset[str] = field(default_factory=frozenset)

    def canonical(self, tag: str) -> str:
        key = normalize(tag)
        return self.aliases.get(key, key)

    def is_ignored(self, tag: str) -> bool:
        return self.canonical(tag) in self.ignored

    def lookup(self, tag: str) -> tuple[str, TagEntry] | None:
        key = self.canonical(tag)
        entry = self.entries.get(key)
        return None if entry is None else (key, entry)

    def resolve(self, tag: str) -> tuple[str, TagEntry, float] | None:
        """Find a tag's meaning, reading through a compound name if it has to.

        Tag vocabularies are open, so the long tail is mostly qualified versions of things
        the map already knows: a hundred "<adjective> <genre>" and "<genre> <subgenre>"
        spellings that no hand-written map will ever enumerate. Falling back to the longest
        known phrase inside the tag turns most of that tail from "no evidence" into
        slightly-discounted evidence, which is the cheapest coverage available.

        The rightmost of two equally long matches wins: an English genre name carries its
        head noun at the end and its qualifiers at the front.
        """
        key = self.canonical(tag)
        entry = self.entries.get(key)
        if entry is not None:
            return key, entry, 1.0

        words = key.split()
        for size in range(len(words) - 1, 0, -1):
            for start in range(len(words) - size, -1, -1):
                phrase = " ".join(words[start : start + size])
                candidate = self.aliases.get(phrase, phrase)
                found = self.entries.get(candidate)
                if found is not None:
                    return candidate, found, INHERITED_FACTOR
        return None

    @classmethod
    def from_data(cls, data: Mapping[str, Any]) -> TagMap:
        """Validate a parsed map. Raises :class:`TagMapError` on anything unusable."""
        raw_entries = data.get("tags") or {}
        if not isinstance(raw_entries, Mapping) or not raw_entries:
            raise TagMapError("tag map has no 'tags' section")

        entries: dict[str, TagEntry] = {}
        for name, value in raw_entries.items():
            key = normalize(str(name))
            if not isinstance(value, Mapping):
                raise TagMapError(f"tag {name!r} is not a mapping")
            unknown = set(value) - {"energy", "weight", *AFFINITIES}
            if unknown:
                raise TagMapError(f"tag {name!r} has unknown keys: {sorted(unknown)}")
            energy = _number(value, "energy", name, low=ENERGY_MIN, high=ENERGY_MAX)
            if energy is None:
                raise TagMapError(f"tag {name!r} has no energy")
            weight = _number(value, "weight", name, low=0.0, high=1.0, default=1.0)
            affinities = {
                affinity: _number(value, affinity, name, low=0.0, high=1.0) or 0.0
                for affinity in AFFINITIES
                if affinity in value
            }
            entries[key] = TagEntry(energy=energy, weight=weight or 0.0, affinities=affinities)

        raw_aliases = data.get("aliases") or {}
        if not isinstance(raw_aliases, Mapping):
            raise TagMapError("'aliases' is not a mapping")
        aliases: dict[str, str] = {}
        for alias, target in raw_aliases.items():
            key = normalize(str(alias))
            canonical = normalize(str(target))
            if canonical not in entries:
                raise TagMapError(f"alias {alias!r} points at unknown tag {target!r}")
            aliases[key] = canonical

        raw_ignored = data.get("ignore") or []
        if isinstance(raw_ignored, (str, Mapping)) or not isinstance(raw_ignored, Sequence):
            raise TagMapError("'ignore' must be a list of tags")
        ignored: set[str] = set()
        for name in raw_ignored:
            key = normalize(str(name))
            if key in entries:
                raise TagMapError(f"tag {name!r} is both defined and ignored")
            ignored.add(key)

        return cls(entries=entries, aliases=aliases, ignored=frozenset(ignored))

    @classmethod
    def load(cls, path: Path | str | None = None) -> TagMap:
        target = Path(path) if path is not None else settings.tag_map_file
        try:
            text = target.read_text(encoding="utf-8")
        except OSError as exc:
            raise TagMapError(f"cannot read tag map at {target}") from exc
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise TagMapError(f"tag map at {target} is not valid YAML") from exc
        if not isinstance(data, Mapping):
            raise TagMapError(f"tag map at {target} is not a mapping")
        return cls.from_data(data)


class TagMapError(RuntimeError):
    """The map is missing or malformed. A startup-time problem, not a per-track one."""


def _number(
    value: Mapping[str, Any],
    key: str,
    name: object,
    *,
    low: float,
    high: float,
    default: float | None = None,
) -> float | None:
    raw = value.get(key, default)
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise TagMapError(f"tag {name!r}: {key} must be a number, got {raw!r}")
    number = float(raw)
    if not low <= number <= high:
        raise TagMapError(f"tag {name!r}: {key} must be between {low} and {high}, got {number}")
    return number


@lru_cache(maxsize=1)
def _cached_map(path: str) -> TagMap:
    return TagMap.load(path)


def load_tag_map(path: Path | str | None = None) -> TagMap:
    """Process-wide cached map. Call :func:`reset_tag_map` after editing the file."""
    target = Path(path) if path is not None else settings.tag_map_file
    return _cached_map(str(target))


def reset_tag_map() -> None:
    _cached_map.cache_clear()


@dataclass(frozen=True, slots=True)
class Tagging:
    """The verdict for one track, ready to store in ``track_tags``."""

    energy: float
    affinities: dict[str, float]
    #: 0-1: how much of the supplied tag weight the map understood, and how much of it
    #: there was. Ranking blends towards neutral when this is low.
    confidence: float
    #: Canonical map keys that matched, strongest first. Feeds "why this mix".
    matched: tuple[str, ...] = ()
    #: Normalized tags the map has no entry for. Collected so the map can grow.
    unmatched: tuple[str, ...] = ()
    #: Every tag the source supplied, canonicalised and deduped, with its source weight.
    #: Stored on the row so an edited map can be re-applied without re-fetching.
    raw: tuple[tuple[str, float], ...] = ()

    @property
    def is_known(self) -> bool:
        return bool(self.matched)


def compute(
    tags: Iterable[tuple[str, float]] | Iterable[Sequence[Any]],
    tag_map: TagMap | None = None,
) -> Tagging:
    """Average the tags a source gave us into one energy and affinity set.

    ``tags`` is ``(tag, weight)`` pairs where weight is the source's own confidence in
    that tag, 0-1 (MusicBrainz vote counts, normalized by the caller), **strongest
    first** — the order is data, because rank decides how much each tag counts
    (:data:`RANK_WEIGHTS`). An empty or wholly unrecognised list is not an error: it
    yields neutral energy at confidence 0, which is exactly how SPEC says to treat an
    unknown track.
    """
    tag_map = tag_map or load_tag_map()

    matched: list[tuple[str, float, TagEntry]] = []
    unmatched: list[str] = []
    raw: list[tuple[str, float]] = []
    seen: set[str] = set()
    unmatched_weight = 0.0
    rank = 0

    for tag, weight in ((pair[0], float(pair[1])) for pair in tags):
        weight = max(0.0, min(1.0, weight))
        key = tag_map.canonical(tag)
        if not key or key in seen:
            continue  # two spellings of the same tag must not double-count
        seen.add(key)
        raw.append((key, round(weight, 3)))
        if key in tag_map.ignored:
            # "british", "composer", "1990s": true, and no evidence either way. Counting
            # these as unmatched would read a well-tagged artist as a badly tagged one.
            # They do not consume a rank either, or noise near the top of the list would
            # push real tags down into the cheap seats.
            continue
        if rank >= len(RANK_WEIGHTS):
            # Past the table the tail says nothing the list has not already said. Still
            # recorded above, though: raw_tags is the archive a future map re-reads.
            continue
        weight *= RANK_WEIGHTS[rank]
        rank += 1

        resolved = tag_map.resolve(key)
        if resolved is None:
            unmatched.append(key)
            unmatched_weight += weight
            continue
        name, entry, factor = resolved
        matched.append((name, weight * entry.weight * factor, entry))

    total = sum(weight for _, weight, _ in matched)
    if total <= 0:
        # Either nothing matched, or everything that matched carried zero weight.
        return Tagging(
            energy=NEUTRAL_ENERGY,
            affinities={},
            confidence=0.0,
            unmatched=tuple(unmatched),
            raw=tuple(raw),
        )

    energy = sum(entry.energy * weight for _, weight, entry in matched) / total
    affinities = {
        affinity: round(
            sum(entry.affinities.get(affinity, 0.0) * weight for _, weight, entry in matched)
            / total,
            3,
        )
        for affinity in AFFINITIES
    }

    coverage = total / (total + unmatched_weight) if total + unmatched_weight else 0.0
    strength = min(1.0, total / CONFIDENCE_SATURATION)
    order = sorted(matched, key=lambda item: -item[1])

    return Tagging(
        energy=round(max(ENERGY_MIN, min(ENERGY_MAX, energy)), 3),
        affinities={name: value for name, value in affinities.items() if value > 0},
        confidence=round(coverage * strength, 3),
        # Two tags can resolve to one entry ("death metal", "melodic death metal"): both
        # votes count towards the energy, but the name is only worth saying once.
        matched=tuple(dict.fromkeys(key for key, _, _ in order)),
        unmatched=tuple(unmatched),
        raw=tuple(raw),
    )


@dataclass(frozen=True, slots=True)
class SourceTags:
    """What a :class:`TagSource` found for one track."""

    pairs: tuple[tuple[str, float], ...] = ()
    #: How it was found ("recording", "artist", "genres"). Reporting only; the ranking
    #: never reads it, but "tagged from the artist, not the song" is worth knowing.
    via: str = ""

    @property
    def found(self) -> bool:
        return bool(self.pairs)


#: A source that has nothing for a track. Not an error: see ``TagSource``.
NOTHING = SourceTags()


@runtime_checkable
class TagSource(Protocol):
    """Where tags come from.

    One method, so a source can be a network client (MusicBrainz), a local lookup
    (Spotify artist genres), or a test stub. Implementations must:

    * return ``(tag, weight)`` pairs with weight 0-1, strongest first;
    * return :data:`NOTHING` rather than raising when a track is simply not found;
    * never send anything to an AI or ML service (CLAUDE.md rule 7).
    """

    #: Stored on ``track_tags.source``; one of ``app.models.track_tag.SOURCES``.
    name: str

    async def tags_for(self, *, title: str, artist: str | None = None) -> SourceTags: ...
