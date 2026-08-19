"""Tests for the season calendar and stay segmenting (spec 3.3, 3.5)."""

from datetime import date

import pytest

from lib.models import SeasonDefinition
from lib.seasons import (
    InvalidStayError,
    carve_out,
    UnpricedNightError,
    find_gaps,
    season_for_date,
    segment_stay,
    validate_calendar,
)


def season(label, start, end, year=2027, id=None):
    return SeasonDefinition(id, label, date(*start), date(*end), year)


JANUARY = [
    season("High", (2027, 1, 1), (2027, 1, 10)),
    season("Medium", (2027, 1, 11), (2027, 1, 20)),
    season("Low", (2027, 1, 21), (2027, 1, 31)),
]


def test_worked_example_from_the_spec():
    """1-20 Jan against High 1-10 / Medium 11-20 is 10 high nights then 9 medium."""
    segments = segment_stay(JANUARY, date(2027, 1, 1), date(2027, 1, 20))

    assert [(s.season_label, s.nights) for s in segments] == [("High", 10), ("Medium", 9)]
    assert sum(s.nights for s in segments) == 19
    assert segments[0].first_night == date(2027, 1, 1)
    assert segments[0].last_night == date(2027, 1, 10)
    assert segments[1].last_night == date(2027, 1, 19)


def test_check_out_date_is_not_a_charged_night():
    segments = segment_stay(JANUARY, date(2027, 1, 5), date(2027, 1, 6))

    assert len(segments) == 1
    assert segments[0].nights == 1
    assert segments[0].last_night == date(2027, 1, 5)


def test_stay_inside_one_season_is_one_segment():
    segments = segment_stay(JANUARY, date(2027, 1, 2), date(2027, 1, 6))

    assert [(s.season_label, s.nights) for s in segments] == [("High", 4)]


def test_stay_can_cross_more_than_two_seasons():
    """The spec is explicit that a stay is not capped at two seasons."""
    segments = segment_stay(JANUARY, date(2027, 1, 8), date(2027, 1, 25))

    assert [(s.season_label, s.nights) for s in segments] == [
        ("High", 3),
        ("Medium", 10),
        ("Low", 4),
    ]


def test_a_season_returning_later_gets_its_own_segment():
    """Medium -> High -> Medium is three segments, not two merged mediums."""
    definitions = [
        season("Medium", (2027, 6, 1), (2027, 6, 10)),
        season("High", (2027, 6, 11), (2027, 6, 15)),
        season("Medium", (2027, 6, 16), (2027, 6, 30)),
    ]

    segments = segment_stay(definitions, date(2027, 6, 9), date(2027, 6, 18))

    assert [(s.season_label, s.nights) for s in segments] == [
        ("Medium", 2),
        ("High", 5),
        ("Medium", 2),
    ]


def test_same_season_in_different_rate_years_splits():
    """A New Year stay prices off two rate versions, so it is two segments."""
    definitions = [
        season("High", (2026, 12, 20), (2026, 12, 31), year=2026),
        season("High", (2027, 1, 1), (2027, 1, 15), year=2027),
    ]

    segments = segment_stay(definitions, date(2026, 12, 30), date(2027, 1, 3))

    assert [(s.season_label, s.season_year, s.nights) for s in segments] == [
        ("High", 2026, 2),
        ("High", 2027, 2),
    ]


def test_a_night_with_no_season_is_refused_not_priced_at_zero():
    with pytest.raises(UnpricedNightError) as raised:
        segment_stay(JANUARY, date(2027, 1, 29), date(2027, 2, 3))

    assert raised.value.missing == (date(2027, 2, 1), date(2027, 2, 2))


def test_check_out_before_check_in_is_not_a_stay():
    with pytest.raises(InvalidStayError):
        segment_stay(JANUARY, date(2027, 1, 10), date(2027, 1, 10))


def test_season_for_date_is_inclusive_at_both_ends():
    assert season_for_date(JANUARY, date(2027, 1, 1)) == "High"
    assert season_for_date(JANUARY, date(2027, 1, 10)) == "High"
    assert season_for_date(JANUARY, date(2027, 1, 11)) == "Medium"
    assert season_for_date(JANUARY, date(2027, 2, 1)) is None


def test_overlapping_seasons_are_an_error():
    definitions = [
        season("High", (2027, 1, 1), (2027, 1, 15)),
        season("Medium", (2027, 1, 10), (2027, 1, 20)),
    ]

    problems = validate_calendar(definitions)

    assert [p.severity for p in problems] == ["error"]
    assert "overlaps" in problems[0].message


def test_backwards_range_is_an_error():
    problems = validate_calendar([season("Low", (2027, 3, 10), (2027, 3, 1))])

    assert [p.severity for p in problems] == ["error"]
    assert "ends before it starts" in problems[0].message


def test_uncovered_dates_are_only_a_warning():
    problems = validate_calendar(JANUARY, year=2027)

    assert {p.severity for p in problems} == {"warning"}
    assert "2027-02-01" in problems[0].message


def test_a_fully_covered_year_reports_nothing():
    definitions = [season("Low", (2027, 1, 1), (2027, 12, 31))]

    assert validate_calendar(definitions, year=2027) == []


def test_gaps_are_reported_as_inclusive_ranges():
    definitions = [
        season("Low", (2027, 1, 1), (2027, 3, 31)),
        season("High", (2027, 5, 1), (2027, 12, 31)),
    ]

    assert find_gaps(definitions, 2027) == [(date(2027, 4, 1), date(2027, 4, 30))]


def test_a_new_period_pushes_back_the_one_it_overlaps():
    """Painting High over the start of Low shortens Low rather than being refused."""
    existing = [season("Low", (2026, 3, 1), (2026, 7, 1), id=1)]

    changes = carve_out(existing, date(2026, 3, 1), date(2026, 4, 16))

    assert len(changes) == 1
    assert changes[0].kind == "shortened"
    survivor = changes[0].replacements[0]
    assert survivor.start_date == date(2026, 4, 17)
    assert survivor.end_date == date(2026, 7, 1)


def test_a_period_landing_in_the_middle_splits_the_other_in_two():
    existing = [season("Low", (2026, 3, 1), (2026, 7, 1), id=1)]

    changes = carve_out(existing, date(2026, 4, 3), date(2026, 4, 16))

    assert changes[0].kind == "split"
    before, after = changes[0].replacements
    assert (before.start_date, before.end_date) == (date(2026, 3, 1), date(2026, 4, 2))
    assert (after.start_date, after.end_date) == (date(2026, 4, 17), date(2026, 7, 1))
    assert after.id is None, "the second half is a new row, not the original"


def test_a_period_wholly_covered_is_removed():
    existing = [season("Medium", (2026, 4, 5), (2026, 4, 10), id=1)]

    changes = carve_out(existing, date(2026, 4, 1), date(2026, 4, 30))

    assert changes[0].kind == "removed"
    assert changes[0].replacements == ()


def test_a_period_that_ends_before_it_starts_being_moved_is_left_alone():
    existing = [
        season("Low", (2026, 1, 1), (2026, 2, 28), id=1),
        season("Medium", (2026, 8, 1), (2026, 9, 30), id=2),
    ]

    assert carve_out(existing, date(2026, 4, 1), date(2026, 4, 30)) == []


def test_a_period_being_moved_does_not_give_way_to_itself():
    """Editing High's own dates must not treat High as an obstacle."""
    existing = [season("High", (2026, 1, 1), (2026, 1, 15), id=7)]

    assert carve_out(existing, date(2026, 1, 5), date(2026, 1, 20), ignore_id=7) == []


def test_one_period_can_displace_several_at_once():
    existing = [
        season("Low", (2026, 3, 1), (2026, 3, 31), id=1),
        season("Medium", (2026, 4, 1), (2026, 4, 30), id=2),
        season("Low", (2026, 5, 1), (2026, 5, 31), id=3),
    ]

    changes = carve_out(existing, date(2026, 3, 20), date(2026, 5, 10))

    assert [change.kind for change in changes] == ["shortened", "removed", "shortened"]
    assert changes[0].replacements[0].end_date == date(2026, 3, 19)
    assert changes[2].replacements[0].start_date == date(2026, 5, 11)


def test_the_change_says_what_happened_in_words():
    existing = [season("Low", (2026, 3, 1), (2026, 7, 1), id=1)]

    described = carve_out(existing, date(2026, 4, 3), date(2026, 4, 16))[0].describe()

    assert "was split into" in described
    assert "2026-03-01 to 2026-04-02" in described
    assert "2026-04-17 to 2026-07-01" in described
