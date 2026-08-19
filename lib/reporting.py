"""Occupancy and revenue, per flat, per owner and per season (spec 9, Phase 6).

Reporting has one job here: to answer questions the parents can act on. Which
flats earn their keep, which sit empty, whether high season is worth what it
charges. So the figures are the ones they already have - nights actually slept
and money actually charged - rather than a model of them.

Two things are worth knowing about how the numbers are built:

* **Nights are clipped to the period.** A stay straddling the boundary counts
  only the nights inside it, the same way an owner statement works, so two
  adjoining periods add up to the whole rather than double-counting the stay.
* **Revenue is apportioned, not recalculated.** A booking's own total is the
  money that changed hands; splitting it across seasons is done in proportion
  to what each segment was worth, so the parts always sum back to the total
  even when the guest was charged something other than the rate file says.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Mapping, Sequence

from lib.availability import BLOCKED, OPEN, occupancy
from lib.models import BLOCKING_STATUSES, Booking, SeasonDefinition, Unit, UnitBlock
from lib.rates import money
from lib.seasons import SeasonCalendarError, segment_stay

ONE_DAY = timedelta(days=1)


def clipped_nights(booking: Booking, start: date, end: date) -> tuple[date, date] | None:
    """The part of a stay inside [start, end), or None if none of it is."""
    first = max(booking.check_in, start)
    last = min(booking.check_out, end)
    return (first, last) if last > first else None


def apportion(total: Decimal, weights: Sequence[Decimal]) -> list[Decimal]:
    """Split `total` across `weights` so the parts sum exactly back to it.

    Rounding each share on its own loses or invents a cent or two, which on a
    revenue report means the seasons never quite add up to the year. The
    largest remainders take the difference instead.
    """
    if not weights:
        return []
    weighed = sum(weights)
    if weighed <= 0:
        even = money(total / len(weights))
        shares = [even] * len(weights)
        shares[-1] = money(total - even * (len(weights) - 1))
        return shares

    exact = [total * weight / weighed for weight in weights]
    shares = [money(value) for value in exact]
    drift = money(total - sum(shares))
    if drift:
        # Hand the odd cents to whichever shares were rounded down hardest.
        order = sorted(range(len(shares)), key=lambda i: exact[i] - shares[i], reverse=drift > 0)
        step = Decimal("0.01") if drift > 0 else Decimal("-0.01")
        for index in order[: int(abs(drift) / Decimal("0.01"))]:
            shares[index] = money(shares[index] + step)
    return shares


@dataclass(frozen=True)
class UnitPerformance:
    """How one flat did over a period."""

    unit_id: int
    unit_name: str
    owner_id: int | None
    nights_available: int
    nights_let: int
    nights_blocked: int
    revenue: Decimal
    stays: int

    @property
    def occupancy(self) -> float:
        """Let nights as a share of the nights it could have been let.

        Blocked nights come out of the denominator: a flat off the market for
        repairs was not empty for want of a guest, and counting those against
        it would make maintenance look like a sales problem.
        """
        sellable = self.nights_available - self.nights_blocked
        return self.nights_let / sellable if sellable > 0 else 0.0

    @property
    def revenue_per_available_night(self) -> Decimal:
        sellable = self.nights_available - self.nights_blocked
        return money(self.revenue / sellable) if sellable > 0 else Decimal("0.00")


@dataclass(frozen=True)
class SeasonPerformance:
    """How one season did, across whichever flats are in the report."""

    season_label: str
    nights_let: int
    revenue: Decimal

    @property
    def average_nightly(self) -> Decimal:
        return money(self.revenue / self.nights_let) if self.nights_let else Decimal("0.00")


@dataclass(frozen=True)
class Report:
    """Everything the reporting page shows, worked out once."""

    start: date
    end: date
    units: tuple[UnitPerformance, ...]
    seasons: tuple[SeasonPerformance, ...]
    #: Nights that could not be attributed to a season, which means the season
    #: calendar has a hole in it. Reported rather than silently dropped.
    unattributed_nights: int = 0

    @property
    def nights_let(self) -> int:
        return sum(unit.nights_let for unit in self.units)

    @property
    def nights_available(self) -> int:
        return sum(unit.nights_available - unit.nights_blocked for unit in self.units)

    @property
    def revenue(self) -> Decimal:
        return money(sum((unit.revenue for unit in self.units), Decimal("0.00")))

    @property
    def occupancy(self) -> float:
        return self.nights_let / self.nights_available if self.nights_available else 0.0

    def by_owner(self, owners: Mapping[int, str]) -> list[tuple[str, int, Decimal, float]]:
        """Name, let nights, revenue and occupancy for each owner in the report."""
        grouped: dict[int | None, list[UnitPerformance]] = {}
        for unit in self.units:
            grouped.setdefault(unit.owner_id, []).append(unit)

        rows = []
        for owner_id, theirs in grouped.items():
            let = sum(unit.nights_let for unit in theirs)
            sellable = sum(unit.nights_available - unit.nights_blocked for unit in theirs)
            rows.append((
                owners.get(owner_id, "Unknown owner"),
                let,
                money(sum((unit.revenue for unit in theirs), Decimal("0.00"))),
                let / sellable if sellable else 0.0,
            ))
        return sorted(rows, key=lambda row: row[2], reverse=True)


def build_report(
    units: Sequence[Unit],
    start: date,
    end: date,
    bookings: Sequence[Booking],
    definitions: Sequence[SeasonDefinition] = (),
    blocks: Sequence[UnitBlock] = (),
) -> Report:
    """Occupancy and revenue for every flat between two dates (end exclusive)."""
    total_nights = (end - start).days
    performances: list[UnitPerformance] = []
    season_nights: dict[str, int] = {}
    season_revenue: dict[str, Decimal] = {}
    unattributed = 0

    for unit in units:
        let_nights = 0
        revenue = Decimal("0.00")
        stays = 0

        for booking in bookings:
            if booking.unit_id != unit.id or booking.status not in BLOCKING_STATUSES:
                continue
            window = clipped_nights(booking, start, end)
            if window is None:
                continue
            first, last = window
            nights = (last - first).days
            let_nights += nights
            stays += 1

            # The money that actually changed hands, scaled to the part of the
            # stay inside the period - a stay half in and half out of a month
            # should not put its whole value in either.
            whole = booking.nights or 1
            share = money((booking.total_price or Decimal("0.00")) * nights / whole)
            revenue += share

            try:
                segments = segment_stay(definitions, first, last)
            except SeasonCalendarError:
                unattributed += nights
                continue

            weights = [Decimal(segment.nights) for segment in segments]
            for segment, part in zip(segments, apportion(share, weights)):
                season_nights[segment.season_label] = (
                    season_nights.get(segment.season_label, 0) + segment.nights
                )
                season_revenue[segment.season_label] = money(
                    season_revenue.get(segment.season_label, Decimal("0.00")) + part
                )

        nights_map = occupancy(unit.id, start, end, [], (), definitions, blocks)
        blocked = sum(1 for cell in nights_map.values() if cell.status == BLOCKED)

        performances.append(UnitPerformance(
            unit_id=unit.id,
            unit_name=unit.name,
            owner_id=unit.owner_id,
            nights_available=total_nights,
            nights_let=let_nights,
            nights_blocked=blocked,
            revenue=money(revenue),
            stays=stays,
        ))

    seasons = tuple(
        SeasonPerformance(label, nights, season_revenue.get(label, Decimal("0.00")))
        for label, nights in sorted(season_nights.items(), key=lambda item: -item[1])
    )
    return Report(
        start=start,
        end=end,
        units=tuple(sorted(performances, key=lambda p: p.revenue, reverse=True)),
        seasons=seasons,
        unattributed_nights=unattributed,
    )
