"""Turnover buffers, what blocks a unit, and whether a stay can be taken.

Spec 3.2 and 3.10. The point of putting this in one module is that the
availability search and the cleaning-job rules must never disagree: a unit's
turnover policy is stated once, as a Turnover Rule, and both read it from here.

Same-day turnover is the norm, not the exception (3.10): guest out in the
morning, changeover clean at midday, next guest in that afternoon. So the
default buffer is 0 nights and a unit needing a clear day is the special case.

One rule the spec implies but does not spell out: when a unit's buffer differs
by season, the buffer around a given boundary is taken from the season covering
**that boundary date** - the checkout date for the gap after a stay, the
check-in date for the gap before one. That matches why the rule exists (how
much cleaning capacity there is on the turnover day itself), and it means a
stay running out of high season into low is not held to high season's buffer
for a changeover that actually happens in low season.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Sequence

from lib.models import BLOCKING_STATUSES, Booking, SeasonDefinition, TurnoverRule, UnitBlock
from lib.seasons import season_for_date

ONE_DAY = timedelta(days=1)

#: What a given night is doing, in the order a grid cell should prefer to show
#: it if two apply at once.
BOOKED = "booked"
BLOCKED = "blocked"
BUFFER = "buffer"
OPEN = "open"

#: The business-wide fallback when a unit has no turnover rule on file at all.
DEFAULT_BUFFER_NIGHTS = 0


@dataclass(frozen=True)
class Occupancy:
    """What one night of one unit is doing, and why."""

    status: str
    booking_id: int | None = None
    label: str = ""


@dataclass(frozen=True)
class AvailabilityResult:
    """Whether a stay can be taken, and if not, which nights are in the way."""

    available: bool
    blocked_nights: tuple[date, ...] = ()
    reason: str = ""
    #: What kind of clash it is - BOOKED, BLOCKED or BUFFER - so a caller can
    #: treat them differently. Capturing a stay that already happened over what
    #: is now a turnover gap is worth a warning; putting one guest on top of
    #: another never is.
    kind: str = ""


def buffer_nights_for(
    rules: Iterable[TurnoverRule], unit_id: int, season_label: str | None
) -> int:
    """How many nights must sit free either side of a stay on this unit.

    A rule naming the season wins; otherwise the unit's all-seasons rule; and
    with neither on file, same-day turnover, which is the confirmed default.
    """
    unit_default: int | None = None
    for rule in rules:
        if rule.unit_id != unit_id:
            continue
        if rule.season_label is None:
            unit_default = rule.buffer_nights
        elif season_label is not None and rule.season_label == season_label:
            return rule.buffer_nights
    return unit_default if unit_default is not None else DEFAULT_BUFFER_NIGHTS


def _buffer_at(
    boundary: date,
    unit_id: int,
    rules: Iterable[TurnoverRule],
    definitions: Iterable[SeasonDefinition],
) -> int:
    """Buffer applying at one boundary date, per the season covering that date."""
    return buffer_nights_for(rules, unit_id, season_for_date(definitions, boundary))


def nights_held_by(
    booking: Booking,
    rules: Iterable[TurnoverRule],
    definitions: Iterable[SeasonDefinition],
) -> dict[date, str]:
    """Every night this booking takes out of circulation, and in what capacity.

    The stay's own nights are BOOKED. On top of those, `buffer` nights before
    check-in and after check-out are BUFFER - held free so the unit can be
    turned around, and shown as unavailable on the grid rather than looking
    like a bookable gap (3.10).

    Because the buffer belongs to the unit and season rather than to the
    booking, working it out from each existing booking is enough: a new stay
    that would land next door is caught by the neighbour's own buffer, so there
    is nothing to double-count.
    """
    held: dict[date, str] = {}

    before = _buffer_at(booking.check_in, booking.unit_id, rules, definitions)
    for step in range(1, before + 1):
        held[booking.check_in - step * ONE_DAY] = BUFFER

    after = _buffer_at(booking.check_out, booking.unit_id, rules, definitions)
    for step in range(after):
        held[booking.check_out + step * ONE_DAY] = BUFFER

    night = booking.check_in
    while night < booking.check_out:
        held[night] = BOOKED
        night += ONE_DAY

    return held


def occupancy(
    unit_id: int,
    start: date,
    end: date,
    bookings: Sequence[Booking],
    rules: Sequence[TurnoverRule] = (),
    definitions: Sequence[SeasonDefinition] = (),
    blocks: Sequence[UnitBlock] = (),
) -> dict[date, Occupancy]:
    """What each night from start to end (exclusive) is doing for one unit.

    Only confirmed bookings hold dates (see BLOCKING_STATUSES) - an enquiry or
    an unaccepted quote does not take the flat off the market.
    """
    result: dict[date, Occupancy] = {}

    for booking in bookings:
        if booking.unit_id != unit_id or booking.status not in BLOCKING_STATUSES:
            continue
        for night, status in nights_held_by(booking, rules, definitions).items():
            if start <= night < end:
                existing = result.get(night)
                # A booked night beats a neighbour's buffer night: if two
                # stays are tight against each other the cell is booked.
                if existing is None or (existing.status == BUFFER and status == BOOKED):
                    result[night] = Occupancy(status, booking.id)

    for block in blocks:
        if block.unit_id != unit_id:
            continue
        night = max(block.start_date, start)
        while night < min(block.end_date, end):
            if result.get(night, Occupancy(OPEN)).status != BOOKED:
                result[night] = Occupancy(BLOCKED, label=block.reason)
            night += ONE_DAY

    night = start
    while night < end:
        result.setdefault(night, Occupancy(OPEN))
        night += ONE_DAY

    return result


def is_available(
    unit_id: int,
    check_in: date,
    check_out: date,
    bookings: Sequence[Booking],
    rules: Sequence[TurnoverRule] = (),
    definitions: Sequence[SeasonDefinition] = (),
    blocks: Sequence[UnitBlock] = (),
    ignore_booking_id: int | None = None,
) -> AvailabilityResult:
    """Is this unit free for the whole requested stay, buffers included (3.2)?

    `ignore_booking_id` lets an existing booking be re-checked when its dates
    are edited, without it blocking itself.
    """
    if check_out <= check_in:
        return AvailabilityResult(False, (), "Check-out must be after check-in.")

    considered = [b for b in bookings if b.id is None or b.id != ignore_booking_id]
    nights = occupancy(unit_id, check_in, check_out, considered, rules, definitions, blocks)
    clashes = tuple(sorted(night for night, cell in nights.items() if cell.status != OPEN))

    if not clashes:
        return AvailabilityResult(True)

    statuses = {nights[night].status for night in clashes}
    if BOOKED in statuses:
        kind, reason = BOOKED, "The unit is already booked for part of these dates."
    elif BLOCKED in statuses:
        kind, reason = BLOCKED, "The unit is blocked for part of these dates."
    else:
        kind = BUFFER
        reason = "These dates are inside the turnover gap this unit needs between guests."
    return AvailabilityResult(False, clashes, reason, kind)
