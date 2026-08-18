"""Pricing a stay, and the minimum-stay rules that gate it (spec 3.4, 3.5).

The client quote and the owner's rental income are the same arithmetic over the
same segments, differing only in which rate table is read (3.8), so the pricing
here takes a rate lookup rather than reaching for one itself. When Phase 5 adds
owner rates it reuses price_segments unchanged.

Rates are keyed by (season label, year). The year is the one on the season
definition the nights came from, so a season running 1 Dec into 15 Jan prices
its January nights at the rate version filed under the December year - see
StaySegment.season_year.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Mapping, Sequence

from lib.models import ClientRate, QuoteLine, SeasonDefinition, StaySegment, StayQuote, Unit
from lib.seasons import segment_stay

PENNY = Decimal("0.01")


class PricingError(Exception):
    """Base class for anything that stops a stay being priced."""


class MissingRateError(PricingError):
    """No rate is on file for a season the stay actually touches."""

    def __init__(self, season_label: str, year: int, unit_id: int | None = None):
        self.season_label = season_label
        self.year = year
        self.unit_id = unit_id
        super().__init__(
            f"No {year} {season_label}-season rate is set for this unit, and the stay "
            f"includes {season_label}-season nights. Add the rate on the Units page first."
        )


class MinimumStayError(PricingError):
    """The stay is shorter than the governing minimum (3.5 step 5)."""

    def __init__(self, requested_nights: int, check: "MinimumStayCheck"):
        self.requested_nights = requested_nights
        self.check = check
        super().__init__(
            f"This stay is {requested_nights} night(s), but {check.explain()}"
        )


def money(amount: Decimal) -> Decimal:
    """Round to whole cents, half up - the way a person totalling an invoice would."""
    return Decimal(amount).quantize(PENNY, rounding=ROUND_HALF_UP)


def index_rates(rates: Iterable[ClientRate]) -> dict[tuple[str, int], ClientRate]:
    """Key a unit's rate rows by (season label, year) for lookup by segment."""
    return {(rate.season_label, rate.year): rate for rate in rates}


def rate_for_segment(
    rate_index: Mapping[tuple[str, int], ClientRate], segment: StaySegment
) -> ClientRate:
    """Find the rate row that prices this segment, or say precisely what is missing."""
    try:
        return rate_index[(segment.season_label, segment.season_year)]
    except KeyError:
        raise MissingRateError(segment.season_label, segment.season_year) from None


def price_segments(
    unit_id: int,
    check_in: date,
    check_out: date,
    segments: Sequence[StaySegment],
    rate_index: Mapping[tuple[str, int], ClientRate],
) -> StayQuote:
    """Multiply each segment out and sum, giving the built-up total (3.5 steps 3-4).

    The per-segment lines are kept, not just the total: the client is shown how
    the price was arrived at, one line per season touched.
    """
    lines: list[QuoteLine] = []
    total = Decimal("0.00")
    for segment in segments:
        rate = rate_for_segment(rate_index, segment)
        subtotal = money(rate.nightly_rate * segment.nights)
        lines.append(
            QuoteLine(
                season_label=segment.season_label,
                first_night=segment.first_night,
                last_night=segment.last_night,
                nights=segment.nights,
                nightly_rate=money(rate.nightly_rate),
                subtotal=subtotal,
            )
        )
        total += subtotal

    return StayQuote(
        unit_id=unit_id,
        check_in=check_in,
        check_out=check_out,
        nights=sum(segment.nights for segment in segments),
        lines=tuple(lines),
        total=money(total),
    )


@dataclass(frozen=True)
class MinimumStayCheck:
    """How long this stay has to be, and which rule is doing the demanding."""

    required_nights: int
    unit_minimum: int
    season_minimum: int | None
    #: The highest-rated season the stay touches - the one whose own minimum
    #: governs a multi-season stay (3.5 step 5).
    governing_season: str | None
    #: "unit" or "season" - which of the two set the bar, for the message shown.
    source: str

    def satisfied_by(self, nights: int) -> bool:
        return nights >= self.required_nights

    def explain(self) -> str:
        if self.source == "season":
            return (
                f"{self.governing_season} season requires a minimum of "
                f"{self.required_nights} nights."
            )
        return f"this unit has a minimum stay of {self.required_nights} nights."


def minimum_stay_for(
    segments: Sequence[StaySegment],
    rate_index: Mapping[tuple[str, int], ClientRate],
    unit_minimum: int,
) -> MinimumStayCheck:
    """Work out the governing minimum for a stay (3.5 step 5).

    The unit's own minimum always applies. On top of that, a season can carry
    its own minimum - and where a stay spans several seasons it is the
    **highest-rated** season touched whose minimum governs, not the longest or
    the last. A stay dipping from high into medium is still held to high
    season's rule. Where two seasons touched share the top rate, the stricter of
    their minimums wins, since neither has a claim to be the lesser rule.
    """
    top_rate: Decimal | None = None
    governing_season: str | None = None
    season_minimum: int | None = None

    for segment in segments:
        rate = rate_for_segment(rate_index, segment)
        if top_rate is None or rate.nightly_rate > top_rate:
            top_rate = rate.nightly_rate
            governing_season = segment.season_label
            season_minimum = rate.min_nights
        elif rate.nightly_rate == top_rate and rate.min_nights is not None:
            if season_minimum is None or rate.min_nights > season_minimum:
                governing_season = segment.season_label
                season_minimum = rate.min_nights

    required = unit_minimum
    source = "unit"
    if season_minimum is not None and season_minimum > required:
        required = season_minimum
        source = "season"

    return MinimumStayCheck(
        required_nights=required,
        unit_minimum=unit_minimum,
        season_minimum=season_minimum,
        governing_season=governing_season,
        source=source,
    )


def build_quote(
    unit: Unit,
    definitions: Iterable[SeasonDefinition],
    rates: Iterable[ClientRate],
    check_in: date,
    check_out: date,
) -> StayQuote:
    """Run the whole of 3.5 for one stay: segment, check the minimum, price it.

    Raises UnpricedNightError (a night no season covers), MissingRateError (a
    season touched with no rate on file) or MinimumStayError (too short) rather
    than returning a quote that would be wrong or shouldn't be offered.
    """
    segments = segment_stay(definitions, check_in, check_out)
    rate_index = index_rates(rates)

    nights = sum(segment.nights for segment in segments)
    check = minimum_stay_for(segments, rate_index, unit.min_nights)
    if not check.satisfied_by(nights):
        raise MinimumStayError(nights, check)

    quote = price_segments(unit.id, check_in, check_out, segments, rate_index)
    return quote
