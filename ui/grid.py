"""The booking grid: units down the side, dates across the top (spec 3.1).

Rendered as a plain HTML table rather than a dataframe so that the first column
and the date header can stay put while the rest scrolls, and so a cell can
carry its booking's details in a tooltip. It has to still be readable at 30+
units, which is what the sticky column and the filters on the page are for.
"""

from __future__ import annotations

from datetime import date
from html import escape
from typing import Mapping, Sequence

from lib.availability import BLOCKED, BOOKED, BUFFER, OPEN, Occupancy
from lib.models import Booking, Client, Unit
from ui.format import date_range, nights

STATUS_COLOURS = {
    OPEN: ("#e8f5e9", "#1b5e20"),
    BOOKED: ("#1976d2", "#ffffff"),
    BUFFER: ("#ffe0b2", "#7a4f01"),
    BLOCKED: ("#bdbdbd", "#3a3a3a"),
}

STATUS_NAMES = {
    OPEN: "Open",
    BOOKED: "Booked",
    BUFFER: "Turnover gap",
    BLOCKED: "Blocked",
}

GRID_CSS = """
<style>
.rm-grid-wrap { overflow: auto; max-height: 70vh; border: 1px solid #d9d9d9;
                border-radius: 6px; }
.rm-grid { border-collapse: separate; border-spacing: 0; font-size: 12px;
           font-family: inherit; }
.rm-grid th, .rm-grid td { padding: 0; margin: 0; }
.rm-grid thead th { position: sticky; top: 0; z-index: 3; background: #fafafa;
                    border-bottom: 1px solid #d9d9d9; padding: 4px 0;
                    min-width: 26px; text-align: center; font-weight: 600;
                    color: #444; }
.rm-grid thead th.rm-unit-head { left: 0; z-index: 4; text-align: left;
                                 padding-left: 10px; min-width: 190px; }
.rm-grid td.rm-unit { position: sticky; left: 0; z-index: 2; background: #fff;
                      border-right: 1px solid #d9d9d9; padding: 3px 10px;
                      white-space: nowrap; }
.rm-grid td.rm-cell { border: 1px solid #ffffff; height: 26px; text-align: center;
                      cursor: default; }
.rm-grid .rm-weekend { background: #f0f0f0; }
.rm-grid .rm-today { box-shadow: inset 0 0 0 2px #d32f2f; }
.rm-grid .rm-beds { color: #888; font-weight: 400; }
.rm-legend { display: flex; gap: 16px; flex-wrap: wrap; font-size: 12px;
             margin: 8px 0 4px; align-items: center; }
.rm-legend span.rm-swatch { display: inline-block; width: 14px; height: 14px;
                            border-radius: 3px; margin-right: 6px;
                            vertical-align: -2px; border: 1px solid #00000022; }
</style>
"""


def legend_html() -> str:
    items = "".join(
        f'<div><span class="rm-swatch" style="background:{STATUS_COLOURS[status][0]}"></span>'
        f"{STATUS_NAMES[status]}</div>"
        for status in (OPEN, BOOKED, BUFFER, BLOCKED)
    )
    return f'<div class="rm-legend">{items}</div>'


def _tooltip(
    cell: Occupancy,
    unit: Unit,
    day: date,
    bookings: Mapping[int, Booking],
    clients: Mapping[int, Client],
) -> str:
    if cell.status == BOOKED and cell.booking_id in bookings:
        booking = bookings[cell.booking_id]
        client = clients.get(booking.client_id)
        who = client.name if client else "No client on record"
        return (
            f"{unit.name}: {who} - {date_range(booking.check_in, booking.check_out)} "
            f"({nights(booking.nights)}) - booking #{booking.id}"
        )
    if cell.status == BUFFER:
        return f"{unit.name}: turnover gap - held free between guests"
    if cell.status == BLOCKED:
        return f"{unit.name}: blocked{' - ' + cell.label if cell.label else ''}"
    return f"{unit.name}: open on {day.isoformat()}"


def render_grid(
    units: Sequence[Unit],
    days: Sequence[date],
    occupancy_by_unit: Mapping[int, Mapping[date, Occupancy]],
    bookings: Mapping[int, Booking],
    clients: Mapping[int, Client],
    today: date | None = None,
) -> str:
    """Build the whole grid as one HTML string, ready for st.markdown.

    `occupancy_by_unit` comes straight from lib.availability.occupancy, one
    entry per unit, so what the grid draws and what the availability search
    decides can never drift apart.
    """
    if not units:
        return "<p>No units match these filters.</p>"

    header = ['<th class="rm-unit-head">Unit</th>']
    for day in days:
        weekend = " rm-weekend" if day.weekday() >= 5 else ""
        header.append(
            f'<th class="{weekend.strip()}" title="{day.strftime("%A %d %B %Y")}">'
            f'{day.day}<br><span style="font-weight:400;color:#999">'
            f'{day.strftime("%a")[0]}</span></th>'
        )

    rows = []
    for unit in units:
        cells = [
            f'<td class="rm-unit">{escape(unit.name)} '
            f'<span class="rm-beds">{unit.beds}b/{unit.sleeps}p</span></td>'
        ]
        unit_days = occupancy_by_unit.get(unit.id, {})
        for day in days:
            cell = unit_days.get(day, Occupancy(OPEN))
            background, _ = STATUS_COLOURS.get(cell.status, STATUS_COLOURS[OPEN])
            classes = ["rm-cell"]
            if day.weekday() >= 5 and cell.status == OPEN:
                background = "#dcedc8"
            if today is not None and day == today:
                classes.append("rm-today")
            cells.append(
                f'<td class="{" ".join(classes)}" style="background:{background}" '
                f'title="{escape(_tooltip(cell, unit, day, bookings, clients))}"></td>'
            )
        rows.append("<tr>" + "".join(cells) + "</tr>")

    return (
        GRID_CSS
        + legend_html()
        + '<div class="rm-grid-wrap"><table class="rm-grid"><thead><tr>'
        + "".join(header)
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


SEASON_COLOURS = {
    "Low": "#c8e6c9",
    "Medium": "#ffe082",
    "High": "#ef9a9a",
}
UNCOVERED_COLOUR = "#f0f0f0"

RIBBON_CSS = """
<style>
.rm-year { border-collapse: separate; border-spacing: 0; font-size: 11px; }
.rm-year td, .rm-year th { padding: 0; }
.rm-year th { color: #666; font-weight: 600; padding: 2px 6px 2px 0; text-align: right; }
.rm-year thead th { text-align: center; padding: 0 0 3px; min-width: 17px; color: #999;
                    font-weight: 400; }
.rm-year td.rm-day { width: 17px; height: 17px; border: 1px solid #fff; }
</style>
"""


def render_year_ribbon(definitions: Sequence, year: int) -> str:
    """A month-by-day map of which season covers what, for spotting gaps.

    Uncovered days show pale grey: those are the dates a stay cannot be quoted
    across, which is far easier to see here than to work out from a list of
    start and end dates.
    """
    import calendar

    from lib.seasons import season_for_date

    header = "".join(f"<th>{day}</th>" for day in range(1, 32))
    rows = []
    for month in range(1, 13):
        days_in_month = calendar.monthrange(year, month)[1]
        cells = []
        for day_number in range(1, 32):
            if day_number > days_in_month:
                cells.append('<td class="rm-day" style="background:transparent"></td>')
                continue
            day = date(year, month, day_number)
            label = season_for_date(definitions, day)
            colour = SEASON_COLOURS.get(label, UNCOVERED_COLOUR)
            title = f"{day.strftime('%d %b %Y')}: {label or 'no season set'}"
            cells.append(f'<td class="rm-day" style="background:{colour}" title="{title}"></td>')
        rows.append(
            f'<tr><th>{date(year, month, 1).strftime("%b")}</th>' + "".join(cells) + "</tr>"
        )

    swatches = "".join(
        f'<div><span class="rm-swatch" style="background:{colour}"></span>{label}</div>'
        for label, colour in list(SEASON_COLOURS.items()) + [("Not set", UNCOVERED_COLOUR)]
    )
    return (
        GRID_CSS
        + RIBBON_CSS
        + f'<div class="rm-legend">{swatches}</div>'
        + '<table class="rm-year"><thead><tr><th></th>'
        + header
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


CLEANING_CSS = """
<style>
.rm-grid tfoot td { position: sticky; bottom: 0; z-index: 3; background: #fafafa;
                    border-top: 2px solid #d9d9d9; }
.rm-grid tfoot td.rm-total { font-size: 11px; font-weight: 700; color: #7f1d1d;
                             text-align: center; }
.rm-grid tfoot td.rm-total-head { left: 0; z-index: 5; font-size: 11px; color: #444;
                                  font-weight: 600; }
</style>
"""

SERVICE_COLOURS = {
    "changeover clean": "#1976d2",
    "post-clean": "#00897b",
    "pre-clean": "#f9a825",
    "light clean": "#7e57c2",
    "deep clean": "#37474f",
}
UNASSIGNED = "#e0e0e0"


def initials(name: str) -> str:
    """Two letters at most - a grid cell has room for a mark, not a name."""
    parts = [part for part in name.replace(".", " ").split() if part]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def render_cleaning_grid(
    units: Sequence,
    days: Sequence[date],
    jobs_by_unit: Mapping[int, Mapping[date, Sequence]],
    staff_names: Mapping[int, str],
    today: date | None = None,
) -> str:
    """Flats down the side, days across, one mark per scheduled clean (3.9).

    Flats rather than staff on the vertical, so it lines up with the booking
    calendar and so a job nobody has been given yet still has a row to sit in -
    which is the thing worth spotting.
    """
    if not units:
        return "<p>No units match these filters.</p>"

    header = ['<th class="rm-unit-head">Flat</th>']
    for day in days:
        weekend = "rm-weekend" if day.weekday() >= 5 else ""
        header.append(
            f'<th class="{weekend}" title="{day.strftime("%A %d %B %Y")}">{day.day}<br>'
            f'<span style="font-weight:400;color:#999">{day.strftime("%a")[0]}</span></th>'
        )

    rows = []
    for unit in units:
        cells = [f'<td class="rm-unit">{escape(unit.name)}</td>']
        for day in days:
            jobs = jobs_by_unit.get(unit.id, {}).get(day, [])
            if not jobs:
                background, text, title = ("#f7f7f7" if day.weekday() < 5 else "#f0f0f0"), "", ""
            else:
                job = jobs[0]
                background = SERVICE_COLOURS.get(job.service_label, "#9e9e9e")
                who = staff_names.get(job.staff_id)
                text = initials(who) if who else "?"
                if not who:
                    background = UNASSIGNED
                title = "; ".join(
                    f"{j.service_label} - {staff_names.get(j.staff_id, 'nobody assigned yet')}"
                    f" ({j.status})"
                    for j in jobs
                )
                if len(jobs) > 1:
                    text = f"{text}+"
            classes = "rm-cell" + (" rm-today" if today and day == today else "")
            colour = "#ffffff" if text and background != UNASSIGNED else "#555"
            cells.append(
                f'<td class="{classes}" style="background:{background};color:{colour};'
                f'font-size:10px;font-weight:600" title="{escape(title)}">{text}</td>'
            )
        rows.append("<tr>" + "".join(cells) + "</tr>")

    # How much cleaning each day carries, across every flat shown. This is the
    # question the calendar is really asked - not "is this flat clean" but
    # "can the cleaners get through Saturday" - so it gets its own row rather
    # than leaving somebody to count coloured squares down a column.
    totals = [
        sum(len(jobs_by_unit.get(unit.id, {}).get(day, [])) for unit in units)
        for day in days
    ]
    busiest = max(totals) if totals else 0
    footer = ['<td class="rm-unit rm-total-head">Cleans that day</td>']
    for day, count in zip(days, totals):
        # Shaded by how heavy the day is, so a pile-up is visible at a glance
        # rather than needing to be read number by number.
        weight = 0 if not busiest else count / busiest
        background = "#ffffff" if not count else f"rgba(198, 40, 40, {0.10 + 0.55 * weight:.2f})"
        footer.append(
            f'<td class="rm-cell rm-total" style="background:{background}" '
            f'title="{count} clean(s) on {day.strftime("%a %d %b")}">{count or ""}</td>'
        )

    swatches = "".join(
        f'<div><span class="rm-swatch" style="background:{colour}"></span>{label}</div>'
        for label, colour in SERVICE_COLOURS.items()
    ) + f'<div><span class="rm-swatch" style="background:{UNASSIGNED}"></span>nobody assigned</div>'

    return (
        GRID_CSS
        + CLEANING_CSS
        + f'<div class="rm-legend">{swatches}</div>'
        + '<div class="rm-grid-wrap"><table class="rm-grid"><thead><tr>'
        + "".join(header)
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody><tfoot><tr>"
        + "".join(footer)
        + "</tr></tfoot></table></div>"
    )
