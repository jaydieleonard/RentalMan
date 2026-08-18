"""Domain objects shared by the database layer, the logic modules and the pages.

These mirror the entities in spec §6. Money is `Decimal` throughout and never
`float` — these are the business's financial records, and a rounding artefact in
an owner statement is not an acceptable failure mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal

# The three season labels of the one shared season calendar (§3.3).
LOW = "Low"
MEDIUM = "Medium"
HIGH = "High"
SEASON_LABELS = (LOW, MEDIUM, HIGH)

# Booking statuses (§3.6). Only CONFIRMED occupies the calendar and blocks a
# unit; an enquiry or an unaccepted quote does not hold the dates.
ENQUIRY = "enquiry"
QUOTED = "quoted"
CONFIRMED = "confirmed"
CANCELLED = "cancelled"
BOOKING_STATUSES = (ENQUIRY, QUOTED, CONFIRMED, CANCELLED)

#: Statuses that make a unit unavailable. Kept as one constant so that a future
#: decision to have quotes pencil-hold the dates is a one-line change here
#: rather than a hunt through the availability code.
BLOCKING_STATUSES = frozenset({CONFIRMED})


@dataclass(frozen=True)
class Owner:
    """§6 Owner. Banking details are reference-only — nothing here pays anyone."""

    id: int | None
    name: str
    phone: str = ""
    email: str = ""
    banking_details: str = ""
    notes: str = ""


@dataclass(frozen=True)
class Unit:
    """§6 Unit (Flat). One owner per unit — joint ownership is out of scope."""

    id: int | None
    name: str
    beds: int
    sleeps: int
    owner_id: int | None
    monthly_management_fee: Decimal = Decimal("0.00")
    #: General minimum stay, independent of season (§3.4): 2 for most units,
    #: 1 for the one unit that takes single nights.
    min_nights: int = 2
    #: Per-unit override of the business-wide changeover window (§3.10). Blank
    #: means "use the business default", which the caller supplies.
    checkout_time: time | None = None
    checkin_time: time | None = None
    group_tag: str = ""
    notes: str = ""
    active: bool = True


@dataclass(frozen=True)
class SeasonDefinition:
    """§6 Season Definition. One shared calendar for every unit (§3.3).

    `start_date` and `end_date` are both **inclusive** — a season that runs
    "1–10 Jan" covers the night of the 10th.
    """

    id: int | None
    label: str
    start_date: date
    end_date: date
    year: int


@dataclass(frozen=True)
class ClientRate:
    """§6 Client Rate — the nightly figure charged to the guest.

    `min_nights` is the season's own minimum-night rule (§3.4), which can raise
    the bar above the unit's general minimum but never lower it. None means the
    season imposes nothing extra.
    """

    unit_id: int
    season_label: str
    year: int
    nightly_rate: Decimal
    min_nights: int | None = None


@dataclass(frozen=True)
class Client:
    """§6 Client."""

    id: int | None
    name: str
    phone: str = ""
    email: str = ""
    notes: str = ""


@dataclass(frozen=True)
class Booking:
    """§6 Booking. `check_out` is the departure date and is **not** a charged night."""

    id: int | None
    unit_id: int
    client_id: int | None
    check_in: date
    check_out: date
    status: str = ENQUIRY
    total_price: Decimal | None = None
    notes: str = ""

    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days


@dataclass(frozen=True)
class UnitBlock:
    """A stretch of nights held off the market for the unit's own reasons.

    3.1 asks the grid to show grey for "blocked/maintenance", but 6 lists no
    entity to hold it, so this fills that gap: maintenance, an owner staying in
    their own flat, a unit out of action. `end_date` is exclusive and behaves
    exactly like a booking's check-out date, so the two can be reasoned about
    together.
    """

    id: int | None
    unit_id: int
    start_date: date
    end_date: date
    reason: str = ""


@dataclass(frozen=True)
class TurnoverRule:
    """§6 Turnover Rule — how many nights must sit free around a booking.

    `season_label` of None is the unit's default across all seasons; a row with
    a label overrides it for that season only. `buffer_nights` of 0 is same-day
    turnover, which is the confirmed norm (§3.10), not the exception.
    """

    unit_id: int
    season_label: str | None
    buffer_nights: int


@dataclass(frozen=True)
class StaySegment:
    """An unbroken run of nights in one season (§3.5 step 2).

    `first_night` and `last_night` are inclusive night dates. A night belongs to
    the season covering the date it *starts* on, so a segment's `last_night` is
    the last date the guest sleeps there, not their departure date.
    """

    season_label: str
    #: Year of the season definition these nights came from - the rate version
    #: to price them at (3.4). A season running 1 Dec 2026 to 15 Jan 2027 is
    #: one definition with year 2026, so its January nights price at the 2026
    #: rate, not the 2027 one.
    season_year: int
    first_night: date
    last_night: date

    @property
    def nights(self) -> int:
        return (self.last_night - self.first_night).days + 1


@dataclass(frozen=True)
class QuoteLine:
    """One priced season segment on a quote (§3.5 output)."""

    season_label: str
    first_night: date
    last_night: date
    nights: int
    nightly_rate: Decimal
    subtotal: Decimal


@dataclass(frozen=True)
class StayQuote:
    """The full built-up price for one stay — the thing the client is shown."""

    unit_id: int
    check_in: date
    check_out: date
    nights: int
    lines: tuple[QuoteLine, ...]
    total: Decimal
