"""What has actually been paid against a statement (spec 9, Phase 6).

Phase 5 recorded settlement as a single flag: paid, or not. That cannot hold a
part payment, a bank reference, or the fact that March was settled in two
transfers three weeks apart - and those are exactly the things somebody asks
about six months later.

So payments are recorded one by one, and how much is outstanding is worked out
from them rather than remembered separately. The flag on the statement follows
the payments; the payments are never inferred from the flag.

A statement can be negative - an empty month where the management fee and the
cleaning came to more than the flat earned. That is money owed *to* the
business, so it is described that way rather than as an owner who is owed a
negative amount.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Sequence

from lib.rates import money

#: How close to zero counts as settled. Bank transfers land a cent out often
#: enough that chasing the difference costs more than it is worth.
TOLERANCE = Decimal("0.01")


@dataclass(frozen=True)
class OwnerPayment:
    """One transfer against one statement."""

    id: int | None
    statement_id: int
    paid_on: date
    amount: Decimal
    reference: str = ""
    notes: str = ""


@dataclass(frozen=True)
class Settlement:
    """Where a statement stands, given what has been paid against it."""

    due: Decimal
    paid: Decimal
    payments: int
    last_paid_on: date | None

    @property
    def outstanding(self) -> Decimal:
        return money(self.due - self.paid)

    @property
    def is_settled(self) -> bool:
        return abs(self.outstanding) <= TOLERANCE

    @property
    def is_owed_to_us(self) -> bool:
        """The month cost the owner more than the flat earned."""
        return self.due < 0

    @property
    def state(self) -> str:
        if self.is_settled:
            return "settled"
        if self.payments:
            return "part paid"
        return "owed to us" if self.is_owed_to_us else "unpaid"

    def describe(self) -> str:
        if self.is_settled:
            when = f" on {self.last_paid_on.strftime('%d %B %Y')}" if self.last_paid_on else ""
            if not self.payments:
                return "Nothing to pay."
            once = "in one payment" if self.payments == 1 else f"in {self.payments} payments"
            return f"Settled {once}{when}."
        if self.is_owed_to_us and not self.payments:
            return "The month cost more than the flat earned - this is owed to the business."
        if self.payments:
            return f"{self.payments} payment(s) so far; still outstanding."
        return "Not paid yet."


def settle(due: Decimal, payments: Sequence[OwnerPayment]) -> Settlement:
    """Add up what has been paid against a statement."""
    return Settlement(
        due=money(due),
        paid=money(sum((payment.amount for payment in payments), Decimal("0.00"))),
        payments=len(payments),
        last_paid_on=max((payment.paid_on for payment in payments), default=None),
    )
