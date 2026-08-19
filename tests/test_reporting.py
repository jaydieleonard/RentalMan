"""Tests for occupancy and revenue reporting (spec 9, Phase 6)."""

from datetime import date
from decimal import Decimal

from lib.models import CANCELLED, CONFIRMED, Booking, SeasonDefinition, Unit, UnitBlock
from lib.reporting import apportion, build_report, clipped_nights

JANUARY = (date(2027, 1, 1), date(2027, 2, 1))   # 31 nights
SEASONS = [
    SeasonDefinition(1, "High", date(2027, 1, 1), date(2027, 1, 10), 2027),
    SeasonDefinition(2, "Low", date(2027, 1, 11), date(2027, 1, 31), 2027),
]
FLAT = Unit(1, "Seaview 3", 2, 4, 1)
OTHER = Unit(2, "Dune Cottage", 3, 6, 2)


def stay(check_in, check_out, total="10000.00", unit_id=1, status=CONFIRMED, id=1):
    return Booking(id, unit_id, 1, date(*check_in), date(*check_out), status,
                   Decimal(total) if total else None)


def test_clipping_keeps_only_the_nights_inside_the_period():
    crossing = stay((2026, 12, 28), (2027, 1, 4))

    window = clipped_nights(crossing, *JANUARY)

    assert window == (date(2027, 1, 1), date(2027, 1, 4))


def test_a_stay_wholly_outside_contributes_nothing():
    assert clipped_nights(stay((2027, 3, 1), (2027, 3, 5)), *JANUARY) is None


def test_occupancy_is_let_nights_over_the_nights_available():
    report = build_report([FLAT], *JANUARY, [stay((2027, 1, 5), (2027, 1, 15))], SEASONS)

    unit = report.units[0]
    assert unit.nights_let == 10
    assert unit.nights_available == 31
    assert round(unit.occupancy, 3) == round(10 / 31, 3)


def test_blocked_nights_come_out_of_the_denominator():
    """A flat off the market for repairs was not empty for want of a guest."""
    blocks = [UnitBlock(1, 1, date(2027, 1, 20), date(2027, 1, 31), "Repaint")]

    report = build_report([FLAT], *JANUARY, [stay((2027, 1, 5), (2027, 1, 15))], SEASONS, blocks)

    unit = report.units[0]
    assert unit.nights_blocked == 11
    assert round(unit.occupancy, 3) == round(10 / 20, 3)


def test_revenue_is_scaled_to_the_part_of_the_stay_inside_the_period():
    """An 8-night stay at 8000, of which 3 nights fall in January."""
    crossing = stay((2026, 12, 29), (2027, 1, 4), total="6000.00")

    report = build_report([FLAT], *JANUARY, [crossing], SEASONS)

    assert report.units[0].nights_let == 3
    assert report.units[0].revenue == Decimal("3000.00")   # 3 of 6 nights


def test_cancelled_stays_count_for_nothing():
    report = build_report([FLAT], *JANUARY, [stay((2027, 1, 5), (2027, 1, 15), status=CANCELLED)], SEASONS)

    assert report.units[0].nights_let == 0
    assert report.revenue == Decimal("0.00")


def test_revenue_is_split_across_the_seasons_it_was_earned_in():
    """8-15 Jan: three high-season nights and four low, out of 7000 charged."""
    report = build_report([FLAT], *JANUARY, [stay((2027, 1, 8), (2027, 1, 15), total="7000.00")], SEASONS)

    by_label = {season.season_label: season for season in report.seasons}
    assert by_label["High"].nights_let == 3
    assert by_label["Low"].nights_let == 4
    assert by_label["High"].revenue + by_label["Low"].revenue == Decimal("7000.00")


def test_the_season_split_always_sums_back_to_the_total():
    """Rounding each share alone would leave the seasons not adding up."""
    report = build_report(
        [FLAT], *JANUARY, [stay((2027, 1, 8), (2027, 1, 15), total="1000.01")], SEASONS
    )

    assert sum(season.revenue for season in report.seasons) == Decimal("1000.01")


def test_apportioning_hands_the_odd_cents_out_rather_than_losing_them():
    shares = apportion(Decimal("10.00"), [Decimal(1), Decimal(1), Decimal(1)])

    assert sum(shares) == Decimal("10.00")
    assert sorted(shares) == [Decimal("3.33"), Decimal("3.33"), Decimal("3.34")]


def test_flats_are_ranked_by_what_they_earned():
    report = build_report(
        [FLAT, OTHER], *JANUARY,
        [stay((2027, 1, 5), (2027, 1, 10), total="4000.00", unit_id=1, id=1),
         stay((2027, 1, 5), (2027, 1, 10), total="9000.00", unit_id=2, id=2)],
        SEASONS,
    )

    assert [unit.unit_name for unit in report.units] == ["Dune Cottage", "Seaview 3"]
    assert report.revenue == Decimal("13000.00")


def test_a_flat_that_was_never_let_still_appears():
    """An empty flat is the most interesting row on an occupancy report."""
    report = build_report([FLAT, OTHER], *JANUARY, [stay((2027, 1, 5), (2027, 1, 10), unit_id=1)], SEASONS)

    empty = next(unit for unit in report.units if unit.unit_name == "Dune Cottage")
    assert empty.nights_let == 0
    assert empty.occupancy == 0.0
    assert empty.revenue == Decimal("0.00")


def test_revenue_per_available_night_says_what_a_flat_is_worth_a_night():
    """Two flats can earn the same and be worth very different amounts."""
    report = build_report([FLAT], *JANUARY, [stay((2027, 1, 5), (2027, 1, 15), total="9300.00")], SEASONS)

    assert report.units[0].revenue_per_available_night == Decimal("300.00")   # 9300 / 31


def test_owners_are_totalled_separately():
    report = build_report(
        [FLAT, OTHER], *JANUARY,
        [stay((2027, 1, 5), (2027, 1, 10), total="4000.00", unit_id=1, id=1),
         stay((2027, 1, 5), (2027, 1, 10), total="9000.00", unit_id=2, id=2)],
        SEASONS,
    )

    rows = report.by_owner({1: "A. Petersen", 2: "S. Nkosi"})

    assert rows[0][0] == "S. Nkosi"
    assert rows[0][2] == Decimal("9000.00")
    assert rows[1][0] == "A. Petersen"


def test_nights_no_season_covers_are_reported_not_swallowed():
    """A hole in the season calendar should show up here, not hide."""
    report = build_report(
        [FLAT], *JANUARY, [stay((2027, 1, 5), (2027, 1, 10))],
        [SeasonDefinition(1, "High", date(2027, 1, 1), date(2027, 1, 3), 2027)],
    )

    assert report.unattributed_nights == 5
    assert report.units[0].nights_let == 5, "the nights still count towards occupancy"


def test_a_stay_with_no_price_still_counts_towards_occupancy():
    report = build_report([FLAT], *JANUARY, [stay((2027, 1, 5), (2027, 1, 10), total=None)], SEASONS)

    assert report.units[0].nights_let == 5
    assert report.units[0].revenue == Decimal("0.00")
