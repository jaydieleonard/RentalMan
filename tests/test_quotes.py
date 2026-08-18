"""Tests for the follow-up flag and the message a guest receives (spec 3.5)."""

from datetime import date
from decimal import Decimal

from lib.models import QuoteLine
from lib.quotes import days_waiting, needs_follow_up, quote_message

LINES = (
    QuoteLine("High", date(2027, 1, 1), date(2027, 1, 10), 10, Decimal("2400.00"), Decimal("24000.00")),
    QuoteLine("Medium", date(2027, 1, 11), date(2027, 1, 19), 9, Decimal("1500.00"), Decimal("13500.00")),
)


def test_a_quote_is_flagged_once_it_has_waited_a_week():
    sent = date(2027, 3, 1)

    assert not needs_follow_up("quoted", sent, date(2027, 3, 7))
    assert needs_follow_up("quoted", sent, date(2027, 3, 8))
    assert needs_follow_up("quoted", sent, date(2027, 4, 1))


def test_an_answered_quote_is_never_flagged():
    sent = date(2027, 3, 1)
    long_after = date(2027, 6, 1)

    assert not needs_follow_up("accepted", sent, long_after)
    assert not needs_follow_up("cancelled", sent, long_after)


def test_days_waiting_never_goes_negative():
    assert days_waiting(date(2027, 3, 10), date(2027, 3, 1)) == 0
    assert days_waiting(date(2027, 3, 1), date(2027, 3, 10)) == 9


def test_the_message_shows_how_the_price_was_built_up():
    message = quote_message(
        "Seaview 3", "M. Abrahams", date(2027, 1, 1), date(2027, 1, 20),
        LINES, Decimal("37500.00"), guests=4, reference=17,
    )

    assert "Hi M. Abrahams," in message
    assert "Seaview 3" in message
    assert "Nights: 19" in message
    assert "Guests: 4" in message
    # One line per season touched, with the rate visible, then the total.
    assert "10 x R2 400.00 (High season) = R24 000.00" in message
    assert "9 x R1 500.00 (Medium season) = R13 500.00" in message
    assert "Total: R37 500.00" in message
    assert "Quote reference: 17" in message


def test_a_single_night_line_reads_as_one_date_not_a_range():
    line = QuoteLine("Low", date(2027, 5, 1), date(2027, 5, 1), 1, Decimal("900.00"), Decimal("900.00"))

    message = quote_message(
        "Milkwood 7", "D. Fourie", date(2027, 5, 1), date(2027, 5, 2),
        (line,), Decimal("900.00"),
    )

    assert "01 May  1 x R900.00" in message
    assert " - " not in message.split("Price:")[1].split("Total:")[0]


def test_guests_are_left_out_when_not_recorded():
    message = quote_message(
        "Seaview 3", "H. Steyn", date(2027, 1, 1), date(2027, 1, 3),
        LINES[:1], Decimal("24000.00"),
    )

    assert "Guests:" not in message
