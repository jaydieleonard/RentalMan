"""Tests for turnover buffers and availability (spec 3.2, 3.10)."""

from datetime import date

from lib.models import (
    CANCELLED,
    CONFIRMED,
    QUOTED,
    Booking,
    SeasonDefinition,
    TurnoverRule,
    UnitBlock,
)
from lib.availability import BLOCKED, BOOKED, BUFFER, OPEN, is_available, occupancy

UNIT = 1

SEASONS = [
    SeasonDefinition(1, "High", date(2027, 1, 1), date(2027, 1, 10), 2027),
    SeasonDefinition(2, "Low", date(2027, 1, 11), date(2027, 1, 31), 2027),
]


def booking(check_in, check_out, status=CONFIRMED, id=1, unit_id=UNIT):
    return Booking(id, unit_id, 1, date(*check_in), date(*check_out), status)


def test_same_day_turnover_is_allowed_by_default():
    """The confirmed norm: guest out on the 5th, next guest in on the 5th."""
    existing = [booking((2027, 1, 2), (2027, 1, 5))]

    result = is_available(UNIT, date(2027, 1, 5), date(2027, 1, 8), existing)

    assert result.available


def test_a_unit_needing_a_clear_day_blocks_the_checkout_night():
    existing = [booking((2027, 1, 2), (2027, 1, 5))]
    rules = [TurnoverRule(UNIT, None, 1)]

    blocked = is_available(UNIT, date(2027, 1, 5), date(2027, 1, 8), existing, rules)
    next_day = is_available(UNIT, date(2027, 1, 6), date(2027, 1, 8), existing, rules)

    assert not blocked.available
    assert blocked.blocked_nights == (date(2027, 1, 5),)
    assert "turnover gap" in blocked.reason
    assert next_day.available


def test_the_buffer_also_protects_the_night_before_a_check_in():
    existing = [booking((2027, 1, 10), (2027, 1, 14))]
    rules = [TurnoverRule(UNIT, None, 1)]

    up_to_check_in = is_available(UNIT, date(2027, 1, 6), date(2027, 1, 10), existing, rules)
    a_night_short = is_available(UNIT, date(2027, 1, 6), date(2027, 1, 9), existing, rules)

    assert not up_to_check_in.available
    assert up_to_check_in.blocked_nights == (date(2027, 1, 9),)
    assert a_night_short.available


def test_a_season_rule_overrides_the_units_default_buffer():
    """Same-day most of the year, a clear day in high season when cleaning is tight."""
    rules = [TurnoverRule(UNIT, None, 0), TurnoverRule(UNIT, "High", 1)]
    in_high = [booking((2027, 1, 2), (2027, 1, 5))]
    in_low = [booking((2027, 1, 12), (2027, 1, 15))]

    high_turnover = is_available(UNIT, date(2027, 1, 5), date(2027, 1, 8), in_high, rules, SEASONS)
    low_turnover = is_available(UNIT, date(2027, 1, 15), date(2027, 1, 18), in_low, rules, SEASONS)

    assert not high_turnover.available
    assert low_turnover.available


def test_the_buffer_follows_the_season_of_the_turnover_day_itself():
    """A stay running out of high season into low turns over under low's rule."""
    rules = [TurnoverRule(UNIT, None, 0), TurnoverRule(UNIT, "High", 1)]
    existing = [booking((2027, 1, 8), (2027, 1, 13))]

    result = is_available(UNIT, date(2027, 1, 13), date(2027, 1, 16), existing, rules, SEASONS)

    assert result.available


def test_only_confirmed_bookings_hold_the_dates():
    for status in (QUOTED, CANCELLED):
        result = is_available(UNIT, date(2027, 1, 2), date(2027, 1, 5), [booking((2027, 1, 1), (2027, 1, 6), status)])
        assert result.available, status


def test_another_units_booking_is_irrelevant():
    existing = [booking((2027, 1, 2), (2027, 1, 8), unit_id=99)]

    assert is_available(UNIT, date(2027, 1, 2), date(2027, 1, 5), existing).available


def test_maintenance_blocks_the_unit_too():
    blocks = [UnitBlock(1, UNIT, date(2027, 1, 4), date(2027, 1, 7), "Bathroom retile")]

    result = is_available(UNIT, date(2027, 1, 2), date(2027, 1, 5), [], blocks=blocks)

    assert not result.available
    assert result.blocked_nights == (date(2027, 1, 4),)
    assert "blocked" in result.reason


def test_a_booking_can_be_rechecked_without_blocking_itself():
    existing = [booking((2027, 1, 2), (2027, 1, 6), id=7)]

    moved = is_available(UNIT, date(2027, 1, 3), date(2027, 1, 8), existing, ignore_booking_id=7)

    assert moved.available


def test_occupancy_marks_stay_buffer_and_open_nights_apart():
    """What the grid draws: booked nights, the held turnover night, then open."""
    existing = [booking((2027, 1, 12), (2027, 1, 15))]
    rules = [TurnoverRule(UNIT, None, 1)]

    nights = occupancy(UNIT, date(2027, 1, 10), date(2027, 1, 18), existing, rules, SEASONS)

    assert [nights[date(2027, 1, day)].status for day in range(10, 18)] == [
        OPEN,
        BUFFER,
        BOOKED,
        BOOKED,
        BOOKED,
        BUFFER,
        OPEN,
        OPEN,
    ]


def test_a_booked_night_beats_a_neighbours_buffer_in_the_same_cell():
    """Two stays tight against each other read as booked, never as a free gap."""
    existing = [
        booking((2027, 1, 12), (2027, 1, 15), id=1),
        booking((2027, 1, 15), (2027, 1, 18), id=2),
    ]

    nights = occupancy(UNIT, date(2027, 1, 12), date(2027, 1, 18), existing)

    assert nights[date(2027, 1, 15)].status == BOOKED
    assert nights[date(2027, 1, 15)].booking_id == 2


def test_maintenance_shows_on_the_grid_as_blocked_with_its_reason():
    blocks = [UnitBlock(1, UNIT, date(2027, 1, 4), date(2027, 1, 6), "Bathroom retile")]

    nights = occupancy(UNIT, date(2027, 1, 3), date(2027, 1, 7), [], blocks=blocks)

    assert nights[date(2027, 1, 4)].status == BLOCKED
    assert nights[date(2027, 1, 4)].label == "Bathroom retile"
    assert nights[date(2027, 1, 6)].status == OPEN


def test_a_clash_says_which_kind_it_is():
    """Callers treat a double-booking and a turnover gap differently."""
    rules = [TurnoverRule(UNIT, None, 1)]
    existing = [booking((2027, 1, 2), (2027, 1, 5))]
    blocks = [UnitBlock(1, UNIT, date(2027, 1, 20), date(2027, 1, 22), "Repaint")]

    on_top = is_available(UNIT, date(2027, 1, 3), date(2027, 1, 6), existing, rules)
    in_the_gap = is_available(UNIT, date(2027, 1, 5), date(2027, 1, 8), existing, rules)
    on_a_block = is_available(UNIT, date(2027, 1, 20), date(2027, 1, 23), [], blocks=blocks)

    assert (on_top.kind, in_the_gap.kind, on_a_block.kind) == (BOOKED, BUFFER, BLOCKED)
