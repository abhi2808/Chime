"""Scoring and running order (SPEC section 5).

Most of this is pure, so the tests are the specification. The one database test covers
the join that feeds it, including the case the engine has to survive on day one: a
library that is not tagged yet.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.models import Track, TrackTag, User, UserTrack
from app.services.body_state import BodyState, DayPart, Readiness
from app.services.profile_rules import build_profile
from app.services.ranking import (
    MAX_ARTIST_RUN,
    WEIGHT_AFFINITY,
    WEIGHT_BEHAVIOR,
    WEIGHT_ENERGY,
    WEIGHT_FRESHNESS,
    Candidate,
    affinity_fit,
    behavior_boost,
    candidates_for,
    energy_fit,
    freshness,
    rank,
    score,
)

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def body(
    *,
    day_part: DayPart = "afternoon",
    readiness: Readiness | None = None,
    since_workout: int | None = None,
) -> BodyState:
    return BodyState(
        day_part=day_part,
        connected=readiness is not None,
        has_data=readiness is not None,
        readiness=readiness,
        minutes_since_last_workout=since_workout,
    )


def candidate(
    track_id: int = 1,
    *,
    energy: float = 3.0,
    confidence: float = 1.0,
    artist: str = "One",
    **kwargs: object,
) -> Candidate:
    return Candidate(
        track_id=track_id,
        spotify_track_id=f"s{track_id}",
        name=f"track {track_id}",
        artist_names=(artist,),
        energy=energy,
        confidence=confidence,
        **kwargs,  # type: ignore[arg-type]
    )


class TestEnergyFit:
    def test_a_track_inside_the_band_is_a_perfect_fit(self) -> None:
        profile = build_profile(body(), mood="steady", session_type="workout")  # 3 -> 5
        assert energy_fit(candidate(energy=4.0), profile) == 1.0

    def test_the_fit_falls_off_outside_the_band(self) -> None:
        profile = build_profile(body(), mood="steady", session_type="workout")
        near = energy_fit(candidate(energy=2.5), profile)
        far = energy_fit(candidate(energy=1.0), profile)
        assert 1.0 > near > far

    def test_an_untagged_track_is_neither_rewarded_nor_punished(self) -> None:
        """Confidence 0 means the energy was a guess, so it must not decide anything."""
        profile = build_profile(body(), mood="steady", session_type="wind_down")
        assert energy_fit(candidate(energy=3.0, confidence=0.0), profile) == 0.5

    def test_confidence_blends_between_the_two(self) -> None:
        profile = build_profile(body(), mood="steady", session_type="workout")
        half = energy_fit(candidate(energy=4.0, confidence=0.5), profile)
        assert 0.5 < half < 1.0

    def test_a_manual_override_is_believed_completely(self) -> None:
        profile = build_profile(body(), mood="steady", session_type="wind_down")  # 2 -> 1
        guessed = candidate(energy=5.0, confidence=0.0)
        overridden = candidate(energy=5.0, confidence=0.0, energy_override=1.0)
        assert energy_fit(guessed, profile) == 0.5
        assert energy_fit(overridden, profile) == 1.0

    def test_a_capped_session_does_not_call_a_loud_track_a_good_fit(self) -> None:
        """Low recovery caps the ceiling, and the fit has to respect the cap."""
        profile = build_profile(body(readiness="low"), mood="fired_up", session_type="wake_up")
        assert profile.ceiling == 4.0
        assert energy_fit(candidate(energy=5.0), profile) < 1.0


class TestAffinityFit:
    def test_a_track_the_session_wants_scores_top_marks(self) -> None:
        profile = build_profile(body(), mood="steady", session_type="wind_down")
        perfect = candidate(affinities={"wind_down": 1.0, "calm": 1.0})
        assert affinity_fit(perfect, profile) == pytest.approx(1.0)

    def test_a_track_with_no_affinities_scores_nothing(self) -> None:
        profile = build_profile(body(), mood="steady", session_type="wind_down")
        assert affinity_fit(candidate(), profile) == 0.0

    def test_the_wrong_affinities_do_not_count(self) -> None:
        profile = build_profile(body(), mood="steady", session_type="wind_down")
        assert affinity_fit(candidate(affinities={"workout": 1.0}), profile) == 0.0

    def test_partial_overlap_scores_in_between(self) -> None:
        profile = build_profile(body(), mood="steady", session_type="focus")
        partial = candidate(affinities={"focus": 1.0})
        full = candidate(affinities={"focus": 1.0, "calm": 1.0})
        assert 0.0 < affinity_fit(partial, profile) < affinity_fit(full, profile)


class TestBehaviorBoost:
    def test_no_history_is_neutral(self) -> None:
        assert behavior_boost(candidate(), now=NOW) == 0.5

    def test_completions_help_and_fast_skips_hurt(self) -> None:
        liked = candidate(completes=4, last_played_at=NOW)
        skipped = candidate(fast_skips=4, last_played_at=NOW)
        assert behavior_boost(liked, now=NOW) > 0.5
        assert behavior_boost(skipped, now=NOW) < 0.5

    def test_keeping_a_track_counts_for_more_than_finishing_it(self) -> None:
        kept = candidate(kept_count=1, last_played_at=NOW)
        completed = candidate(completes=1, last_played_at=NOW)
        assert behavior_boost(kept, now=NOW) > behavior_boost(completed, now=NOW)

    def test_old_behaviour_counts_for_less(self) -> None:
        """Taste moves, so a run of plays last winter should not still be steering."""
        recent = candidate(completes=4, last_played_at=NOW - timedelta(days=1))
        stale = candidate(completes=4, last_played_at=NOW - timedelta(days=365))
        assert behavior_boost(recent, now=NOW) > behavior_boost(stale, now=NOW) > 0.5

    def test_it_stays_inside_zero_to_one(self) -> None:
        loved = candidate(completes=500, kept_count=100, last_played_at=NOW)
        hated = candidate(fast_skips=500, last_played_at=NOW)
        assert behavior_boost(loved, now=NOW) == 1.0
        assert behavior_boost(hated, now=NOW) == 0.0


class TestFreshness:
    def test_something_never_played_is_as_fresh_as_it_gets(self) -> None:
        assert freshness(candidate(), now=NOW) == 1.0

    def test_something_just_played_is_not_fresh(self) -> None:
        assert freshness(candidate(last_played_at=NOW), now=NOW) == 0.0

    def test_freshness_returns_over_time(self) -> None:
        week = freshness(candidate(last_played_at=NOW - timedelta(days=7)), now=NOW)
        month = freshness(candidate(last_played_at=NOW - timedelta(days=30)), now=NOW)
        assert 0.0 < week < 1.0
        assert month == 1.0

    def test_a_track_from_a_recent_session_is_stale_whatever_the_clock_says(self) -> None:
        """Phase 4 passes the last few sessions in; membership beats the timestamp."""
        assert freshness(candidate(track_id=7), recent_track_ids=[7], now=NOW) == 0.0
        assert freshness(candidate(track_id=7), recent_track_ids=[8], now=NOW) == 1.0


class TestScore:
    def test_the_weights_are_the_whole_score(self) -> None:
        assert WEIGHT_ENERGY + WEIGHT_AFFINITY + WEIGHT_BEHAVIOR + WEIGHT_FRESHNESS == 1.0

    def test_the_breakdown_adds_up_to_the_score(self) -> None:
        profile = build_profile(body(), mood="steady", session_type="focus")
        scored = score(candidate(energy=2.5, affinities={"focus": 0.8}), profile, now=NOW)
        expected = (
            WEIGHT_ENERGY * scored.breakdown["energy_fit"]
            + WEIGHT_AFFINITY * scored.breakdown["affinity"]
            + WEIGHT_BEHAVIOR * scored.breakdown["behavior"]
            + WEIGHT_FRESHNESS * scored.breakdown["freshness"]
        )
        assert scored.score == pytest.approx(expected, abs=1e-4)
        assert scored.breakdown["score"] == scored.score

    def test_the_breakdown_explains_itself(self) -> None:
        """History and "why this mix" read this dict, so it has to carry the reasons."""
        profile = build_profile(body(), mood="steady", session_type="focus")
        scored = score(candidate(tags=("ambient", "piano")), profile, now=NOW)
        assert set(scored.breakdown) >= {
            "energy_fit",
            "affinity",
            "behavior",
            "freshness",
            "score",
            "energy",
            "confidence",
            "tags",
        }
        assert scored.breakdown["tags"] == ["ambient", "piano"]

    def test_a_score_is_always_a_fraction(self) -> None:
        profile = build_profile(body(), mood="steady", session_type="workout")
        best = candidate(energy=5.0, affinities={"workout": 1.0}, completes=9, kept_count=3)
        worst = candidate(energy=1.0, fast_skips=9, last_played_at=NOW)
        for item in (best, worst):
            assert 0.0 <= score(item, profile, now=NOW).score <= 1.0


class TestRank:
    def pool(self, *, per_energy: int = 3) -> list[Candidate]:
        """A spread-out library: several tracks at each energy, several artists."""
        pool: list[Candidate] = []
        track_id = 0
        for energy in (1.0, 2.0, 3.0, 4.0, 5.0):
            for index in range(per_energy):
                track_id += 1
                pool.append(
                    candidate(
                        track_id,
                        energy=energy,
                        artist=f"artist {index}",
                        affinities={name: 0.5 for name in ("calm", "focus", "workout")},
                    )
                )
        return pool

    def test_it_returns_the_number_of_tracks_asked_for(self) -> None:
        profile = build_profile(body(), mood="steady", session_type="focus")
        assert len(rank(self.pool(), profile, count=8, now=NOW)) == 8

    def test_it_never_returns_more_than_the_library_has(self) -> None:
        profile = build_profile(body(), mood="steady", session_type="focus")
        assert len(rank(self.pool(per_energy=1), profile, count=25, now=NOW)) == 5

    def test_nothing_in_nothing_out(self) -> None:
        profile = build_profile(body(), mood="steady", session_type="focus")
        assert rank([], profile, count=10, now=NOW) == []
        assert rank(self.pool(), profile, count=0, now=NOW) == []

    def test_a_workout_climbs(self) -> None:
        profile = build_profile(body(), mood="steady", session_type="workout")
        order = rank(self.pool(per_energy=6), profile, count=12, now=NOW)
        energies = [item.candidate.effective_energy for item in order]
        assert energies[0] < max(energies)
        assert sum(energies[6:]) > sum(energies[:6])

    def test_a_wind_down_descends(self) -> None:
        profile = build_profile(body(), mood="steady", session_type="wind_down")
        order = rank(self.pool(per_energy=6), profile, count=10, now=NOW)
        energies = [item.candidate.effective_energy for item in order]
        assert energies[0] >= energies[-1]
        assert sum(energies[5:]) <= sum(energies[:5])

    def test_positions_and_targets_are_recorded(self) -> None:
        profile = build_profile(body(), mood="steady", session_type="wake_up")
        order = rank(self.pool(per_energy=6), profile, count=6, now=NOW)
        assert [item.position for item in order] == list(range(6))
        assert [item.target for item in order] == profile.curve(6)
        assert all(item.breakdown["target"] == item.target for item in order)

    def test_no_more_than_two_tracks_in_a_row_from_one_artist(self) -> None:
        """One artist scores best on everything here, so only the rule breaks the run."""
        profile = build_profile(body(), mood="steady", session_type="focus")
        pool = [
            candidate(index, energy=3.0, artist="Repeat", completes=5) for index in range(10)
        ] + [candidate(20 + index, energy=3.0, artist=f"Other {index}") for index in range(10)]
        order = rank(pool, profile, count=12, now=NOW)
        assert sum(1 for item in order if item.candidate.artist == "Repeat") >= 6
        run = 1
        for previous, current in zip(order, order[1:]):
            run = run + 1 if current.candidate.artist == previous.candidate.artist else 1
            assert run <= MAX_ARTIST_RUN

    def test_a_one_artist_library_still_gets_a_full_playlist(self) -> None:
        """The artist rule must not be able to cut a session short: when a library is
        one artist, a full playlist beats honouring the rule."""
        profile = build_profile(body(), mood="steady", session_type="focus")
        pool = [candidate(index, energy=3.0, artist="Only") for index in range(10)]
        assert len(rank(pool, profile, count=10, now=NOW)) == 10

    def test_a_track_is_never_used_twice(self) -> None:
        profile = build_profile(body(), mood="steady", session_type="workout")
        order = rank(self.pool(per_energy=6), profile, count=20, now=NOW)
        ids = [item.candidate.track_id for item in order]
        assert len(ids) == len(set(ids))

    def test_a_better_track_wins_a_slot_over_a_worse_one_at_the_same_energy(self) -> None:
        profile = build_profile(body(), mood="steady", session_type="focus")
        loved = candidate(1, energy=3.0, artist="A", completes=8, affinities={"focus": 1.0})
        skipped = candidate(2, energy=3.0, artist="B", fast_skips=8, last_played_at=NOW)
        order = rank([loved, skipped], profile, count=1, now=NOW)
        assert order[0].candidate.track_id == 1

    def test_recent_tracks_lose_to_equal_but_fresher_ones(self) -> None:
        profile = build_profile(body(), mood="steady", session_type="focus")
        stale = candidate(1, energy=3.0, artist="A")
        fresh = candidate(2, energy=3.0, artist="B")
        order = rank([stale, fresh], profile, count=1, recent_track_ids=[1], now=NOW)
        assert order[0].candidate.track_id == 2

    def test_an_untagged_library_still_produces_a_session(self) -> None:
        """Day one: nothing tagged. A short playlist is a bug, silence is worse."""
        profile = build_profile(body(), mood="steady", session_type="wind_down")
        pool = [
            candidate(index, energy=3.0, confidence=0.0, artist=f"artist {index % 4}")
            for index in range(15)
        ]
        order = rank(pool, profile, count=12, now=NOW)
        assert len(order) == 12
        assert all(item.score > 0 for item in order)


def test_candidates_for_reads_tags_and_history_in_one_pass(db: Session, user: User) -> None:
    tagged = Track(spotify_track_id="s1", name="one", artist_ids=["a1"], artist_names=["A"])
    untagged = Track(spotify_track_id="s2", name="two", artist_ids=["a2"], artist_names=["B"])
    db.add_all([tagged, untagged])
    db.flush()
    db.add_all(
        [
            TrackTag(
                track_id=tagged.id,
                energy=4.2,
                affinities={"workout": 0.8},
                confidence=0.6,
                raw_tags=[["techno", 1.0]],
            ),
            UserTrack(
                user_id=user.id,
                track_id=tagged.id,
                source="liked",
                completes=3,
                energy_override=2.0,
            ),
            UserTrack(user_id=user.id, track_id=untagged.id, source="liked"),
        ]
    )
    db.commit()

    by_id = {item.track_id: item for item in candidates_for(db, user.id)}
    assert len(by_id) == 2

    first = by_id[tagged.id]
    assert first.energy == 4.2
    assert first.confidence == 0.6
    assert first.affinities == {"workout": 0.8}
    assert first.tags == ("techno",)
    assert first.completes == 3
    assert first.effective_energy == 2.0  # the override wins

    second = by_id[untagged.id]
    assert second.energy == 3.0
    assert second.confidence == 0.0
    assert second.tags == ()


def test_candidates_for_keeps_users_apart(db: Session, user: User) -> None:
    other = User(spotify_account_id="acct-else", spotify_user_id="someone-else")
    db.add(other)
    track = Track(spotify_track_id="s1", name="one", artist_ids=["a1"], artist_names=["A"])
    db.add(track)
    db.flush()
    db.add(UserTrack(user_id=other.id, track_id=track.id, source="liked"))
    db.commit()

    assert candidates_for(db, user.id) == []
    assert len(candidates_for(db, other.id)) == 1
