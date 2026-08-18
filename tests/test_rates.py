"""Tests for quote pricing and the minimum-stay rules (spec 3.4, 3.5)."""

from datetime import date
from decimal import Decimal

import pytest

from lib.models import ClientRate, SeasonDefinition, Unit
from lib.rates import (
    MinimumStayError,
    MissingRateError,
    build_quote,
    index_rates,
    minimum_stay_for,
)
from lib.seasons import segment_stay

JANUARY = [
    SeasonDefinition(1, "High", date(2027, 1, 1), date(2027, 1, 10), 2027),
    SeasonDefinition(2, "Medium", date(2027, 1, 11), date(2027, 1, 20), 2027),
    SeasonDefinition(3, "Low", date(2027, 1, 21), date(2027, 1, 31), 2027),
]


def rate(label, amount, min_nights=None, unit_id=1, year=2027):
    return ClientRate(unit_id, label, year, Decimal(amount), min_nights)


RATES = [rate("High", "2400.00"), rate("Medium", "1500.00"), rate("Low", "900.00")]


def unit(min_nights=2, id=1):
    return Unit(id=id, name="Seaview 3", beds=2, sleeps=4, owner_id=1, min_nights=min_nights)


def test_quote_is_built_up_line_by_line_across_seasons():
    """The spec worked example, priced: 10 high nights then 9 medium."""
    quote = build_quote(unit(), JANUARY, RATES, date(2027, 1, 1), date(2027, 1, 20))

    assert quote.nights == 19
    assert [(line.season_label, line.nights, line.subtotal) for line in quote.lines] == [
        ("High", 10, Decimal("24000.00")),
        ("Medium", 9, Decimal("13500.00")),
    ]
    assert quote.total == Decimal("37500.00")


def test_single_season_stay_is_one_line():
    quote = build_quote(unit(), JANUARY, RATES, date(2027, 1, 22), date(2027, 1, 25))

    assert len(quote.lines) == 1
    assert quote.lines[0].nights == 3
    assert quote.total == Decimal("2700.00")


def test_a_season_with_no_rate_on_file_stops_the_quote():
    with pytest.raises(MissingRateError) as raised:
        build_quote(unit(), JANUARY, [rate("High", "2400.00")], date(2027, 1, 8), date(2027, 1, 14))

    assert raised.value.season_label == "Medium"


def test_rates_are_versioned_by_year():
    """A 2027 rate does not price 2026 nights."""
    definitions = [
        SeasonDefinition(1, "High", date(2026, 12, 20), date(2026, 12, 31), 2026),
        SeasonDefinition(2, "High", date(2027, 1, 1), date(2027, 1, 15), 2027),
    ]
    rates = [rate("High", "2000.00", year=2026), rate("High", "2400.00", year=2027)]

    quote = build_quote(unit(), definitions, rates, date(2026, 12, 30), date(2027, 1, 3))

    assert [(line.nights, line.nightly_rate) for line in quote.lines] == [
        (2, Decimal("2000.00")),
        (2, Decimal("2400.00")),
    ]
    assert quote.total == Decimal("8800.00")


def test_unit_minimum_stay_blocks_a_short_booking():
    with pytest.raises(MinimumStayError) as raised:
        build_quote(unit(min_nights=2), JANUARY, RATES, date(2027, 1, 22), date(2027, 1, 23))

    assert raised.value.requested_nights == 1
    assert raised.value.check.source == "unit"


def test_the_one_unit_that_takes_single_nights_can_be_quoted_for_one():
    quote = build_quote(unit(min_nights=1), JANUARY, RATES, date(2027, 1, 22), date(2027, 1, 23))

    assert quote.nights == 1


def test_highest_rated_season_governs_the_minimum_not_the_longest_stretch():
    """A stay dipping from high into medium is still held to high's minimum."""
    rates = [rate("High", "2400.00", min_nights=5), rate("Medium", "1500.00", min_nights=2)]
    segments = segment_stay(JANUARY, date(2027, 1, 9), date(2027, 1, 16))

    check = minimum_stay_for(segments, index_rates(rates), unit_minimum=2)

    assert check.governing_season == "High"
    assert check.required_nights == 5
    assert check.source == "season"


def test_a_seven_night_stay_touching_high_season_for_two_nights_is_refused_at_a_five_night_minimum():
    rates = [rate("High", "2400.00", min_nights=8), rate("Medium", "1500.00", min_nights=2)]

    with pytest.raises(MinimumStayError) as raised:
        build_quote(unit(), JANUARY, rates, date(2027, 1, 9), date(2027, 1, 16))

    assert "High season requires a minimum of 8 nights" in str(raised.value)


def test_unit_minimum_wins_when_it_is_the_stricter_of_the_two():
    rates = [rate("Low", "900.00", min_nights=2)]
    segments = segment_stay(JANUARY, date(2027, 1, 22), date(2027, 1, 25))

    check = minimum_stay_for(segments, index_rates(rates), unit_minimum=4)

    assert check.required_nights == 4
    assert check.source == "unit"


def test_a_season_with_no_minimum_of_its_own_leaves_the_unit_rule_standing():
    segments = segment_stay(JANUARY, date(2027, 1, 2), date(2027, 1, 5))

    check = minimum_stay_for(segments, index_rates(RATES), unit_minimum=2)

    assert check.season_minimum is None
    assert check.required_nights == 2
    assert check.satisfied_by(3)


def test_tied_top_rates_take_the_stricter_minimum():
    rates = [rate("High", "2000.00", min_nights=3), rate("Medium", "2000.00", min_nights=6)]
    segments = segment_stay(JANUARY, date(2027, 1, 9), date(2027, 1, 14))

    check = minimum_stay_for(segments, index_rates(rates), unit_minimum=2)

    assert check.required_nights == 6
    assert check.governing_season == "Medium"
