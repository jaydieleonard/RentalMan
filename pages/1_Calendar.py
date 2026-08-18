"""The booking grid: every flat, every night of the month, at a glance (spec 3.1).

A read-only view: bookings are entered and corrected on the Bookings page, and
from Phase 3 will also arrive by accepting a quote. What it shows comes from
lib.availability.occupancy, the same function the availability search will use,
so a night that reads as open here is a night that really can be sold.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from db import queries
from lib.availability import occupancy
from ui import page
from ui.format import date_range, money, nights
from ui.grid import render_grid

page.start("Booking calendar")

units = queries.list_units(include_inactive=True)
if not units:
    page.no_data("units", "Units")
    st.stop()

owners = {owner.id: owner for owner in queries.list_owners()}

# --- Which month are we looking at ---------------------------------------

if "calendar_month" not in st.session_state:
    st.session_state.calendar_month = date.today().replace(day=1)

anchor = st.session_state.calendar_month
back, today_button, forward, jump = st.columns([1, 1, 1, 3])

if back.button("< Previous", use_container_width=True):
    st.session_state.calendar_month = (anchor - timedelta(days=1)).replace(day=1)
    st.rerun()
if today_button.button("This month", use_container_width=True):
    st.session_state.calendar_month = date.today().replace(day=1)
    st.rerun()
if forward.button("Next >", use_container_width=True):
    last_day = calendar.monthrange(anchor.year, anchor.month)[1]
    st.session_state.calendar_month = (anchor.replace(day=last_day) + timedelta(days=1))
    st.rerun()

jumped = jump.date_input("Jump to", value=anchor, format="DD/MM/YYYY")
if jumped and jumped.replace(day=1) != anchor:
    st.session_state.calendar_month = jumped.replace(day=1)
    st.rerun()

anchor = st.session_state.calendar_month
days_in_month = calendar.monthrange(anchor.year, anchor.month)[1]
month_start = anchor
month_end = anchor + timedelta(days=days_in_month)  # exclusive
days = [month_start + timedelta(days=offset) for offset in range(days_in_month)]

st.subheader(anchor.strftime("%B %Y"))

# --- Filters, so the grid stays readable past 30 units --------------------

with st.expander("Filters", expanded=False):
    filter_columns = st.columns(4)
    owner_choice = filter_columns[0].selectbox(
        "Owner", ["All owners"] + [owner.name for owner in owners.values()]
    )
    minimum_beds = filter_columns[1].number_input("Minimum beds", min_value=0, value=0, step=1)
    tags = sorted({unit.group_tag for unit in units if unit.group_tag})
    chosen_tags = filter_columns[2].multiselect("Group", tags) if tags else []
    show_inactive = filter_columns[3].checkbox("Include inactive units", value=False)

visible = [unit for unit in units if show_inactive or unit.active]
if owner_choice != "All owners":
    owner_ids = {owner.id for owner in owners.values() if owner.name == owner_choice}
    visible = [unit for unit in visible if unit.owner_id in owner_ids]
if minimum_beds:
    visible = [unit for unit in visible if unit.beds >= minimum_beds]
if chosen_tags:
    visible = [unit for unit in visible if unit.group_tag in chosen_tags]

if not visible:
    st.info("No units match these filters.")
    st.stop()

# --- The grid itself ------------------------------------------------------

unit_ids = [unit.id for unit in visible]
# Bookings are fetched a little wider than the month so that a stay starting in
# the previous month still paints its nights inside this one, and so a buffer
# reaching back over the month boundary is not missed.
window_start = month_start - timedelta(days=7)
window_end = month_end + timedelta(days=7)

bookings = queries.list_bookings(window_start, window_end, unit_ids=unit_ids)
rules = queries.list_turnover_rules()
seasons = queries.list_seasons()
blocks = queries.list_unit_blocks(window_start, window_end)
clients = {client.id: client for client in queries.list_clients()}

occupancy_by_unit = {
    unit.id: occupancy(unit.id, month_start, month_end, bookings, rules, seasons, blocks)
    for unit in visible
}

st.markdown(
    render_grid(
        units=visible,
        days=days,
        occupancy_by_unit=occupancy_by_unit,
        bookings={booking.id: booking for booking in bookings},
        clients=clients,
        today=date.today(),
    ),
    unsafe_allow_html=True,
)
st.caption("Hover a cell for the booking behind it. Weekends are shaded; today is outlined in red.")

# --- What is actually in the month ---------------------------------------

unit_names = {unit.id: unit.name for unit in units}
in_view = [
    booking
    for booking in bookings
    if booking.check_out > month_start and booking.check_in < month_end
]

st.subheader(f"Bookings in {anchor.strftime('%B %Y')}")
if not in_view:
    st.info("Nothing booked in this month yet. Bookings are entered on the Bookings page.")
else:
    table = pd.DataFrame(
        [
            {
                "Ref": booking.id,
                "Unit": unit_names.get(booking.unit_id, "?"),
                "Client": (clients[booking.client_id].name
                           if booking.client_id in clients else "-"),
                "Dates": date_range(booking.check_in, booking.check_out),
                "Nights": booking.nights,
                "Status": booking.status.title(),
                "Total": money(booking.total_price),
                "Notes": booking.notes,
            }
            for booking in sorted(in_view, key=lambda b: (b.check_in, unit_names.get(b.unit_id, "")))
        ]
    )
    st.dataframe(table, hide_index=True, use_container_width=True)

occupied_nights = sum(
    1
    for unit_days in occupancy_by_unit.values()
    for cell in unit_days.values()
    if cell.status == "booked"
)
available_nights = len(visible) * days_in_month
if available_nights:
    st.caption(
        f"{occupied_nights} of {available_nights} unit-nights booked this month "
        f"({occupied_nights / available_nights:.0%} occupancy across the units shown)."
    )
