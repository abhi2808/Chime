"""Tagging maths and the shipped tag map.

No network and no database: ``compute`` is a pure function, which is the point of
keeping tag supply behind :class:`TagSource`.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.tagging import (
    AFFINITIES,
    NEUTRAL_ENERGY,
    TagMap,
    TagMapError,
    compute,
    load_tag_map,
    normalize,
    reset_tag_map,
)

SMALL = TagMap.from_data(
    {
        "tags": {
            "ambient": {"energy": 1, "calm": 0.9, "focus": 0.8},
            "drum and bass": {"energy": 5, "workout": 1.0},
            "rock": {"energy": 3.5, "weight": 0.5},
            "shoegaze": {"energy": 3, "focus": 0.6},
            "silent": {"energy": 2, "weight": 0},
        },
        "aliases": {"dnb": "drum and bass", "d&b": "drum and bass"},
        "ignore": ["british", "seen live"],
    }
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Hip-Hop", "hip hop"),
        ("  HIP   HOP  ", "hip hop"),
        ("R&B", "r&b"),
        ("lo-fi hip hop", "lo fi hip hop"),
        ("post-rock", "post rock"),
        ("drum & bass", "drum & bass"),
        ("90s!!", "90s"),
        ("", ""),
    ],
)
def test_normalize_folds_spelling_but_not_words(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


def test_aliases_resolve_to_a_canonical_entry() -> None:
    assert SMALL.lookup("DNB") == SMALL.lookup("drum and bass")
    assert SMALL.lookup("d&b") == SMALL.lookup("drum and bass")
    assert SMALL.lookup("nonsense") is None


def test_an_unknown_track_is_neutral_at_zero_confidence() -> None:
    result = compute([], SMALL)
    assert result.energy == NEUTRAL_ENERGY
    assert result.confidence == 0.0
    assert result.affinities == {}
    assert result.is_known is False


def test_unrecognised_tags_are_reported_not_guessed() -> None:
    result = compute([("witch house", 1.0), ("Hyperpop", 0.5)], SMALL)
    assert result.energy == NEUTRAL_ENERGY
    assert result.confidence == 0.0
    assert result.unmatched == ("witch house", "hyperpop")


def test_a_single_strong_tag_carries_its_own_energy() -> None:
    result = compute([("ambient", 1.0)], SMALL)
    assert result.energy == 1.0
    assert result.affinities == {"calm": 0.9, "focus": 0.8}
    assert result.matched == ("ambient",)
    assert 0 < result.confidence <= 1


def test_energy_is_a_weighted_average_of_matches() -> None:
    # ambient 1 at weight 1.0, drum and bass 5 at weight 0.5 -> (1 + 2.5) / 1.5
    result = compute([("ambient", 1.0), ("drum and bass", 0.5)], SMALL)
    assert result.energy == pytest.approx(2.333, abs=0.001)


def test_a_precise_tag_outweighs_an_umbrella_tag() -> None:
    """``rock`` carries weight 0.5, so ``shoegaze`` should dominate a track with both."""
    both = compute([("rock", 1.0), ("shoegaze", 1.0)], SMALL)
    assert both.matched[0] == "shoegaze"
    assert both.energy < 3.25  # the unweighted mean of 3.5 and 3


def test_two_spellings_of_one_tag_do_not_double_count() -> None:
    once = compute([("drum and bass", 1.0)], SMALL)
    twice = compute([("drum and bass", 1.0), ("dnb", 1.0)], SMALL)
    assert twice.energy == once.energy
    assert twice.matched == once.matched


def test_unmatched_tags_lower_confidence_without_moving_energy() -> None:
    clean = compute([("ambient", 1.0)], SMALL)
    noisy = compute([("ambient", 1.0), ("witch house", 1.0)], SMALL)
    assert noisy.energy == clean.energy
    assert noisy.confidence < clean.confidence
    assert noisy.unmatched == ("witch house",)


def test_ignored_tags_are_not_held_against_a_track() -> None:
    """MusicBrainz artists carry nationality, role and era tags. Counting those as tags
    we failed to understand reads a well-tagged artist as a badly tagged one."""
    clean = compute([("ambient", 1.0)], SMALL)
    noisy = compute([("ambient", 1.0), ("british", 1.0), ("Seen Live", 1.0)], SMALL)
    assert noisy.confidence == clean.confidence
    assert noisy.energy == clean.energy
    assert noisy.unmatched == ()


def test_an_ignored_tag_is_still_recorded_on_the_row() -> None:
    """``raw_tags`` exists so a later map can re-read tags without re-fetching them."""
    result = compute([("british", 0.5)], SMALL)
    assert result.raw == (("british", 0.5),)
    assert result.confidence == 0.0
    assert result.energy == NEUTRAL_ENERGY


def test_a_tag_cannot_be_both_defined_and_ignored() -> None:
    with pytest.raises(TagMapError, match="both defined and ignored"):
        TagMap.from_data({"tags": {"ambient": {"energy": 1}}, "ignore": ["Ambient"]})


def test_an_ignore_list_that_is_not_a_list_fails_loudly() -> None:
    with pytest.raises(TagMapError, match="must be a list"):
        TagMap.from_data({"tags": {"ambient": {"energy": 1}}, "ignore": "british"})


def test_thin_evidence_is_not_fully_trusted() -> None:
    thin = compute([("ambient", 0.2)], SMALL)
    thick = compute([("ambient", 1.0), ("shoegaze", 1.0)], SMALL)
    assert thin.confidence < thick.confidence
    assert thick.confidence == 1.0


def test_a_zero_weight_entry_cannot_decide_a_track() -> None:
    result = compute([("silent", 1.0)], SMALL)
    assert result.energy == NEUTRAL_ENERGY
    assert result.confidence == 0.0


def test_source_weights_are_clamped_to_zero_one() -> None:
    assert compute([("ambient", 4.0)], SMALL).energy == 1.0
    assert compute([("ambient", -1.0)], SMALL).confidence == 0.0


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"tags": {}}, "no 'tags'"),
        ({"tags": {"x": {"energy": 9}}}, "between"),
        ({"tags": {"x": {"energy": 3, "vibe": 1}}}, "unknown keys"),
        ({"tags": {"x": {"calm": 1}}}, "no energy"),
        ({"tags": {"x": {"energy": "high"}}}, "must be a number"),
        ({"tags": {"x": {"energy": 3, "calm": 2}}}, "between"),
        ({"tags": {"x": {"energy": 3}}, "aliases": {"y": "z"}}, "unknown tag"),
    ],
)
def test_a_broken_map_fails_loudly(data: dict, message: str) -> None:
    with pytest.raises(TagMapError, match=message):
        TagMap.from_data(data)


def test_a_missing_map_file_is_a_clear_error(tmp_path) -> None:
    with pytest.raises(TagMapError, match="cannot read tag map"):
        TagMap.load(tmp_path / "nope.yaml")


class TestRankWeighting:
    """A tag's position in the source's list is data: the first two say what a thing is."""

    def test_the_top_tag_decides_more_than_the_tail(self) -> None:
        loud_first = compute([("drum and bass", 1.0), ("ambient", 1.0)], SMALL)
        quiet_first = compute([("ambient", 1.0), ("drum and bass", 1.0)], SMALL)
        # The first two ranks are deliberately equal, so these two agree...
        assert loud_first.energy == quiet_first.energy == 3.0
        # ...but push the same tag to fourth and it stops deciding.
        demoted = compute(
            [("ambient", 1.0), ("shoegaze", 1.0), ("shoegaze rock", 1.0), ("drum and bass", 1.0)],
            SMALL,
        )
        assert demoted.energy < 3.0

    def test_a_long_tail_cannot_drag_a_clear_track_to_the_middle(self) -> None:
        """The reason the weights exist: eight tags averaged flat land on 3, and a library
        of 3s cannot fill a wind-down or a workout."""
        flat = compute([("ambient", 1.0)] + [("rock", 1.0)] * 1, SMALL)
        assert flat.energy < 2.5

    def test_tags_beyond_the_table_are_dropped_not_counted_against_us(self) -> None:
        tags = [("ambient", 1.0)] + [(f"unknown {index}", 1.0) for index in range(12)]
        many = compute(tags, SMALL)
        few = compute(tags[:9], SMALL)
        assert many.confidence == few.confidence
        # Every supplied tag is still recorded, so a later map can use them.
        assert len(many.raw) == 13

    def test_an_ignored_tag_does_not_use_up_a_rank(self) -> None:
        """Otherwise "british" in first place would demote the genre behind it."""
        with_noise = compute([("british", 1.0), ("seen live", 1.0), ("ambient", 1.0)], SMALL)
        without = compute([("ambient", 1.0)], SMALL)
        assert with_noise.energy == without.energy
        assert with_noise.confidence == without.confidence


class TestInheritedTags:
    """Tag vocabularies are open, so the tail is mostly qualified versions of known names."""

    def test_a_compound_tag_reads_through_to_the_genre_inside_it(self) -> None:
        resolved = SMALL.resolve("melodic shoegaze")
        assert resolved is not None
        name, entry, factor = resolved
        assert name == "shoegaze"
        assert entry.energy == 3
        assert factor < 1.0  # inherited, so discounted

    def test_an_exact_entry_beats_reading_through(self) -> None:
        assert SMALL.resolve("rock") == ("rock", SMALL.entries["rock"], 1.0)

    def test_the_head_noun_wins_over_the_qualifier(self) -> None:
        """"ambient rock" is rock that is ambient, and English puts the noun last."""
        resolved = SMALL.resolve("ambient rock")
        assert resolved is not None
        assert resolved[0] == "rock"

    def test_the_longest_known_phrase_wins(self) -> None:
        resolved = SMALL.resolve("liquid drum and bass")
        assert resolved is not None
        assert resolved[0] == "drum and bass"

    def test_an_alias_inside_a_compound_still_resolves(self) -> None:
        resolved = SMALL.resolve("liquid dnb")
        assert resolved is not None
        assert resolved[0] == "drum and bass"

    def test_a_single_unknown_word_stays_unknown(self) -> None:
        assert SMALL.resolve("rockgruppe") is None
        assert compute([("rockgruppe", 1.0)], SMALL).confidence == 0.0

    def test_inheritance_raises_confidence_without_pretending_to_certainty(self) -> None:
        inherited = compute([("melodic shoegaze", 1.0)], SMALL)
        exact = compute([("shoegaze", 1.0)], SMALL)
        assert inherited.energy == exact.energy
        assert 0.0 < inherited.confidence < exact.confidence

    def test_two_tags_that_mean_one_thing_are_named_once(self) -> None:
        tagging = compute([("shoegaze", 1.0), ("dreamy shoegaze", 1.0)], SMALL)
        assert tagging.matched == ("shoegaze",)


class TestShippedMap:
    """The real ``data/tag_map.yaml`` has to load and has to say sensible things."""

    @pytest.fixture(autouse=True)
    def real_map(self) -> TagMap:
        reset_tag_map()
        return load_tag_map(settings.tag_map_file)

    def test_it_loads(self, real_map: TagMap) -> None:
        assert len(real_map.entries) > 100
        assert real_map.aliases
        assert real_map.ignored

    def test_a_real_artists_tags_survive_the_noise_around_them(self, real_map: TagMap) -> None:
        """Massive Attack, live from MusicBrainz: five genres and two tags about where
        the band is from. The energy should come from the five."""
        result = compute(
            [
                ("trip hop", 1.0),
                ("electronic", 0.78),
                ("downtempo", 0.52),
                ("ambient", 0.3),
                ("dub", 0.26),
                ("british", 0.22),
                ("seen live", 0.13),
            ],
            real_map,
        )
        assert result.confidence > 0.7
        assert result.energy < NEUTRAL_ENERGY
        assert "british" not in result.unmatched

    def test_quiet_genres_are_quiet_and_loud_genres_are_loud(self, real_map: TagMap) -> None:
        assert compute([("ambient", 1.0)], real_map).energy <= 1.5
        assert compute([("drum and bass", 1.0)], real_map).energy >= 4.5

    def test_the_affinities_a_profile_asks_for_all_exist_somewhere(
        self, real_map: TagMap
    ) -> None:
        offered = {
            affinity
            for entry in real_map.entries.values()
            for affinity, value in entry.affinities.items()
            if value > 0
        }
        assert offered == set(AFFINITIES)

    def test_a_focus_session_has_something_to_choose(self, real_map: TagMap) -> None:
        focused = compute([("lo-fi hip hop", 1.0)], real_map)
        assert focused.affinities["focus"] >= 0.8
        assert focused.energy <= 2.5
