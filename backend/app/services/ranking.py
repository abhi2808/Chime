"""Ranking and running order (SPEC section 5).

Two steps, deliberately separate:

1. **Score** every candidate against the target profile. One number per track, with the
   per-component breakdown kept so "why this mix" and History can explain themselves.
2. **Shape** the running order to the profile's energy curve, keeping quality high but
   never putting three tracks from one artist in a row.

Scoring cannot be done per position, because a track's score must not depend on where it
happens to land; and ordering cannot be done by score alone, because a workout that opens
at 5 is not a workout. Hence the split.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import as_utc, utcnow
from app.models import Track, TrackTag, UserTrack
from app.services.profile_rules import TargetProfile
from app.services.tagging import ENERGY_MAX, ENERGY_MIN, NEUTRAL_ENERGY

#: SPEC section 5. These four are the whole score and must sum to 1.
WEIGHT_ENERGY = 0.50
WEIGHT_AFFINITY = 0.25
WEIGHT_BEHAVIOR = 0.15
WEIGHT_FRESHNESS = 0.10

#: What a component scores when we know nothing either way.
NEUTRAL = 0.5

#: Widest possible energy gap, used to turn a distance into a 0-1 fit.
ENERGY_SPAN = ENERGY_MAX - ENERGY_MIN

#: Behaviour: a completion is worth 1, keeping a track 2, a fast skip costs 2. Divided by
#: this to land inside 0-1, so roughly four completions reach the top of the range.
BEHAVIOR_SCALE = 8.0
#: Days after which behaviour counts half as much. Taste moves.
BEHAVIOR_HALF_LIFE_DAYS = 60.0

#: A track played within this many days is not fresh.
FRESHNESS_WINDOW_DAYS = 14.0

#: How many tracks in a row may come from one artist (SPEC section 5).
MAX_ARTIST_RUN = 2

#: Ordering: how hard to chase the curve against how hard to chase score.
ORDER_ENERGY_WEIGHT = 1.0
ORDER_SCORE_WEIGHT = 2.0
#: Candidates considered per slot. A wider pool follows the curve better and dips further
#: down the score list.
POOL_FACTOR = 4


@dataclass(frozen=True, slots=True)
class Candidate:
    """One track, with everything ranking needs and nothing it does not."""

    track_id: int
    spotify_track_id: str
    name: str
    artist_names: tuple[str, ...]
    duration_ms: int = 0
    #: From ``track_tags``, or the neutral assumption when untagged.
    energy: float = NEUTRAL_ENERGY
    confidence: float = 0.0
    affinities: Mapping[str, float] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    #: From ``user_tracks``.
    energy_override: float | None = None
    completes: int = 0
    fast_skips: int = 0
    kept_count: int = 0
    last_played_at: datetime | None = None

    @property
    def artist(self) -> str | None:
        return self.artist_names[0] if self.artist_names else None

    @property
    def effective_energy(self) -> float:
        """A manual override is the truth (SPEC section 5, step 4)."""
        return self.energy if self.energy_override is None else self.energy_override

    @property
    def effective_confidence(self) -> float:
        return 1.0 if self.energy_override is not None else self.confidence


@dataclass(frozen=True, slots=True)
class Scored:
    candidate: Candidate
    score: float
    breakdown: dict[str, float | list[str] | None]


@dataclass(frozen=True, slots=True)
class Ranked:
    position: int
    candidate: Candidate
    score: float
    #: Target energy at this position, so a dev page can show curve against reality.
    target: float
    breakdown: dict[str, float | list[str] | None]


def candidates_for(
    db: Session, user_id: int, *, sources: Sequence[str] = ("liked",), limit: int | None = None
) -> list[Candidate]:
    """Load the pool in one query. Untagged tracks are included, not excluded.

    A library that is only half tagged still has to produce a session, so an untagged
    track competes at neutral energy and low confidence rather than being dropped.
    """
    statement = (
        select(Track, TrackTag, UserTrack)
        .join(UserTrack, UserTrack.track_id == Track.id)
        .outerjoin(TrackTag, TrackTag.track_id == Track.id)
        .where(UserTrack.user_id == user_id, UserTrack.source.in_(tuple(sources)))
    )
    if limit is not None:
        statement = statement.limit(limit)

    pool: list[Candidate] = []
    for track, tag, user_track in db.execute(statement).all():
        pool.append(
            Candidate(
                track_id=track.id,
                spotify_track_id=track.spotify_track_id,
                name=track.name,
                artist_names=tuple(track.artist_names or ()),
                duration_ms=track.duration_ms,
                energy=tag.energy if tag else NEUTRAL_ENERGY,
                confidence=tag.confidence if tag else 0.0,
                affinities=dict(tag.affinities or {}) if tag else {},
                tags=tuple(name for name, _ in (tag.raw_tags or [])) if tag else (),
                energy_override=user_track.energy_override,
                completes=user_track.completes,
                fast_skips=user_track.fast_skips,
                kept_count=user_track.kept_count,
                last_played_at=user_track.last_played_at,
            )
        )
    return pool


def energy_fit(candidate: Candidate, profile: TargetProfile) -> float:
    """1 when the track sits inside the session's energy band, falling off outside it.

    Blended towards neutral by the tag's confidence: a track we have not managed to tag
    should neither win nor lose on an energy we effectively guessed.
    """
    low, high = sorted((profile.start, profile.end))
    low = max(profile.floor, min(profile.ceiling, low))
    high = max(profile.floor, min(profile.ceiling, high))

    energy = candidate.effective_energy
    distance = 0.0 if low <= energy <= high else min(abs(energy - low), abs(energy - high))
    fit = max(0.0, 1.0 - distance / ENERGY_SPAN)

    confidence = candidate.effective_confidence
    return fit * confidence + NEUTRAL * (1 - confidence)


def affinity_fit(candidate: Candidate, profile: TargetProfile) -> float:
    """How well the track's affinities line up with what the session asked for."""
    wanted = {name: weight for name, weight in profile.affinities.items() if weight > 0}
    total = sum(wanted.values())
    if not total:
        return NEUTRAL
    got = sum(weight * float(candidate.affinities.get(name, 0.0)) for name, weight in wanted.items())
    return max(0.0, min(1.0, got / total))


def behavior_boost(candidate: Candidate, *, now: datetime | None = None) -> float:
    """Plain arithmetic over play counters, decayed. 0.5 means no evidence either way."""
    raw = candidate.completes + 2 * candidate.kept_count - 2 * candidate.fast_skips
    if raw == 0:
        return NEUTRAL
    decay = _decay(candidate.last_played_at, BEHAVIOR_HALF_LIFE_DAYS, now=now)
    return max(0.0, min(1.0, NEUTRAL + raw * decay / BEHAVIOR_SCALE))


def freshness(
    candidate: Candidate,
    *,
    recent_track_ids: Iterable[int] = (),
    now: datetime | None = None,
) -> float:
    """1 for something we have not reached for lately, 0 for something we just played.

    ``recent_track_ids`` is how Phase 4 will pass in the last few sessions; until
    ``session_tracks`` exists, the last played timestamp is the only record there is.
    """
    if candidate.track_id in set(recent_track_ids):
        return 0.0
    played = as_utc(candidate.last_played_at)
    if played is None:
        return 1.0
    days = ((now or utcnow()) - played).total_seconds() / 86400
    return max(0.0, min(1.0, days / FRESHNESS_WINDOW_DAYS))


def _decay(moment: datetime | None, half_life_days: float, *, now: datetime | None = None) -> float:
    played = as_utc(moment)
    if played is None:
        return 1.0
    days = max(0.0, ((now or utcnow()) - played).total_seconds() / 86400)
    return 0.5 ** (days / half_life_days)


def score(
    candidate: Candidate,
    profile: TargetProfile,
    *,
    recent_track_ids: Iterable[int] = (),
    now: datetime | None = None,
) -> Scored:
    recent = set(recent_track_ids)
    components = {
        "energy_fit": round(energy_fit(candidate, profile), 4),
        "affinity": round(affinity_fit(candidate, profile), 4),
        "behavior": round(behavior_boost(candidate, now=now), 4),
        "freshness": round(freshness(candidate, recent_track_ids=recent, now=now), 4),
    }
    total = (
        WEIGHT_ENERGY * components["energy_fit"]
        + WEIGHT_AFFINITY * components["affinity"]
        + WEIGHT_BEHAVIOR * components["behavior"]
        + WEIGHT_FRESHNESS * components["freshness"]
    )
    breakdown: dict[str, float | list[str] | None] = dict(components)
    breakdown["score"] = round(total, 4)
    breakdown["energy"] = candidate.effective_energy
    breakdown["confidence"] = candidate.effective_confidence
    breakdown["tags"] = list(candidate.tags[:6])
    return Scored(candidate=candidate, score=round(total, 4), breakdown=breakdown)


def rank(
    candidates: Iterable[Candidate],
    profile: TargetProfile,
    *,
    count: int = 25,
    recent_track_ids: Iterable[int] = (),
    now: datetime | None = None,
    curve: Sequence[float] | None = None,
) -> list[Ranked]:
    """Score, then lay the best of them along the energy curve.

    ``curve`` overrides the profile's own sampling, which is what a mid-session adaptation
    needs: it is filling the *tail* of a session, and a fresh ``profile.curve(count)`` would
    start the ramp again from the beginning — dropping a workout back to its opening energy
    half an hour in (:mod:`app.services.adaptation`).
    """
    recent = set(recent_track_ids)
    scored = sorted(
        (score(candidate, profile, recent_track_ids=recent, now=now) for candidate in candidates),
        key=lambda item: -item.score,
    )
    if count <= 0 or not scored:
        return []

    pool = scored[: max(count * POOL_FACTOR, count)]
    positions = min(count, len(pool))
    shape = list(curve)[:positions] if curve is not None else profile.curve(positions)
    return _shape(pool, shape)


def _shape(pool: Sequence[Scored], curve: Sequence[float]) -> list[Ranked]:
    """Greedy: at each position take the best compromise between curve and score.

    Greedy rather than optimal on purpose. An exact assignment would be slower, harder to
    explain, and no better musically — and every candidate here already scored well.
    """
    remaining = list(pool)
    order: list[Ranked] = []
    run_artist: str | None = None
    run_length = 0

    for position, target in enumerate(curve):
        index = _pick(remaining, target, run_artist, run_length)
        if index is None:
            # Everything left is by the artist we have just played twice: a library that
            # is mostly one artist. Take the best fit anyway — a short playlist would be
            # the worse answer to a request for a session.
            index = _pick(remaining, target, None, 0)
            assert index is not None  # remaining is non-empty inside this loop
        chosen = remaining.pop(index)

        artist = chosen.candidate.artist
        run_length = run_length + 1 if artist is not None and artist == run_artist else 1
        run_artist = artist

        order.append(
            Ranked(
                position=position,
                candidate=chosen.candidate,
                score=chosen.score,
                target=target,
                breakdown={**chosen.breakdown, "target": target},
            )
        )
        if not remaining:
            break
    return order


def _pick(
    remaining: Sequence[Scored], target: float, run_artist: str | None, run_length: int
) -> int | None:
    """Index of the best compromise between the curve and the score, or ``None``.

    ``None`` means the artist rule ruled everything out. Passing ``run_artist=None``
    asks the same question with the rule lifted.
    """
    best: tuple[float, int] | None = None
    for index, item in enumerate(remaining):
        artist = item.candidate.artist
        if artist is not None and artist == run_artist and run_length >= MAX_ARTIST_RUN:
            continue
        cost = (
            abs(item.candidate.effective_energy - target) * ORDER_ENERGY_WEIGHT
            - item.score * ORDER_SCORE_WEIGHT
        )
        if best is None or cost < best[0]:
            best = (cost, index)
    return None if best is None else best[1]
