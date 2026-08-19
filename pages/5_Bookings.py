"""Capturing bookings by hand, and correcting them afterwards (spec 3.6).

Brought forward from Phase 3 so the flats' existing bookings can be entered
before the quote flow exists. When quoting lands, the quote builder joins this
page as another tab and "accept this quote" writes a booking through the same
checks used here - it does not become a second way in.

Nothing is saved without running lib.availability first, so a stay cannot be
entered on top of another one, or inside the turnover gap a flat needs. The
database's own exclusion constraint is the backstop if the other laptop saves
in the same moment.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import streamlit as st

from db import queries
from lib.availability import BUFFER, is_available
from lib.models import BOOKING_STATUSES
from lib.rates import PricingError, index_rates, minimum_stay_for, price_segments
from lib.seasons import SeasonCalendarError, segment_stay
from ui import page
from ui.clients import client_picker
from ui.format import date_range, money, nights

page.start("Bookings")

units = queries.list_units(include_inactive=True)
if not units:
    page.no_data("units", "Units")
    st.stop()

units_by_id = {unit.id: unit for unit in units}
seasons = queries.list_seasons()

# Widget keys carry a round number so that saving a booking can hand the next
# one sensible defaults: Streamlit will not let a widget's own state be
# rewritten after it exists, but a new key makes a fresh widget.
if "capture_round" not in st.session_state:
    st.session_state.capture_round = 0
round_key = st.session_state.capture_round

capture_tab, find_tab = st.tabs(["Add a booking", "Find and edit"])

with capture_tab:
    st.caption(
        "For entering bookings you already have on paper or in the diary. Dates are "
        "checked against everything else on file before anything is saved."
    )

    columns = st.columns([3, 2, 2])
    unit_name = columns[0].selectbox("Flat", [unit.name for unit in units], key="add_unit")
    unit = next(u for u in units if u.name == unit_name)

    default_check_in = st.session_state.get("next_check_in", date.today())
    check_in = columns[1].date_input(
        "Check-in", value=default_check_in, format="DD/MM/YYYY", key=f"add_in_{round_key}"
    )
    check_out = columns[2].date_input(
        "Check-out",
        value=check_in + timedelta(days=1),
        format="DD/MM/YYYY",
        key=f"add_out_{round_key}",
    )

    guest = client_picker(f"add_client_{round_key}")

    # --- Is it free, and what does it come to? ---------------------------

    stay_is_valid = check_out > check_in
    if not stay_is_valid:
        st.error("Check-out must be after check-in.")

    # Set when the dates land on another guest or on blocked dates - the two
    # cases that must not be saved however the button is pressed.
    clash_stops_save = False

    calculated_total: Decimal | None = None
    if stay_is_valid:
        window_bookings = queries.list_bookings(
            check_in - timedelta(days=14), check_out + timedelta(days=14), unit_ids=[unit.id]
        )
        availability = is_available(
            unit.id,
            check_in,
            check_out,
            window_bookings,
            queries.list_turnover_rules(unit.id),
            seasons,
            queries.list_unit_blocks(check_in - timedelta(days=14), check_out + timedelta(days=14)),
        )
        if availability.available:
            st.success(f"{unit.name} is free for these dates.")
        else:
            which_nights = ", ".join(
                day.strftime("%d %b") for day in availability.blocked_nights[:8]
            ) + ("..." if len(availability.blocked_nights) > 8 else "")
            if availability.kind == BUFFER:
                # A stay that already happened over what is now a turnover gap
                # is a fact worth recording, so this warns rather than refuses.
                st.warning(f"{availability.reason} ({which_nights})")
            else:
                clash_stops_save = True
                st.error(f"{availability.reason} ({which_nights})")

        try:
            segments = segment_stay(seasons, check_in, check_out)
            rate_index = index_rates(queries.list_client_rates(unit.id))
            quote = price_segments(unit.id, check_in, check_out, segments, rate_index)
            calculated_total = quote.total

            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Season": line.season_label,
                            "Nights": line.nights,
                            "Per night": money(line.nightly_rate),
                            "Subtotal": money(line.subtotal),
                        }
                        for line in quote.lines
                    ]
                ),
                hide_index=True,
                use_container_width=True,
            )
            st.caption(f"{nights(quote.nights)} - rate-file total {money(quote.total)}.")

            # A booking already taken is a fact, so a stay under today's
            # minimum is worth saying but never worth refusing.
            check = minimum_stay_for(segments, rate_index, unit.min_nights)
            if not check.satisfied_by(quote.nights):
                st.warning(f"Shorter than the current rules allow - {check.explain()}")
        except (SeasonCalendarError, PricingError) as error:
            # Missing seasons or missing rates only stop the total being worked
            # out; the booking itself can still be captured with a typed price.
            st.info(f"Cannot work the price out automatically: {error}")

    # --- Save it ---------------------------------------------------------

    detail_columns = st.columns([2, 2, 4])
    status = detail_columns[0].selectbox(
        "Status",
        BOOKING_STATUSES,
        index=BOOKING_STATUSES.index("confirmed"),
        key=f"add_status_{round_key}",
        help="Only confirmed bookings hold the dates on the calendar.",
    )
    total_price = detail_columns[1].number_input(
        "Total charged",
        min_value=0.0,
        step=100.0,
        value=float(calculated_total) if calculated_total is not None else 0.0,
        key=f"add_total_{round_key}",
        help="Taken from the rate file. Change it if the guest was quoted something else.",
    )
    booking_notes = detail_columns[2].text_input("Notes", key=f"add_notes_{round_key}")

    if st.button(
        "Save booking", type="primary", disabled=not stay_is_valid or clash_stops_save
    ):
        if clash_stops_save:
            st.error("Those dates are not free - nothing was saved.")
            st.stop()
        if not guest.is_usable:
            st.error("Give the guest a name, or pick one already on file.")
            st.stop()
        client_id = guest.commit()

        try:
            reference = queries.create_booking(
                unit.id, client_id, check_in, check_out, status,
                Decimal(str(total_price)) if total_price else None, booking_notes.strip(),
            )
        except queries.BookingClash as clash:
            st.error(str(clash))
        else:
            st.success(
                f"Booking #{reference} saved: {unit.name}, "
                f"{date_range(check_in, check_out)}."
            )
            # Ready for the next one on the same flat, starting where this ended.
            st.session_state.next_check_in = check_out
            st.session_state.capture_round += 1
            st.rerun()

# --- Finding and correcting what is already captured ---------------------

with find_tab:
    filters = st.columns([3, 2, 2, 2])
    search = filters[0].text_input("Search", placeholder="Client name, note or reference")
    unit_filter = filters[1].selectbox("Flat", ["All flats"] + [u.name for u in units])
    status_filter = filters[2].multiselect("Status", BOOKING_STATUSES, default=[])
    span = filters[3].selectbox(
        "Period", ["From today", "This year", "Everything"], index=0
    )

    today = date.today()
    if span == "From today":
        window_start, window_end = today, None
    elif span == "This year":
        window_start, window_end = date(today.year, 1, 1), date(today.year + 1, 1, 1)
    else:
        window_start, window_end = None, None

    unit_ids = None if unit_filter == "All flats" else [
        next(u.id for u in units if u.name == unit_filter)
    ]
    found = queries.list_bookings(
        window_start, window_end, unit_ids=unit_ids, statuses=status_filter or None
    )
    clients_by_id = queries.get_clients({b.client_id for b in found})

    if search.strip():
        needle = search.strip().lower()

        def matches(booking) -> bool:
            client = clients_by_id.get(booking.client_id)
            haystack = [
                str(booking.id),
                booking.notes,
                client.name if client else "",
                units_by_id[booking.unit_id].name,
            ]
            return any(needle in value.lower() for value in haystack)

        found = [booking for booking in found if matches(booking)]

    st.caption(f"{len(found)} booking(s).")
    if found:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Ref": booking.id,
                        "Flat": units_by_id[booking.unit_id].name,
                        "Client": (clients_by_id[booking.client_id].name
                                   if booking.client_id in clients_by_id else "-"),
                        "Dates": date_range(booking.check_in, booking.check_out),
                        "Nights": booking.nights,
                        "Status": booking.status.title(),
                        "Total": money(booking.total_price),
                        "Notes": booking.notes,
                    }
                    for booking in found
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )

    if found:
        st.divider()
        st.markdown("**Correct a booking**")
        labels = {
            f"#{b.id} - {units_by_id[b.unit_id].name} - "
            f"{date_range(b.check_in, b.check_out)}": b
            for b in found
        }
        chosen = st.selectbox("Booking", list(labels), key="edit_booking_pick")
        booking = labels[chosen]

        edit_columns = st.columns([3, 2, 2])
        edit_unit_name = edit_columns[0].selectbox(
            "Flat",
            [unit.name for unit in units],
            index=[u.id for u in units].index(booking.unit_id),
            key=f"edit_unit_{booking.id}",
        )
        edit_unit = next(u for u in units if u.name == edit_unit_name)
        edit_check_in = edit_columns[1].date_input(
            "Check-in", value=booking.check_in, format="DD/MM/YYYY", key=f"edit_in_{booking.id}"
        )
        edit_check_out = edit_columns[2].date_input(
            "Check-out", value=booking.check_out, format="DD/MM/YYYY", key=f"edit_out_{booking.id}"
        )

        more_columns = st.columns([2, 2, 4])
        edit_status = more_columns[0].selectbox(
            "Status",
            BOOKING_STATUSES,
            index=BOOKING_STATUSES.index(booking.status),
            key=f"edit_status_{booking.id}",
        )
        edit_total = more_columns[1].number_input(
            "Total charged", min_value=0.0, step=100.0,
            value=float(booking.total_price or 0), key=f"edit_total_{booking.id}",
        )
        edit_notes = more_columns[2].text_input(
            "Notes", value=booking.notes, key=f"edit_notes_{booking.id}"
        )
        edit_guest = client_picker(
            f"edit_client_{booking.id}", current=clients_by_id.get(booking.client_id)
        )

        moved = (edit_unit.id, edit_check_in, edit_check_out) != (
            booking.unit_id, booking.check_in, booking.check_out
        )
        blocked_reason = ""
        if moved and edit_check_out > edit_check_in:
            recheck = is_available(
                edit_unit.id,
                edit_check_in,
                edit_check_out,
                queries.list_bookings(
                    edit_check_in - timedelta(days=14),
                    edit_check_out + timedelta(days=14),
                    unit_ids=[edit_unit.id],
                ),
                queries.list_turnover_rules(edit_unit.id),
                seasons,
                queries.list_unit_blocks(
                    edit_check_in - timedelta(days=14), edit_check_out + timedelta(days=14)
                ),
                # A booking being moved must not be treated as blocking itself.
                ignore_booking_id=booking.id,
            )
            if not recheck.available:
                blocked_reason = recheck.reason
                st.error(recheck.reason)

        save_column, delete_column = st.columns([1, 1])
        if save_column.button("Save changes", type="primary", key=f"save_{booking.id}"):
            if edit_check_out <= edit_check_in:
                st.error("Check-out must be after check-in.")
            elif blocked_reason:
                st.error("Those dates are not free - nothing was saved.")
            else:
                try:
                    queries.update_booking(
                        booking.id,
                        unit_id=edit_unit.id,
                        client_id=edit_guest.commit(),
                        check_in=edit_check_in,
                        check_out=edit_check_out,
                        status=edit_status,
                        total_price=Decimal(str(edit_total)) if edit_total else None,
                        notes=edit_notes.strip(),
                    )
                except queries.BookingClash as clash:
                    st.error(str(clash))
                else:
                    st.success(f"Booking #{booking.id} updated.")
                    st.rerun()

        with delete_column.popover("Delete"):
            st.caption(
                "Only for something entered by mistake. A stay that was booked and then "
                "called off should be set to Cancelled instead, so the history survives."
            )
            if st.button("Delete permanently", key=f"delete_{booking.id}"):
                queries.delete_booking(booking.id)
                st.success(f"Booking #{booking.id} deleted.")
                st.rerun()
