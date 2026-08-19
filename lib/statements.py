"""What each owner is owed for a month (spec 3.8).

Three figures per flat, and they must never be confused with one another:

* **rental income** - the nights actually slept that month, valued at the
  *owner* rate for whatever season each night falls in. Not the client rate:
  what the guest paid and what the owner is due are set independently;
* **less the management fee** - a flat monthly amount for looking after the
  flat, the same whether it was full or empty all month;
* **less cleaning** - what the cleans done on that flat that month cost.

The nights are clipped to the month before they are priced, so a stay running
from the 28th to the 3rd puts three nights on one statement and two on the
next, rather than the whole stay landing on whichever month it started in.

The season segmenting is the same code the client quote uses, pointed at the
owner rate table instead - which is the whole reason it lives in lib/rates.py
rather than inside a quote screen.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable, Sequence

from lib.models import (
    BLOCKING_STATUSES,
    DONE,
    Booking,
    CleaningJob,
    ClientRate,
    OwnerRate,
    QuoteLine,
    SeasonDefinition,
    Unit,
)
from lib.rates import money, price_segments
from lib.seasons import SeasonCalendarError, segment_stay


def month_bounds(year: int, month: int) -> tuple[date, date]:
    """First day of the month, and the first day of the next - end exclusive."""
    start = date(year, month, 1)
    return start, date(year + (month == 12), month % 12 + 1, 1)


@dataclass(frozen=True)
class StayShare:
    """One stay's contribution to one month."""

    booking_id: int | None
    check_in: date
    check_out: date
    nights_in_month: int
    lines: tuple[QuoteLine, ...]
    income: Decimal


@dataclass(frozen=True)
class UnitStatement:
    """One flat's part of an owner's month."""

    unit_id: int
    unit_name: str
    nights: int
    rental_income: Decimal
    management_fee: Decimal
    cleaning_cost: Decimal
    stays: tuple[StayShare, ...] = ()
    cleans: tuple[CleaningJob, ...] = ()
    #: Anything that stopped a figure being worked out - a missing owner rate,
    #: a night no season covers. Reported rather than quietly costed at zero.
    problems: tuple[str, ...] = ()

    @property
    def net(self) -> Decimal:
        return money(self.rental_income - self.management_fee - self.cleaning_cost)


@dataclass(frozen=True)
class OwnerStatement:
    """What one owner is owed for one month, across all their flats."""

    owner_id: int
    year: int
    month: int
    units: tuple[UnitStatement, ...]

    @property
    def rental_income(self) -> Decimal:
        return money(sum((u.rental_income for u in self.units), Decimal("0.00")))

    @property
    def management_fees(self) -> Decimal:
        return money(sum((u.management_fee for u in self.units), Decimal("0.00")))

    @property
    def cleaning_costs(self) -> Decimal:
        return money(sum((u.cleaning_cost for u in self.units), Decimal("0.00")))

    @property
    def net(self) -> Decimal:
        return money(self.rental_income - self.management_fees - self.cleaning_costs)

    @property
    def period_name(self) -> str:
        return f"{calendar.month_name[self.month]} {self.year}"

    @property
    def problems(self) -> tuple[str, ...]:
        return tuple(problem for unit in self.units for problem in unit.problems)


def _as_client_rates(
    owner_rates: Iterable[OwnerRate], unit_id: int
) -> dict[tuple[str, int], ClientRate]:
    """Present one flat's owner rates in the shape the pricing code expects.

    The arithmetic is identical - nights times a nightly figure, per season -
    so it is the same function with a different rate table behind it, not a
    second copy of the calculation drifting away from the first.

    Filtered to the flat here rather than trusting the caller to have done it:
    the lookup is keyed on season and year, so another flat's rate for the same
    season would otherwise sit in the same slot and quietly price these nights.
    """
    return {
        (rate.season_label, rate.year): ClientRate(
            rate.unit_id, rate.season_label, rate.year, rate.nightly_rate, None
        )
        for rate in owner_rates
        if rate.unit_id == unit_id
    }


def stay_share(
    booking: Booking,
    month_start: date,
    month_end: date,
    definitions: Sequence[SeasonDefinition],
    owner_rates: Iterable[OwnerRate],
) -> StayShare | None:
    """The part of one stay that belongs to this month, priced at owner rates.

    Returns None when the stay puts no nights in the month at all. Raises
    whatever the pricing raises - a missing rate is worth stopping for, since
    the alternative is an owner quietly paid nothing for a fortnight.
    """
    first_night = max(booking.check_in, month_start)
    last_departure = min(booking.check_out, month_end)
    if last_departure <= first_night:
        return None

    segments = segment_stay(definitions, first_night, last_departure)
    priced = price_segments(
        booking.unit_id, first_night, last_departure, segments,
        _as_client_rates(owner_rates, booking.unit_id),
    )
    return StayShare(
        booking_id=booking.id,
        check_in=first_night,
        check_out=last_departure,
        nights_in_month=priced.nights,
        lines=priced.lines,
        income=priced.total,
    )


def unit_statement(
    unit: Unit,
    year: int,
    month: int,
    bookings: Sequence[Booking],
    owner_rates: Iterable[OwnerRate],
    definitions: Sequence[SeasonDefinition],
    cleaning_jobs: Sequence[CleaningJob] = (),
) -> UnitStatement:
    """One flat's income, fee and cleaning for one month.

    Only stays that actually held the flat count, and only cleans marked done -
    a job still sitting as scheduled has not been carried out, and billing an
    owner for it would be charging for work nobody has done yet.
    """
    month_start, month_end = month_bounds(year, month)
    owner_rates = list(owner_rates)
    shares: list[StayShare] = []
    problems: list[str] = []

    for booking in sorted(bookings, key=lambda b: b.check_in):
        if booking.unit_id != unit.id or booking.status not in BLOCKING_STATUSES:
            continue
        try:
            share = stay_share(booking, month_start, month_end, definitions, owner_rates)
        except SeasonCalendarError as problem:
            problems.append(f"{unit.name}: {problem}")
            continue
        except Exception as problem:
            problems.append(f"{unit.name}: {problem}")
            continue
        if share is not None:
            shares.append(share)

    cleans = tuple(
        job for job in cleaning_jobs
        if job.unit_id == unit.id and job.status == DONE and month_start <= job.date < month_end
    )

    return UnitStatement(
        unit_id=unit.id,
        unit_name=unit.name,
        nights=sum(share.nights_in_month for share in shares),
        rental_income=money(sum((share.income for share in shares), Decimal("0.00"))),
        management_fee=money(unit.monthly_management_fee),
        cleaning_cost=money(sum((job.cost for job in cleans), Decimal("0.00"))),
        stays=tuple(shares),
        cleans=cleans,
        problems=tuple(problems),
    )


def build_statement(
    owner_id: int,
    units: Sequence[Unit],
    year: int,
    month: int,
    bookings: Sequence[Booking],
    owner_rates: Sequence[OwnerRate],
    definitions: Sequence[SeasonDefinition],
    cleaning_jobs: Sequence[CleaningJob] = (),
) -> OwnerStatement:
    """One owner's month, itemised per flat (3.8).

    Every flat the owner has appears, including one that stood empty: the
    management fee is due on it either way, and an owner seeing a flat missing
    from their statement has no way of telling that from an oversight.
    """
    theirs = [unit for unit in units if unit.owner_id == owner_id]
    return OwnerStatement(
        owner_id=owner_id,
        year=year,
        month=month,
        units=tuple(
            unit_statement(
                unit, year, month, bookings,
                [rate for rate in owner_rates if rate.unit_id == unit.id],
                definitions, cleaning_jobs,
            )
            for unit in sorted(theirs, key=lambda u: u.name)
        ),
    )
