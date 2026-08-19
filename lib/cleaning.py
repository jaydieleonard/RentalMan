"""Working out which cleans a unit needs, and when (spec 3.9, 3.10).

The rules are driven by the same Turnover Rule the availability search reads,
so a flat's buffer is stated once and decides both where it can be booked and
how it gets cleaned. That is the whole point of keeping this here rather than
in a page: when the two disagree, guests arrive at a flat nobody cleaned.

The shape of it:

* Buffer 0 - the normal arrangement - means one **changeover clean** on the day
  itself, between the guest leaving and the next arriving.
* Buffer 1 or more means the flat is not being turned around in a day, so the
  ordinary **post-clean** after checkout and **pre-clean** before the next
  arrival apply instead, with a clear day between them.
* A checkout with nobody following gets a **post-clean** regardless: the flat
  still needs doing, there is simply no arrival to work towards.
* A long stay gets a **light clean** partway through, and a flat gets a
  **deep clean** on its own cadence whether or not anyone is staying.

Everything here is planning only. Nothing decides that a job *happened* - that
is the parents marking it done on the cleaning calendar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable, Mapping, Sequence

from lib.availability import buffer_at
from lib.models import (
    BLOCKING_STATUSES,
    CHANGEOVER_CLEAN,
    DEEP_CLEAN,
    LIGHT_CLEAN,
    POST_CLEAN,
    PRE_CLEAN,
    Booking,
    SeasonDefinition,
    TurnoverRule,
)

ONE_DAY = timedelta(days=1)

#: A flat gets at most one clean a day - one visit, one charge to the owner.
#: Where the rules want two on the same day, the one higher up this list stays
#: put and the other is moved on. The order runs from the cleans that cannot
#: move, because a guest is arriving or leaving that day, down to the ones that
#: only have to happen eventually.
PRIORITY = (CHANGEOVER_CLEAN, POST_CLEAN, PRE_CLEAN, LIGHT_CLEAN, DEEP_CLEAN)

#: How far a displaced clean is allowed to slide before it is given up on.
MAX_DEFERRAL_DAYS = 14

#: A stay longer than this gets a mid-stay tidy, one every LIGHT_CLEAN_EVERY
#: nights after that. Both are defaults the parents can move per unit.
LIGHT_CLEAN_AFTER_NIGHTS = 10
LIGHT_CLEAN_EVERY = 7

#: How often a flat gets a deep clean when nothing says otherwise - quarterly.
DEEP_CLEAN_EVERY_DAYS = 91


@dataclass(frozen=True)
class PlannedJob:
    """A clean the rules say is needed, before anyone has agreed to do it."""

    unit_id: int
    date: date
    service_label: str
    booking_id: int | None = None
    #: Why this job exists, in words - shown when the parents review what was
    #: generated, so a surprising job can be understood rather than guessed at.
    reason: str = ""

    @property
    def key(self) -> tuple[int, date, str]:
        """What makes two jobs the same job, for not scheduling one twice."""
        return (self.unit_id, self.date, self.service_label)


def _stays_for(unit_id: int, bookings: Iterable[Booking]) -> list[Booking]:
    """The stays that actually hold this flat, in date order."""
    return sorted(
        (b for b in bookings if b.unit_id == unit_id and b.status in BLOCKING_STATUSES),
        key=lambda b: b.check_in,
    )


def light_clean_dates(
    booking: Booking,
    after_nights: int = LIGHT_CLEAN_AFTER_NIGHTS,
    every: int = LIGHT_CLEAN_EVERY,
) -> list[date]:
    """Mid-stay tidies for a long stay (3.10).

    Only stays longer than `after_nights` get them, and then one every `every`
    nights - never on the arrival day, and never on the departure day, when a
    changeover or post-clean is already happening.
    """
    if booking.nights <= after_nights or every < 1:
        return []
    dates, day = [], booking.check_in + every * ONE_DAY
    while day < booking.check_out:
        dates.append(day)
        day += every * ONE_DAY
    return dates


def deep_clean_dates(
    window_start: date,
    window_end: date,
    every_days: int = DEEP_CLEAN_EVERY_DAYS,
    last_done: date | None = None,
) -> list[date]:
    """When a flat is due its next deep cleans (3.10).

    Counted from the last one actually done, so a flat cleaned late does not
    immediately fall due again. With none on record the first one lands at the
    start of the window rather than a cadence into it - a flat with no deep
    clean on file is exactly the one that needs looking at.
    """
    if every_days < 1:
        return []
    due = last_done + every_days * ONE_DAY if last_done else window_start
    dates = []
    while due < window_end:
        if due >= window_start:
            dates.append(due)
        due += every_days * ONE_DAY
    return dates


def plan_for_unit(
    unit_id: int,
    window_start: date,
    window_end: date,
    bookings: Sequence[Booking],
    rules: Sequence[TurnoverRule] = (),
    definitions: Sequence[SeasonDefinition] = (),
    light_after: int = LIGHT_CLEAN_AFTER_NIGHTS,
    light_every: int = LIGHT_CLEAN_EVERY,
    deep_every_days: int | None = DEEP_CLEAN_EVERY_DAYS,
    last_deep_clean: date | None = None,
) -> list[PlannedJob]:
    """Every clean one flat needs between two dates, in date order.

    Planning only: it says what is needed, not what has been arranged. Jobs
    already on the calendar are left alone by the caller, so a job moved or
    reassigned by hand is never quietly overwritten by the rules.
    """
    stays = _stays_for(unit_id, bookings)
    arrivals = {stay.check_in: stay for stay in stays}
    planned: list[PlannedJob] = []

    for index, stay in enumerate(stays):
        following = stays[index + 1] if index + 1 < len(stays) else None
        buffer_after = buffer_at(stay.check_out, unit_id, rules, definitions)
        same_day = (
            buffer_after == 0 and following is not None and following.check_in == stay.check_out
        )

        if same_day:
            planned.append(PlannedJob(
                unit_id, stay.check_out, CHANGEOVER_CLEAN, stay.id,
                "Guest out and the next guest in the same day",
            ))
        else:
            planned.append(PlannedJob(
                unit_id, stay.check_out, POST_CLEAN, stay.id,
                "After checkout, with no one arriving the same day",
            ))

        for day in light_clean_dates(stay, light_after, light_every):
            planned.append(PlannedJob(
                unit_id, day, LIGHT_CLEAN, stay.id,
                f"Mid-stay tidy on a {stay.nights}-night stay",
            ))

    # A pre-clean is a final check the day before someone arrives. It is not
    # wanted where the flat is being turned around on the day itself, because
    # the changeover clean is that check.
    for stay in stays:
        departing = next((s for s in stays if s.check_out == stay.check_in), None)
        turned_around_today = (
            departing is not None
            and buffer_at(stay.check_in, unit_id, rules, definitions) == 0
        )
        if not turned_around_today:
            planned.append(PlannedJob(
                unit_id, stay.check_in - ONE_DAY, PRE_CLEAN, stay.id,
                "Final check the day before the guest arrives",
            ))

    if deep_every_days:
        for day in deep_clean_dates(window_start, window_end, deep_every_days, last_deep_clean):
            planned.append(PlannedJob(
                unit_id, day, DEEP_CLEAN, None,
                "Periodic deep clean, whether or not anyone is staying",
            ))

    resolved = one_clean_per_day(planned, window_end)
    inside = [job for job in resolved if window_start <= job.date < window_end]
    return sorted(inside, key=lambda job: (job.date, job.service_label))


def one_clean_per_day(planned: Sequence[PlannedJob], window_end: date) -> list[PlannedJob]:
    """Reduce a flat's planned cleans to at most one a day.

    Two cleans on one flat on one day means sending somebody twice and charging
    the owner twice for a single visit. Where the rules ask for that - a buffer
    of exactly one night puts the post-clean and the pre-clean on the same day,
    a deep clean can fall due on a changeover - the fixed one stays and the
    other moves.

    Moved, not dropped: a mid-stay tidy or a deep clean that collides still
    needs doing, so it slides to the next free day. Only one that cannot find a
    day inside `MAX_DEFERRAL_DAYS` is given up on, and then it is the least
    urgent kind by definition, since the urgent ones never move.
    """
    order = {label: rank for rank, label in enumerate(PRIORITY)}
    taken: dict[date, PlannedJob] = {}
    displaced: list[PlannedJob] = []

    for job in sorted(planned, key=lambda j: (j.date, order.get(j.service_label, 99))):
        holder = taken.get(job.date)
        if holder is None:
            taken[job.date] = job
        elif holder.key == job.key:
            continue  # the same clean planned twice over
        else:
            displaced.append(job)

    for job in displaced:
        day = job.date + ONE_DAY
        limit = job.date + MAX_DEFERRAL_DAYS * ONE_DAY
        while day in taken and day <= limit:
            day += ONE_DAY
        if day in taken or day >= window_end:
            continue  # nowhere to put it; it will come round again next time
        taken[day] = PlannedJob(
            job.unit_id, day, job.service_label, job.booking_id,
            f"{job.reason} (moved from {job.date.isoformat()}, "
            f"the flat was already being cleaned that day)",
        )

    return list(taken.values())


def cost_for(
    unit_id: int,
    service_label: str,
    standard: Mapping[str, Decimal],
    overrides: Mapping[tuple[int, str], Decimal] | None = None,
) -> Decimal:
    """What this clean costs on this flat (3.10).

    A negotiated price for one flat wins; otherwise the standard rate for the
    service. Most flats have no override at all, which is the point - the
    exceptions are handled without every flat needing its own price list.
    """
    if overrides:
        negotiated = overrides.get((unit_id, service_label))
        if negotiated is not None:
            return negotiated
    return standard.get(service_label, Decimal("0.00"))
