"""Tests for the season calendar and stay segmenting (spec 3.3, 3.5)."""

from datetime import date

import pytest

from lib.models import SeasonDefinition
from lib.seasons import (
    InvalidStayError,
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
