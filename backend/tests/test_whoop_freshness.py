"""The freshness script reports only what moved."""

from __future__ import annotations

from scripts.whoop_freshness import changes


def test_first_reading_reports_everything() -> None:
    assert changes(None, {"recovery": 41.0, "day_strain": 3.2}) == {
        "recovery": (None, 41.0),
        "day_strain": (None, 3.2),
    }


def test_later_readings_report_only_differences() -> None:
    before = {"recovery": 41.0, "day_strain": 3.2, "workouts": 1}
    after = {"recovery": 41.0, "day_strain": 4.0, "workouts": 2}
    assert changes(before, after) == {"day_strain": (3.2, 4.0), "workouts": (1, 2)}


def test_no_change_is_empty() -> None:
    same = {"recovery": 41.0}
    assert changes(same, dict(same)) == {}
