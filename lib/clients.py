"""What a guest's history adds up to (spec 3.6).

The point of keeping client records at all is the repeat guest: knowing that
the family asking about March stayed twice last year, and what they paid, is
the difference between a quote and a conversation. This works that out from
the bookings and quotes already on file - nothing is stored twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Sequence

from lib.models import CANCELLED, CONFIRMED, QUOTE_OPEN, Booking, SavedQuote


@dataclass(frozen=True)
class ClientHistory:
    """One guest, summed up."""

    stays: int
    nights: int
    spent: Decimal
    cancelled: int
    open_quotes: int
    first_stay: date | None
    last_stay: date | None
    next_stay: date | None

    @property
    def is_repeat_guest(self) -> bool:
        return self.stays > 1

    def describe(self, today: date) -> str:
        """A sentence for the top of the record, rather than a row of figures."""
        if not self.stays:
            return "No stays yet."
        times = "once" if self.stays == 1 else f"{self.stays} times"
        sentence = f"Stayed {times}, {self.nights} night(s) in total."
        if self.last_stay and self.last_stay < today:
            sentence += f" Last here {self.last_stay.strftime('%B %Y')}."
        if self.next_stay:
            sentence += f" Booked again from {self.next_stay.strftime('%d %B %Y')}."
        return sentence


def summarise(
    bookings: Sequence[Booking],
    quotes: Sequence[SavedQuote] = (),
    today: date | None = None,
) -> ClientHistory:
    """Total up one guest's bookings and quotes.

    Only confirmed stays count towards nights and spend - an enquiry that never
    became anything is not a visit, and counting it would make a guest look
    more loyal than they are.
    """
    today = today or date.today()
    confirmed = [b for b in bookings if b.status == CONFIRMED]
    past = [b for b in confirmed if b.check_out <= today]
    upcoming = sorted(b.check_in for b in confirmed if b.check_out > today)

    return ClientHistory(
        stays=len(confirmed),
        nights=sum(b.nights for b in confirmed),
        spent=sum((b.total_price or Decimal("0.00") for b in confirmed), Decimal("0.00")),
        cancelled=sum(1 for b in bookings if b.status == CANCELLED),
        open_quotes=sum(1 for q in quotes if q.status == QUOTE_OPEN),
        first_stay=min((b.check_in for b in confirmed), default=None),
        last_stay=max((b.check_out for b in past), default=None),
        next_stay=upcoming[0] if upcoming else None,
    )
