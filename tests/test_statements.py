"""Tests for the monthly owner statement (spec 3.8)."""

from datetime import date
from decimal import Decimal

from lib.models import (
    CANCELLED,
    CONFIRMED,
    DONE,
    SCHEDULED,
    Booking,
    CleaningJob,
    OwnerRate,
    SeasonDefinition,
    Unit,
)
from lib.statements import build_statement, month_bounds, unit_statement

OWNER = 1
SEASONS = [
    SeasonDefinition(1, "High", date(2027, 1, 1), date(2027, 1, 15), 2027),
    SeasonDefinition(2, "Low", date(2027, 1, 16), date(2027, 2, 28), 2027),
]

FLAT = Unit(1, "Seaview 3", 2, 4, OWNER, Decimal("1800.00"))
OTHER_FLAT = Unit(2, "Dune Cottage", 3, 6, OWNER, Decimal("2500.00"))
SOMEONE_ELSES = Unit(3, "Not theirs", 2, 4, 99, Decimal("2000.00"))

OWNER_RATES = [
    OwnerRate(1, "High", 2027, Decimal("1800.00")),
    OwnerRate(1, "Low", 2027, Decimal("700.00")),
    OwnerRate(2, "High", 2027, Decimal("2400.00")),
    OwnerRate(2, "Low", 2027, Decimal("900.00")),
]


def stay(check_in, check_out, unit_id=1, status=CONFIRMED, id=1):
    return Booking(id, unit_id, 1, date(*check_in), date(*check_out), status)


def clean(day, cost, unit_id=1, status=DONE, label="post-clean"):
    return CleaningJob(1, unit_id, date(*day), label, None, None, status, Decimal(cost))


def test_the_month_runs_to_the_first_of_the_next():
    assert month_bounds(2027, 1) == (date(2027, 1, 1), date(2027, 2, 1))
    assert month_bounds(2027, 12) == (date(2027, 12, 1), date(2028, 1, 1))


def test_income_is_the_nights_slept_at_the_owner_rate():
    """5 nights in high season at the owner's 1800, not the guest's rate."""
    statement = unit_statement(
        FLAT, 2027, 1, [stay((2027, 1, 5), (2027, 1, 10))], OWNER_RATES, SEASONS
    )

    assert statement.nights == 5
    assert statement.rental_income == Decimal("9000.00")


def test_a_stay_crossing_a_season_is_valued_season_by_season():
    """14-18 Jan: the nights of the 14th and 15th are high season (which runs
    through the 15th), the 16th and 17th are low. 2x1800 + 2x700."""
    statement = unit_statement(
        FLAT, 2027, 1, [stay((2027, 1, 14), (2027, 1, 18))], OWNER_RATES, SEASONS
    )

    assert statement.nights == 4
    assert statement.rental_income == Decimal("5000.00")
    labels = [line.season_label for line in statement.stays[0].lines]
    assert labels == ["High", "Low"]


def test_a_stay_crossing_the_month_end_is_split_between_the_two_statements():
    """The nights are what belong to a month, not the stay that contains them."""
    crossing = stay((2027, 1, 29), (2027, 2, 3))

    january = unit_statement(FLAT, 2027, 1, [crossing], OWNER_RATES, SEASONS)
    february = unit_statement(FLAT, 2027, 2, [crossing], OWNER_RATES, SEASONS)

    assert january.nights == 3      # 29, 30, 31 January
    assert february.nights == 2     # 1, 2 February
    assert january.rental_income == Decimal("2100.00")
    assert february.rental_income == Decimal("1400.00")


def test_a_stay_wholly_in_another_month_contributes_nothing():
    statement = unit_statement(
        FLAT, 2027, 1, [stay((2027, 2, 5), (2027, 2, 9))], OWNER_RATES, SEASONS
    )

    assert statement.nights == 0
    assert statement.rental_income == Decimal("0.00")


def test_cancelled_stays_earn_the_owner_nothing():
    statement = unit_statement(
        FLAT, 2027, 1, [stay((2027, 1, 5), (2027, 1, 10), status=CANCELLED)], OWNER_RATES, SEASONS
    )

    assert statement.rental_income == Decimal("0.00")


def test_the_management_fee_is_due_whether_or_not_anyone_stayed():
    """A flat measured by a flat monthly amount, not by how full it was."""
    empty = unit_statement(FLAT, 2027, 1, [], OWNER_RATES, SEASONS)

    assert empty.rental_income == Decimal("0.00")
    assert empty.management_fee == Decimal("1800.00")
    assert empty.net == Decimal("-1800.00")


def test_only_cleans_actually_done_are_billed_on():
    """A job still sitting as scheduled has not been carried out."""
    jobs = [
        clean((2027, 1, 6), "450.00"),
        clean((2027, 1, 20), "500.00", status=SCHEDULED),
        clean((2027, 2, 3), "450.00"),                       # next month
        clean((2027, 1, 9), "600.00", unit_id=2),            # another flat
    ]

    statement = unit_statement(FLAT, 2027, 1, [], OWNER_RATES, SEASONS, jobs)

    assert statement.cleaning_cost == Decimal("450.00")
    assert len(statement.cleans) == 1


def test_the_net_is_income_less_the_fee_and_the_cleaning():
    statement = unit_statement(
        FLAT, 2027, 1, [stay((2027, 1, 5), (2027, 1, 10))], OWNER_RATES, SEASONS,
        [clean((2027, 1, 10), "450.00")],
    )

    assert statement.rental_income == Decimal("9000.00")
    assert statement.management_fee == Decimal("1800.00")
    assert statement.cleaning_cost == Decimal("450.00")
    assert statement.net == Decimal("6750.00")


def test_a_statement_covers_every_flat_the_owner_has():
    """Including one that stood empty - the fee is due on it either way, and a
    missing flat cannot be told apart from an oversight."""
    statement = build_statement(
        OWNER, [FLAT, OTHER_FLAT, SOMEONE_ELSES], 2027, 1,
        [stay((2027, 1, 5), (2027, 1, 10))], OWNER_RATES, SEASONS,
    )

    assert [unit.unit_name for unit in statement.units] == ["Dune Cottage", "Seaview 3"]
    assert statement.rental_income == Decimal("9000.00")
    assert statement.management_fees == Decimal("4300.00")
    assert statement.net == Decimal("4700.00")
    assert statement.period_name == "January 2027"


def test_another_owners_flat_never_appears():
    statement = build_statement(
        99, [FLAT, OTHER_FLAT, SOMEONE_ELSES], 2027, 1, [], OWNER_RATES, SEASONS
    )

    assert [unit.unit_name for unit in statement.units] == ["Not theirs"]


def test_a_missing_owner_rate_is_reported_rather_than_costed_at_nothing():
    """Silently paying an owner zero for a fortnight is the worst outcome."""
    statement = unit_statement(
        FLAT, 2027, 1, [stay((2027, 1, 5), (2027, 1, 10))],
        [OwnerRate(1, "Low", 2027, Decimal("700.00"))], SEASONS,
    )

    assert statement.rental_income == Decimal("0.00")
    assert statement.problems
    assert "High" in statement.problems[0]


def test_each_flat_is_valued_at_its_own_owner_rate():
    """The lookup is keyed on season and year, so this is worth pinning down."""
    both = build_statement(
        OWNER, [FLAT, OTHER_FLAT], 2027, 1,
        [stay((2027, 1, 5), (2027, 1, 10), unit_id=1, id=1),
         stay((2027, 1, 5), (2027, 1, 10), unit_id=2, id=2)],
        OWNER_RATES, SEASONS,
    )

    by_name = {unit.unit_name: unit for unit in both.units}
    assert by_name["Seaview 3"].rental_income == Decimal("9000.00")    # 5 x 1800
    assert by_name["Dune Cottage"].rental_income == Decimal("12000.00")  # 5 x 2400
