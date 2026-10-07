"""Target profile rules (SPEC section 3), including intent match | shift.

Pure functions, so these tests are the specification: if a rule is not asserted here, it
is not a rule.
"""

from __future__ import annotations

import pytest

from app.services.body_state import BodyState, DayPart, Readiness
from app.services.profile_rules import (
    LOW_READINESS_CEILING,
    MOODS,
    SESSION_TYPES,
    TYPE_RULES,
    TargetProfile,
    build_profile,
    ceiling_for,
    resolve_type,
)


def body(
    *,
    day_part: DayPart = "afternoon",
    readiness: Readiness | None = None,
    since_workout: int | None = None,
) -> BodyState:
    return BodyState(
        day_part=day_part,
        connected=readiness is not None or since_workout is not None,
        has_data=readiness is not None,
        readiness=readiness,
        minutes_since_last_workout=since_workout,
    )


class TestTypeResolution:
    def test_an_explicit_type_is_respected(self) -> None:
        resolved, note = resolve_type("focus", body(day_part="morning"), "flat")
        assert resolved == "focus"
        assert note is None

    def test_an_unknown_type_is_refused(self) -> None:
        with pytest.raises(ValueError, match="Unknown session type"):
            resolve_type("party", body(), None)

    @pytest.mark.parametrize(
        ("day_part", "expected"),
        [
            ("early_morning", "wake_up"),
            ("morning", "wake_up"),
            ("afternoon", "focus"),
            ("evening", "wind_down"),
            ("late_night", "wind_down"),
        ],
    )
    def test_auto_follows_the_clock_when_nothing_else_speaks(
        self, day_part: DayPart, expected: str
    ) -> None:
        resolved, note = resolve_type("auto", body(day_part=day_part), None)
        assert resolved == expected
        assert note  # auto always explains itself

    def test_fired_up_asks_for_a_workout(self) -> None:
        resolved, _ = resolve_type("auto", body(day_part="late_night"), "fired_up")
        assert resolved == "workout"

    def test_but_not_on_a_low_recovery_day(self) -> None:
        """The app should not talk someone into a session their body is not ready for."""
        resolved, _ = resolve_type("auto", body(day_part="evening", readiness="low"), "fired_up")
        assert resolved == "wind_down"

    def test_a_workout_in_the_last_hour_cools_down(self) -> None:
        resolved, note = resolve_type("auto", body(day_part="morning", since_workout=20), None)
        assert resolved == "wind_down"
        assert "trained" in note.lower()

    def test_an_older_workout_does_not(self) -> None:
        resolved, _ = resolve_type("auto", body(day_part="morning", since_workout=180), None)
        assert resolved == "wake_up"

    def test_auto_resolves_to_a_real_type_for_every_mood_and_day_part(self) -> None:
        for mood in (*MOODS, None):
            for day_part in ("early_morning", "morning", "afternoon", "evening", "late_night"):
                resolved, _ = resolve_type("auto", body(day_part=day_part), mood)
                assert resolved in TYPE_RULES


class TestMatch:
    def test_a_workout_ramps_three_to_five(self) -> None:
        profile = build_profile(body(), mood="steady", session_type="workout")
        assert (profile.start, profile.end) == (3, 5)

    def test_focus_sits_flat_and_prefers_focus_tracks(self) -> None:
        profile = build_profile(body(), mood="steady", session_type="focus")
        assert (profile.start, profile.end) == (2, 3)
        assert profile.affinities["focus"] == 1.0

    def test_wind_down_descends(self) -> None:
        profile = build_profile(body(), mood="steady", session_type="wind_down")
        assert profile.start > profile.end

    def test_wake_up_ramps_two_to_four(self) -> None:
        profile = build_profile(body(), mood="steady", session_type="wake_up")
        assert (profile.start, profile.end) == (2, 4)

    @pytest.mark.parametrize(
        ("mood", "step"),
        [("wired", -1), ("drained", -1), ("flat", +1), ("fired_up", +1), ("steady", 0)],
    )
    def test_mood_moves_the_whole_curve(self, mood: str, step: float) -> None:
        plain = build_profile(body(), mood="steady", session_type="focus")
        moved = build_profile(body(), mood=mood, session_type="focus")
        assert moved.start == plain.start + step
        assert moved.end == plain.end + step

    def test_a_mood_never_flattens_a_session_onto_the_floor(self) -> None:
        """"Wind down + wired" is the demo, and a curve of all 1s has no shape at all:
        the move is clamped, so the descent survives."""
        profile = build_profile(body(), mood="wired", session_type="wind_down")
        assert (profile.start, profile.end) == (2, 1)
        assert len(set(profile.curve(10))) > 1

    def test_nor_squashes_one_against_the_ceiling(self) -> None:
        profile = build_profile(body(), mood="fired_up", session_type="workout")
        assert (profile.start, profile.end) == (3, 5)

    def test_a_mood_still_moves_a_curve_that_has_room(self) -> None:
        profile = build_profile(body(), mood="wired", session_type="wake_up")  # 2 -> 4
        assert (profile.start, profile.end) == (1, 3)

    def test_a_drained_workout_is_the_exception(self) -> None:
        """SPEC: drained lowers the target, except on a workout."""
        profile = build_profile(body(), mood="drained", session_type="workout")
        assert (profile.start, profile.end) == (3, 5)
        assert profile.ceiling == 4
        assert any("drained" in note for note in profile.notes)

    def test_low_readiness_caps_a_non_workout_session(self) -> None:
        profile = build_profile(
            body(readiness="low"), mood="fired_up", session_type="wake_up"
        )
        assert profile.ceiling == LOW_READINESS_CEILING
        assert max(profile.curve(10)) <= LOW_READINESS_CEILING
        assert any("recovery is low" in note.lower() for note in profile.notes)

    def test_a_ceiling_that_swallows_a_mood_still_says_so(self) -> None:
        """Here the cap leaves no trace in the numbers: wake_up already ends on the ceiling,
        so fired up's lift is absorbed rather than trimmed, and the curve is the plain one.
        The reason still has to be given, or the mix looks like it ignored the mood."""
        profile = build_profile(body(readiness="low"), mood="fired_up", session_type="wake_up")
        assert (profile.start, profile.end) == (2, 4)
        assert not any("fired up" in note for note in profile.notes)
        assert any("recovery is low" in note.lower() for note in profile.notes)

    def test_low_readiness_does_not_cap_a_workout_the_user_asked_for(self) -> None:
        profile = build_profile(body(readiness="low"), mood="steady", session_type="workout")
        assert profile.ceiling == 5

    def test_the_curve_never_leaves_one_to_five(self) -> None:
        for session_type in TYPE_RULES:
            for mood in MOODS:
                for readiness in ("low", "medium", "high", None):
                    profile = build_profile(
                        body(readiness=readiness), mood=mood, session_type=session_type
                    )
                    for value in profile.curve(12):
                        assert 1.0 <= value <= 5.0


class TestShift:
    def test_shift_lifts_a_drained_body_which_match_cannot(self) -> None:
        matched = build_profile(body(), mood="drained", session_type="focus", intent="match")
        shifted = build_profile(body(), mood="drained", session_type="focus", intent="shift")
        assert matched.end < matched.start or matched.end <= 2
        assert (shifted.start, shifted.end) == (2, 4)
        assert shifted.end > matched.end

    def test_shift_lifts_flat_to_the_top(self) -> None:
        profile = build_profile(body(), mood="flat", session_type="focus", intent="shift")
        assert (profile.start, profile.end) == (3, 5)

    def test_shift_brings_wired_down_harder_than_match(self) -> None:
        matched = build_profile(body(), mood="wired", session_type="focus", intent="match")
        shifted = build_profile(body(), mood="wired", session_type="focus", intent="shift")
        assert shifted.end < matched.end

    def test_shift_brings_fired_up_down(self) -> None:
        profile = build_profile(body(), mood="fired_up", session_type="focus", intent="shift")
        assert (profile.start, profile.end) == (4, 2)

    def test_steady_has_nowhere_to_shift_to(self) -> None:
        matched = build_profile(body(), mood="steady", session_type="focus", intent="match")
        shifted = build_profile(body(), mood="steady", session_type="focus", intent="shift")
        assert (shifted.start, shifted.end) == (matched.start, matched.end)
        assert any("nowhere" in note for note in shifted.notes)

    def test_shift_still_respects_a_low_recovery_ceiling(self) -> None:
        """A flat mood does not earn a 5 from a body that is not ready for it."""
        profile = build_profile(
            body(readiness="low"), mood="flat", session_type="focus", intent="shift"
        )
        assert profile.ceiling == LOW_READINESS_CEILING
        assert max(profile.curve(10)) == LOW_READINESS_CEILING
        assert any("recovery is low" in note.lower() for note in profile.notes)

    def test_shift_leaves_the_affinity_weights_alone(self) -> None:
        """SPEC: only the energy curve moves."""
        for session_type in TYPE_RULES:
            for mood in MOODS:
                matched = build_profile(body(), mood=mood, session_type=session_type)
                shifted = build_profile(
                    body(), mood=mood, session_type=session_type, intent="shift"
                )
                assert matched.affinities == shifted.affinities

    def test_shift_says_what_it_did(self) -> None:
        profile = build_profile(body(), mood="flat", session_type="wind_down", intent="shift")
        assert any("shift" in note for note in profile.notes)

    def test_an_unknown_intent_is_refused(self) -> None:
        with pytest.raises(ValueError, match="Unknown intent"):
            build_profile(body(), mood="flat", intent="sideways")

    def test_an_unknown_mood_is_refused(self) -> None:
        with pytest.raises(ValueError, match="Unknown mood"):
            build_profile(body(), mood="peckish")


class TestCurve:
    def test_it_samples_every_position(self) -> None:
        profile = build_profile(body(), mood="steady", session_type="wake_up")
        assert len(profile.curve(25)) == 25
        assert profile.curve(0) == []
        assert profile.curve(1) == [4.0]  # one track gets the destination

    def test_a_ramp_starts_and_ends_where_the_profile_says(self) -> None:
        profile = build_profile(body(), mood="steady", session_type="wake_up")
        curve = profile.curve(10)
        assert curve[0] == 2.0
        assert curve[-1] == 4.0
        assert curve == sorted(curve)

    def test_a_workout_eases_off_at_the_end(self) -> None:
        curve = build_profile(body(), mood="steady", session_type="workout").curve(20)
        assert max(curve) == 5.0
        assert curve[-1] < max(curve)
        assert curve.index(max(curve)) > len(curve) // 2

    def test_the_cool_off_never_eats_the_whole_ramp(self) -> None:
        curve = build_profile(body(), mood="steady", session_type="workout").curve(3)
        assert len(curve) == 3
        assert curve[1] > curve[0]

    def test_a_descending_curve_descends(self) -> None:
        curve = build_profile(body(), mood="steady", session_type="wind_down").curve(8)
        assert curve == sorted(curve, reverse=True)

    def test_a_stored_profile_carries_everything_history_needs(self) -> None:
        profile = build_profile(
            body(readiness="low"), mood="flat", session_type="auto", intent="shift"
        )
        stored = profile.as_dict(positions=5)
        assert stored["type"] in TYPE_RULES
        assert stored["intent"] == "shift"
        assert stored["mood"] == "flat"
        assert len(stored["curve"]) == 5
        assert set(stored["affinities"]) == set(profile.affinities)
        assert stored["notes"]


def test_every_session_type_has_a_rule() -> None:
    assert set(SESSION_TYPES) - {"auto"} == set(TYPE_RULES)


def test_a_profile_with_no_mood_still_works() -> None:
    """Mood is optional at the API edge, and a missing one must not crash the engine."""
    profile = build_profile(body(day_part="evening"), mood=None, session_type="auto")
    assert isinstance(profile, TargetProfile)
    assert profile.mood is None
    assert profile.curve(5)


def test_ceiling_for_is_usable_on_its_own() -> None:
    assert ceiling_for("focus", body(readiness="low"), "steady")[0] == LOW_READINESS_CEILING
    assert ceiling_for("workout", body(readiness="low"), "drained")[0] == 4
    assert ceiling_for("focus", body(readiness="high"), "steady")[0] == 5.0
