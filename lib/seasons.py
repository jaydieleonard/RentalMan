"""The shared season calendar, and splitting a stay across it (spec 3.3, 3.5).

This is the single most load-bearing calculation in the app: the same
segmenting drives the client quote (3.5) and the owner's monthly statement
(3.8), which is exactly why it lives here once instead of being written twice.

Two rules decided in the spec and applied throughout:

* A season's start_date and end_date are both **inclusive**.
* A night belongs to the season covering the date that night *starts* on. So a
  stay of 1-20 January against High = 1-10 Jan and Medium = 11-20 Jan is 19
  chargeable nights: 10 high (nights of 1-10 Jan) and 9 medium (nights of
  11-19 Jan). The check-out date is never a charged night.

A SeasonDefinition.year is a grouping tag for the year-by-year editor, not
part of the lookup - matching is done on the actual dates, so a season that
runs 1 Dec into 15 Jan crosses the year boundary without special handling.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Iterable, Iterator, Sequence

from lib.models import SeasonDefinition, StaySegment

ONE_DAY = timedelta(days=1)


class SeasonCalendarError(Exception):
    """Base class for problems with the season calendar or a stay against it."""


class InvalidStayError(SeasonCalendarError):
    """The requested dates are not a stay at all (zero or negative nights)."""


class UnpricedNightError(SeasonCalendarError):
    """Part of the stay falls on dates no season covers.

    Raised rather than skipped: a night with no season has no rate, and quietly
    charging nothing for it would put a hole in both the client's quote and the
    owner's income.
    """

    def __init__(self, missing: Sequence[date]):
        self.missing = tuple(missing)
        first, last = self.missing[0], self.missing[-1]
        span = first.isoformat() if first == last else f"{first.isoformat()} to {last.isoformat()}"
        super().__init__(
            f"No season is defined for {len(self.missing)} night(s) of this stay ({span}). "
            "Add the missing dates to the season calendar before quoting."
        )


@dataclass(frozen=True)
class CalendarProblem:
    """Something wrong or worth warning about in the season calendar."""

    severity: str  # "error" or "warning"
    message: str


def nights_of(check_in: date, check_out: date) -> Iterator[date]:
    """Yield each charged night of a stay, by the date the night starts on.

    The check-out date is excluded - the guest sleeps there the night before
    and leaves in the morning.
    """
    if check_out <= check_in:
        raise InvalidStayError(
            f"Check-out ({check_out.isoformat()}) must be after check-in ({check_in.isoformat()})."
        )
    night = check_in
    while night < check_out:
        yield night
        night += ONE_DAY


def definition_for_date(
    definitions: Iterable[SeasonDefinition], day: date
) -> SeasonDefinition | None:
    """Return the season definition covering day, or None if nothing covers it.

    Where definitions overlap - which validate_calendar flags as an error - the
    earliest-starting one wins, so the result is at least deterministic.
    """
    match: SeasonDefinition | None = None
    for definition in definitions:
        if definition.start_date <= day <= definition.end_date:
            if match is None or definition.start_date < match.start_date:
                match = definition
    return match


def season_for_date(definitions: Iterable[SeasonDefinition], day: date) -> str | None:
    """Return just the season label covering day, or None."""
    match = definition_for_date(definitions, day)
    return match.label if match else None


def segment_stay(
    definitions: Iterable[SeasonDefinition], check_in: date, check_out: date
) -> tuple[StaySegment, ...]:
    """Break a stay into consecutive runs of nights sharing one season.

    Returns one segment per unbroken run, in date order. A stay wholly inside
    one season gives a single segment; a stay crossing several gives as many as
    it actually crosses - there is no assumption of "at most two" (3.5).

    Raises UnpricedNightError if any night falls outside every season.
    """
    definitions = list(definitions)
    segments: list[StaySegment] = []
    missing: list[date] = []

    # A run is broken by a change of label *or* of rate year: two consecutive
    # High stretches belonging to different years price off different rate
    # versions, so they are two segments, not one.
    run_key: tuple[str, int] | None = None
    run_start: date | None = None
    previous: date | None = None

    def close_run() -> None:
        if run_key is not None and run_start is not None and previous is not None:
            segments.append(StaySegment(run_key[0], run_key[1], run_start, previous))

    for night in nights_of(check_in, check_out):
        definition = definition_for_date(definitions, night)
        if definition is None:
            missing.append(night)
            continue
        key = (definition.label, definition.year)
        if key != run_key:
            close_run()
            run_key, run_start = key, night
        previous = night

    if missing:
        raise UnpricedNightError(missing)

    close_run()
    return tuple(segments)


def find_gaps(definitions: Iterable[SeasonDefinition], year: int) -> list[tuple[date, date]]:
    """Return the uncovered date ranges within year, as inclusive pairs."""
    covered = set()
    for definition in definitions:
        day = max(definition.start_date, date(year, 1, 1))
        last = min(definition.end_date, date(year, 12, 31))
        while day <= last:
            covered.add(day)
            day += ONE_DAY

    gaps: list[tuple[date, date]] = []
    gap_start: date | None = None
    day = date(year, 1, 1)
    end_of_year = date(year, 12, 31)
    while day <= end_of_year:
        if day in covered:
            if gap_start is not None:
                gaps.append((gap_start, day - ONE_DAY))
                gap_start = None
        elif gap_start is None:
            gap_start = day
        day += ONE_DAY
    if gap_start is not None:
        gaps.append((gap_start, end_of_year))
    return gaps


def validate_calendar(
    definitions: Sequence[SeasonDefinition], year: int | None = None
) -> list[CalendarProblem]:
    """Check the calendar the parents have typed in and report what is wrong.

    Errors are things that will misprice a stay (a backwards range, two seasons
    claiming the same date). The gap check is a warning: an uncovered stretch
    only bites when someone tries to quote across it, and part-way through
    setting up next year's dates it is expected.
    """
    problems: list[CalendarProblem] = []
    ordered = sorted(definitions, key=lambda d: (d.start_date, d.end_date))

    for definition in ordered:
        if definition.end_date < definition.start_date:
            problems.append(
                CalendarProblem(
                    "error",
                    f"{definition.label} {definition.start_date.isoformat()} to "
                    f"{definition.end_date.isoformat()} ends before it starts.",
                )
            )

    for earlier, later in zip(ordered, ordered[1:]):
        if later.start_date <= earlier.end_date:
            problems.append(
                CalendarProblem(
                    "error",
                    f"{earlier.label} ({earlier.start_date.isoformat()} to "
                    f"{earlier.end_date.isoformat()}) overlaps {later.label} "
                    f"({later.start_date.isoformat()} to {later.end_date.isoformat()}). "
                    "Each date must belong to exactly one season.",
                )
            )

    if year is not None:
        for gap_start, gap_end in find_gaps(ordered, year):
            span = (
                gap_start.isoformat()
                if gap_start == gap_end
                else f"{gap_start.isoformat()} to {gap_end.isoformat()}"
            )
            problems.append(
                CalendarProblem(
                    "warning",
                    f"No season covers {span} - stays across it cannot be quoted.",
                )
            )

    return problems


@dataclass(frozen=True)
class SeasonChange:
    """What a new or moved period does to one that was already there.

    Reported rather than applied silently: reshaping somebody's season calendar
    without saying what moved is how a year's rates quietly become wrong.
    """

    #: "removed", "shortened" or "split"
    kind: str
    original: SeasonDefinition
    #: What the original becomes - empty when it is removed entirely.
    replacements: tuple[SeasonDefinition, ...]

    def describe(self) -> str:
        was = (
            f"{self.original.label} {self.original.start_date.isoformat()} to "
            f"{self.original.end_date.isoformat()}"
        )
        if self.kind == "removed":
            return f"{was} was removed - the new period covers all of it."
        becomes = " and ".join(
            f"{part.start_date.isoformat()} to {part.end_date.isoformat()}"
            for part in self.replacements
        )
        verb = "was split into" if self.kind == "split" else "was shortened to"
        return f"{was} {verb} {becomes}."


def carve_out(
    definitions: Iterable[SeasonDefinition],
    start: date,
    end: date,
    ignore_id: int | None = None,
) -> list[SeasonChange]:
    """Work out what must give way for a period to occupy start..end.

    Every date belongs to exactly one season, so putting a period over dates
    another season already holds means that other season yields the overlap -
    shrinking back, splitting in two if the new period lands in its middle, or
    going altogether if it is wholly covered.

    `ignore_id` is the period being moved, which must not be asked to give way
    to itself.
    """
    changes: list[SeasonChange] = []

    for definition in definitions:
        if definition.id is not None and definition.id == ignore_id:
            continue
        if definition.end_date < start or definition.start_date > end:
            continue  # nowhere near it

        before_survives = definition.start_date < start
        after_survives = definition.end_date > end

        if before_survives and after_survives:
            changes.append(SeasonChange("split", definition, (
                replace(definition, end_date=start - ONE_DAY),
                replace(definition, id=None, start_date=end + ONE_DAY),
            )))
        elif before_survives:
            changes.append(SeasonChange("shortened", definition, (
                replace(definition, end_date=start - ONE_DAY),
            )))
        elif after_survives:
            changes.append(SeasonChange("shortened", definition, (
                replace(definition, start_date=end + ONE_DAY),
            )))
        else:
            changes.append(SeasonChange("removed", definition, ()))

    return changes
