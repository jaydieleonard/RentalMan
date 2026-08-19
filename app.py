"""RentalMan - the home page (spec 7).

Streamlit turns each file in pages/ into a navigation entry automatically, so
this file is the landing screen: whether everything is connected and set up,
and what still needs filling in before a quote can be produced.
"""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from db import queries
from lib.seasons import validate_calendar
from ui import page
from ui.brand import TAGLINE
from ui.format import money

page.start("RentalMan", hero=True)

st.caption(TAGLINE)

units = queries.list_units()
owners = queries.list_owners()
today = date.today()
seasons_this_year = queries.list_seasons(today.year)

left, middle, right = st.columns(3)
left.metric("Units", len(units))
middle.metric("Owners", len(owners))
right.metric(f"Season rows for {today.year}", len(seasons_this_year))

st.subheader("Where things stand")

if not owners:
    st.warning("No owners on file yet. Start on the **Owners** side of the Units page.")
if not units:
    st.warning("No units yet - add the flats on the **Units** page.")
if not seasons_this_year:
    st.warning(
        f"No season dates for {today.year} yet. Nothing can be quoted until the "
        "**Seasons** page has low/medium/high dates for the year."
    )
else:
    for problem in validate_calendar(seasons_this_year, year=today.year):
        (st.error if problem.severity == "error" else st.warning)(problem.message)

# A unit with no rate for a season it will actually be booked in is the failure
# that only shows up mid-quote, so it is worth saying here instead.
if units and seasons_this_year:
    labels_in_use = {definition.label for definition in seasons_this_year}
    rates = queries.list_client_rates(year=today.year)
    priced = {(rate.unit_id, rate.season_label) for rate in rates}
    unpriced = [
        unit.name
        for unit in units
        if any((unit.id, label) not in priced for label in labels_in_use)
    ]
    if unpriced:
        st.warning(
            f"{len(unpriced)} unit(s) have no {today.year} rate for at least one season: "
            + ", ".join(sorted(unpriced)[:8])
            + ("..." if len(unpriced) > 8 else "")
        )
    else:
        st.success(f"Every unit has a {today.year} rate for every season in use.")

st.subheader("This month")
month_start = today.replace(day=1)
next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
bookings = queries.list_bookings(month_start, next_month)
confirmed = [b for b in bookings if b.status == "confirmed"]
income = sum((b.total_price or 0) for b in confirmed)

first, second = st.columns(2)
first.metric("Confirmed stays touching this month", len(confirmed))
second.metric("Value of those bookings", money(income))

st.caption(
    "Built so far: units, owners, the season calendar, client rates, the booking "
    "grid, and entering bookings by hand. Availability search and quoting come "
    "next (spec 9)."
)
