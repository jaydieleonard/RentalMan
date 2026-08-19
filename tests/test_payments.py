"""Tests for recording what has been paid against a statement (Phase 6)."""

from datetime import date
from decimal import Decimal

from lib.payments import OwnerPayment, settle


def payment(day, amount, id=1, statement_id=1, reference=""):
    return OwnerPayment(id, statement_id, date(*day), Decimal(amount), reference)


def test_a_statement_with_nothing_paid_is_simply_unpaid():
    state = settle(Decimal("10850.00"), [])

    assert state.outstanding == Decimal("10850.00")
    assert state.state == "unpaid"
    assert not state.is_settled
    assert state.describe() == "Not paid yet."


def test_one_payment_covering_it_settles_it():
    state = settle(Decimal("10850.00"), [payment((2026, 9, 3), "10850.00")])

    assert state.outstanding == Decimal("0.00")
    assert state.is_settled
    assert state.state == "settled"
    assert "Settled in one payment on 03 September 2026" in state.describe()


def test_a_part_payment_leaves_the_rest_outstanding():
    """The thing a single paid flag could never hold."""
    state = settle(Decimal("10850.00"), [payment((2026, 9, 3), "5000.00")])

    assert state.paid == Decimal("5000.00")
    assert state.outstanding == Decimal("5850.00")
    assert state.state == "part paid"
    assert not state.is_settled


def test_two_transfers_weeks_apart_add_up():
    state = settle(Decimal("10850.00"), [
        payment((2026, 9, 3), "5000.00", id=1),
        payment((2026, 9, 24), "5850.00", id=2),
    ])

    assert state.is_settled
    assert state.payments == 2
    assert state.last_paid_on == date(2026, 9, 24)
    assert "Settled in 2 payments on 24 September 2026" in state.describe()


def test_a_cent_out_still_counts_as_settled():
    """Chasing a rounding difference costs more than the difference."""
    state = settle(Decimal("10850.00"), [payment((2026, 9, 3), "10849.99")])

    assert state.is_settled
    assert state.outstanding == Decimal("0.01")


def test_a_month_that_cost_more_than_it_earned_is_owed_the_other_way():
    """An empty flat still carries its management fee and its cleaning."""
    state = settle(Decimal("-1800.00"), [])

    assert state.is_owed_to_us
    assert state.state == "owed to us"
    assert "owed to the business" in state.describe()


def test_an_overpayment_shows_as_a_credit_rather_than_settled_exactly():
    state = settle(Decimal("1000.00"), [payment((2026, 9, 3), "1200.00")])

    assert state.outstanding == Decimal("-200.00")
    assert not state.is_settled


def test_a_statement_of_nothing_needs_no_payment():
    state = settle(Decimal("0.00"), [])

    assert state.is_settled
    assert state.describe() == "Nothing to pay."
