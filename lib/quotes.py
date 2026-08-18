"""What happens to a quote after it is priced (spec 3.5).

The pricing itself is in lib.rates; this covers the two things the spec asks
for once a price exists - the message the guest actually receives, and the
follow-up flag that stops an enquiry going quietly cold.

Both are pure functions over plain values so the wording can be tested and
changed without touching a screen or a database.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Sequence

from lib.models import QUOTE_OPEN, QuoteLine

#: A quote still sitting unanswered this many days after it was sent gets
#: flagged for a nudge. A reminder only - it never expires or cancels anything.
FOLLOW_UP_DAYS = 7


def needs_follow_up(status: str, generated_on: date, today: date) -> bool:
    """Has this quote been waiting long enough to deserve a chase?"""
    if status != QUOTE_OPEN:
        return False
    return (today - generated_on) >= timedelta(days=FOLLOW_UP_DAYS)


def days_waiting(generated_on: date, today: date) -> int:
    return max(0, (today - generated_on).days)


def format_money(amount: Decimal, currency: str = "R") -> str:
    return f"{currency}{Decimal(amount):,.2f}".replace(",", " ")


def quote_message(
    unit_name: str,
    client_name: str,
    check_in: date,
    check_out: date,
    lines: Sequence[QuoteLine],
    total: Decimal,
    guests: int | None = None,
    currency: str = "R",
    reference: int | None = None,
) -> str:
    """The quote as a block of text, ready to paste into WhatsApp or an email.

    Written to be read on a phone: no table alignment that collapses on a
    narrow screen, and the build-up shown line by line so the guest can see
    where the number comes from rather than being handed a lump sum.
    """
    nights = (check_out - check_in).days
    parts = [
        f"Hi {client_name},",
        "",
        f"Here is the quote for {unit_name}:",
        "",
        f"Arrive: {check_in.strftime('%a %d %B %Y')}",
        f"Depart: {check_out.strftime('%a %d %B %Y')}",
        f"Nights: {nights}",
    ]
    if guests:
        parts.append(f"Guests: {guests}")

    parts.extend(["", "Price:"])
    for line in lines:
        span = (
            line.first_night.strftime("%d %b")
            if line.nights == 1
            else f"{line.first_night.strftime('%d %b')} - {line.last_night.strftime('%d %b')}"
        )
        parts.append(
            f"  {span}  {line.nights} x {format_money(line.nightly_rate, currency)} "
            f"({line.season_label} season) = {format_money(line.subtotal, currency)}"
        )

    parts.extend(["", f"Total: {format_money(total, currency)}", ""])
    if reference:
        parts.append(f"Quote reference: {reference}")
    parts.append("Let us know if you would like to go ahead and we will hold the dates.")
    return "\n".join(parts)
