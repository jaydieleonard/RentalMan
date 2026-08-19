"""Tests for what a guest's history adds up to (spec 3.6)."""

from datetime import date, timedelta
from decimal import Decimal

from lib.clients import summarise
from lib.models import CANCELLED, CONFIRMED, ENQUIRY, QUOTE_OPEN, Booking, SavedQuote

TODAY = date(2027, 6, 1)


def stay(check_in, check_out, status=CONFIRMED, total="5000.00", id=1):
    return Booking(id, 1, 1, date(*check_in), date(*check_out), status,
                   Decimal(total) if total else None)


def quote(status=QUOTE_OPEN):
    return SavedQuote(1, 1, 1, date(2027, 7, 1), date(2027, 7, 5), 2,
                      Decimal("4000.00"), status, date(2027, 5, 1))


def test_a_guest_with_no_history_reads_plainly():
    history = summarise([], [], TODAY)

    assert history.stays == 0
    assert history.spent == Decimal("0.00")
    assert history.describe(TODAY) == "No stays yet."


def test_confirmed_stays_are_counted_and_totalled():
    history = summarise(
        [stay((2026, 3, 1), (2026, 3, 8), total="7000.00", id=1),
         stay((2027, 1, 2), (2027, 1, 6), total="9000.00", id=2)],
        [], TODAY,
    )

    assert history.stays == 2
    assert history.nights == 11
    assert history.spent == Decimal("16000.00")
    assert history.is_repeat_guest


def test_enquiries_and_cancellations_are_not_visits():
    """Counting them would make a guest look more loyal than they are."""
    history = summarise(
        [stay((2026, 3, 1), (2026, 3, 8), id=1),
         stay((2026, 5, 1), (2026, 5, 8), status=CANCELLED, id=2),
         stay((2026, 9, 1), (2026, 9, 8), status=ENQUIRY, id=3)],
        [], TODAY,
    )

    assert history.stays == 1
    assert history.cancelled == 1
    assert not history.is_repeat_guest


def test_an_upcoming_stay_is_reported_separately_from_past_ones():
    history = summarise(
        [stay((2026, 3, 1), (2026, 3, 8), id=1),
         stay((2027, 8, 10), (2027, 8, 17), id=2)],
        [], TODAY,
    )

    assert history.last_stay == date(2026, 3, 8)
    assert history.next_stay == date(2027, 8, 10)
    assert "Booked again from 10 August 2027" in history.describe(TODAY)


def test_a_stay_in_progress_counts_as_upcoming_not_finished():
    """Somebody in the flat right now has not 'last stayed' - they are here."""
    history = summarise([stay((2027, 5, 30), (2027, 6, 4), id=1)], [], TODAY)

    assert history.last_stay is None
    assert history.next_stay == date(2027, 5, 30)


def test_open_quotes_are_carried_on_the_record():
    history = summarise([], [quote(), quote(status="accepted")], TODAY)

    assert history.open_quotes == 1


def test_a_stay_with_no_price_recorded_does_not_break_the_total():
    history = summarise([stay((2026, 3, 1), (2026, 3, 8), total=None)], [], TODAY)

    assert history.spent == Decimal("0.00")
    assert history.stays == 1
