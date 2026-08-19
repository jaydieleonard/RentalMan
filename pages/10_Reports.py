"""How the flats are doing: occupancy and revenue (spec 9, Phase 6).

Built to answer questions the parents can act on - which flats earn their
keep, which sit empty, whether high season is worth what it charges - so the
figures are the ones they already have: nights actually slept and money
actually charged.

The magnitudes live in the tables rather than in separate charts. With fifteen
flats the exact figure matters as much as the shape, and a bar inside the row
gives both without a legend, a colour key, or a second thing to read.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from db import queries
from lib.reporting import build_report
from ui import page
from ui.format import money

page.start("Reports")

units = queries.list_units(include_inactive=True)
if not units:
    page.no_data("units", "Units")
    st.stop()

today = date.today()
this_month = today.replace(day=1)
last_month = (this_month - timedelta(days=1)).replace(day=1)

PERIODS = {
    "This month": (this_month, (this_month + timedelta(days=32)).replace(day=1)),
    "Last month": (last_month, this_month),
    "This year": (date(today.year, 1, 1), date(today.year + 1, 1, 1)),
    "Last year": (date(today.year - 1, 1, 1), date(today.year, 1, 1)),
    "Last 12 months": ((this_month - timedelta(days=365)).replace(day=1), this_month),
}

choice = st.columns([2, 2, 2, 3])
period_name = choice[0].selectbox("Period", list(PERIODS) + ["Choose dates"], index=1)

if period_name == "Choose dates":
    start = choice[1].date_input("From", value=last_month, format="DD/MM/YYYY")
    end_inclusive = choice[2].date_input("To", value=today, format="DD/MM/YYYY")
    end = end_inclusive + timedelta(days=1)
    if end <= start:
        st.error("The end date must be on or after the start date.")
        st.stop()
else:
    start, end = PERIODS[period_name]

include_inactive = choice[3].checkbox(
    "Include inactive flats", value=False,
    help="Off by default: a flat taken off the market drags the average down for "
         "no reason anybody can act on.",
)
reported_units = [unit for unit in units if include_inactive or unit.active]

bookings = queries.list_bookings(start, end)
report = build_report(
    reported_units, start, end, bookings, queries.list_seasons(),
    queries.list_unit_blocks(start, end),
)

st.caption(
    f"{start.strftime('%d %B %Y')} to {(end - timedelta(days=1)).strftime('%d %B %Y')} - "
    f"{len(reported_units)} flat(s)."
)

# --- The headline ---------------------------------------------------------

headline = st.columns(4)
headline[0].metric("Occupancy", f"{report.occupancy:.0%}")
headline[1].metric("Revenue", money(report.revenue))
headline[2].metric("Nights let", f"{report.nights_let} of {report.nights_available}")
headline[3].metric(
    "Per available night",
    money(report.revenue / report.nights_available) if report.nights_available else money(0),
)

if report.unattributed_nights:
    st.warning(
        f"{report.unattributed_nights} let night(s) fall on dates no season covers, so "
        "they are missing from the season breakdown below. Fill the gap in on the "
        "Seasons page."
    )

# Reserved here, filled at the end: how occupancy moves through the year
# belongs beside the headline, not after three tables.
trend_panel = st.container()

# --- Flat by flat ---------------------------------------------------------

st.subheader("Flat by flat")

flats = pd.DataFrame(
    [
        {
            "Flat": unit.unit_name,
            "Stays": unit.stays,
            "Nights let": unit.nights_let,
            "Occupancy": round(unit.occupancy * 100),
            "Revenue": float(unit.revenue),
            "Per available night": money(unit.revenue_per_available_night),
            "Off market": unit.nights_blocked,
        }
        for unit in report.units
    ]
)

st.dataframe(
    flats,
    hide_index=True,
    use_container_width=True,
    column_config={
        # The bar and the figure together: with fifteen flats the exact number
        # matters as much as the shape, and neither is worth a second chart.
        "Occupancy": st.column_config.ProgressColumn(
            "Occupancy", format="%d%%", min_value=0, max_value=100
        ),
        "Revenue": st.column_config.ProgressColumn(
            "Revenue", format="R%.0f", min_value=0,
            max_value=float(max([unit.revenue for unit in report.units], default=1)) or 1,
        ),
        "Off market": st.column_config.NumberColumn(
            "Off market", help="Nights blocked for maintenance, which are left out "
                               "of the occupancy sum rather than counted as empty.",
        ),
    },
)

empty = [unit for unit in report.units if unit.nights_let == 0]
if empty:
    st.caption(
        f"{len(empty)} flat(s) took nobody at all in this period: "
        + ", ".join(unit.unit_name for unit in empty[:6])
        + ("..." if len(empty) > 6 else "")
    )

# --- By season ------------------------------------------------------------

if report.seasons:
    st.subheader("By season")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Season": season.season_label,
                    "Nights let": season.nights_let,
                    "Revenue": float(season.revenue),
                    "Average a night": money(season.average_nightly),
                    "Share of revenue": round(
                        float(season.revenue) / float(report.revenue) * 100
                    ) if report.revenue else 0,
                }
                for season in report.seasons
            ]
        ),
        hide_index=True,
        use_container_width=True,
        column_config={
            "Revenue": st.column_config.ProgressColumn(
                "Revenue", format="R%.0f", min_value=0,
                max_value=float(max([s.revenue for s in report.seasons], default=1)) or 1,
            ),
            "Share of revenue": st.column_config.ProgressColumn(
                "Share of revenue", format="%d%%", min_value=0, max_value=100
            ),
        },
    )
    st.caption(
        "A stay crossing a season change has its money split between them in "
        "proportion to the nights, so the seasons always add back to the total."
    )

# --- By owner -------------------------------------------------------------

owners = {owner.id: owner.name for owner in queries.list_owners()}
rows = report.by_owner(owners)
if len(rows) > 1:
    st.subheader("By owner")
    st.dataframe(
        pd.DataFrame(
            [
                {"Owner": name, "Nights let": nights, "Revenue": float(revenue),
                 "Occupancy": round(share * 100)}
                for name, nights, revenue, share in rows
            ]
        ),
        hide_index=True,
        use_container_width=True,
        column_config={
            "Revenue": st.column_config.ProgressColumn(
                "Revenue", format="R%.0f", min_value=0,
                max_value=float(max([row[2] for row in rows], default=1)) or 1,
            ),
            "Occupancy": st.column_config.ProgressColumn(
                "Occupancy", format="%d%%", min_value=0, max_value=100
            ),
        },
    )
    st.caption(
        "What the guests paid, which is not what the owner receives - that is on "
        "their monthly statement, after the owner rate, the management fee and cleaning."
    )

# --- Month by month -------------------------------------------------------

months: list[date] = []
cursor = start.replace(day=1)
while cursor < end:
    months.append(cursor)
    cursor = (cursor + timedelta(days=32)).replace(day=1)

if len(months) > 1:
    with trend_panel:
        st.subheader("Occupancy, month by month")
        monthly = []
        for month_start in months:
            month_end = min((month_start + timedelta(days=32)).replace(day=1), end)
            slice_start = max(month_start, start)
            if month_end <= slice_start:
                continue
            month_report = build_report(
                reported_units, slice_start, month_end, bookings,
                queries.list_seasons(), queries.list_unit_blocks(slice_start, month_end),
            )
            monthly.append({
                "Month": month_start.strftime("%b %Y"),
                "Occupancy": round(month_report.occupancy * 100),
                "Revenue": float(month_report.revenue),
            })

        if monthly:
            frame = pd.DataFrame(monthly).set_index("Month")
            # One line, so the heading names it and no key is needed.
            st.line_chart(frame[["Occupancy"]], height=220, y_label="Occupancy %")
            busiest = max(monthly, key=lambda row: row["Occupancy"])
            quietest = min(monthly, key=lambda row: row["Occupancy"])
            st.caption(
                f"Fullest in {busiest['Month']} at {busiest['Occupancy']}%; "
                f"emptiest in {quietest['Month']} at {quietest['Occupancy']}%. "
                "Revenue by month is in the table below."
            )
            st.dataframe(
                pd.DataFrame(monthly),
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Occupancy": st.column_config.ProgressColumn(
                        "Occupancy", format="%d%%", min_value=0, max_value=100
                    ),
                    "Revenue": st.column_config.ProgressColumn(
                        "Revenue", format="R%.0f", min_value=0,
                        max_value=max([row["Revenue"] for row in monthly] + [1]),
                    ),
                },
            )
