"""Quotes already sent: reopen, resend, and chase the ones going quiet (spec 3.5).

The follow-up flag is worked out each time this page loads rather than stored,
so it is always true without anything having to run overnight: a quote still
unanswered a week after it went out is flagged here, and nowhere else does
anything to it. It does not expire, cancel or delete.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from db import queries
from lib.availability import is_available
from lib.models import (
    CANCELLED,
    QUOTE_ACCEPTED,
    QUOTE_CANCELLED,
    QUOTE_OPEN,
    QUOTE_STATUSES,
)
from lib.quotes import FOLLOW_UP_DAYS, days_waiting, needs_follow_up, quote_message
from ui import page
from ui.format import CURRENCY, date_range, money, nights as night_count
from ui.pdf import quote_pdf

page.start("Quotes")

quotes = queries.list_quotes()
if not quotes:
    st.info("No quotes yet. They are created from the Availability search page.")
    st.stop()

units = {unit.id: unit for unit in queries.list_units(include_inactive=True)}
clients = {client.id: client for client in queries.list_clients()}
today = date.today()

waiting = [q for q in quotes if needs_follow_up(q.status, q.generated_on, today)]
open_quotes = [q for q in quotes if q.status == QUOTE_OPEN]

summary = st.columns(3)
summary[0].metric("Open quotes", len(open_quotes))
summary[1].metric("Needing a follow-up", len(waiting))
summary[2].metric(
    "Accepted", sum(1 for q in quotes if q.status == QUOTE_ACCEPTED)
)

if waiting:
    st.warning(
        f"{len(waiting)} quote(s) have been waiting {FOLLOW_UP_DAYS} days or more with no answer: "
        + ", ".join(
            f"#{q.id} {units[q.unit_id].name} ({days_waiting(q.generated_on, today)} days)"
            for q in waiting[:6]
        )
        + ("..." if len(waiting) > 6 else "")
    )

# --- The list -------------------------------------------------------------

# Accepted quotes stay in view by default: accepting one is the moment you
# most want to see it confirm itself, and filtering it away the instant it is
# answered makes the page look like the click did nothing.
status_filter = st.multiselect(
    "Status", QUOTE_STATUSES, default=[QUOTE_OPEN, QUOTE_ACCEPTED]
)
listed = [q for q in quotes if not status_filter or q.status in status_filter]

st.dataframe(
    pd.DataFrame(
        [
            {
                "Ref": quote.id,
                "Flat": units[quote.unit_id].name,
                "Client": (clients[quote.client_id].name
                           if quote.client_id in clients else "-"),
                "Dates": date_range(quote.check_in, quote.check_out),
                "Nights": quote.nights,
                "Total": money(quote.total),
                "Sent": quote.generated_on,
                "Status": quote.status.title(),
                "Follow up": (
                    f"{days_waiting(quote.generated_on, today)} days"
                    if needs_follow_up(quote.status, quote.generated_on, today)
                    else ""
                ),
            }
            for quote in listed
        ]
    ),
    hide_index=True,
    use_container_width=True,
)

# --- Reopening one --------------------------------------------------------

if not listed:
    st.stop()

st.divider()
labels = {
    f"#{q.id} - {units[q.unit_id].name} - {date_range(q.check_in, q.check_out)} "
    f"- {money(q.total)}": q.id
    for q in listed
}
chosen = st.selectbox("Open a quote", list(labels))
quote = queries.get_quote(labels[chosen])

if quote is None:
    st.error("That quote could not be loaded.")
    st.stop()

unit = units[quote.unit_id]
client = clients.get(quote.client_id)
client_name = client.name if client else "there"

heading = st.columns([3, 2, 2])
heading[0].markdown(f"### {unit.name}")
heading[1].metric("Total", money(quote.total))
heading[2].metric("Nights", quote.nights)

st.caption(
    f"Sent {quote.generated_on.strftime('%d %B %Y')} to {client_name}"
    + (f" - {client.phone}" if client and client.phone else "")
    + f" - {night_count(quote.nights)} from {quote.check_in.strftime('%d %b')} "
    f"to {quote.check_out.strftime('%d %b %Y')}"
)

# The lines as they were quoted, not as today's rate file would price them.
st.dataframe(
    pd.DataFrame(
        [
            {
                "Season": line.season_label,
                "From": line.first_night,
                "To": line.last_night,
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
st.caption(
    "Shown as it was quoted. Changing the rate file does not change a quote "
    "already sent."
)

message = quote_message(
    unit.name, client_name, quote.check_in, quote.check_out,
    quote.lines, quote.total, quote.guests, CURRENCY, quote.id,
)
with st.expander("Resend - copy the message or download the PDF", expanded=False):
    st.code(message, language="text")
    st.download_button(
        "Download PDF",
        data=quote_pdf(
            unit.name, client_name, quote.check_in, quote.check_out,
            quote.lines, quote.total, quote.guests, quote.id, quote.generated_on,
            notes=quote.notes,
        ),
        file_name=f"quote-{quote.id}-{unit.name.lower().replace(' ', '-')}.pdf",
        mime="application/pdf",
    )

# --- Answering it ---------------------------------------------------------

st.markdown("**Did they take it?**")

if quote.booking_id is not None:
    booking = queries.get_booking(quote.booking_id)
    if booking is None:
        st.warning(f"This quote was accepted, but booking #{quote.booking_id} no longer exists.")
    elif booking.status == CANCELLED:
        st.warning(f"Booking #{booking.id} was made from this quote and has since been cancelled.")
    else:
        st.success(
            f"Accepted - booking #{booking.id} holds {unit.name} for these dates. "
            "It is on the calendar."
        )

# A quote holds nothing, so the flat may have gone since it was sent. Checked
# before offering to accept, rather than after the guest has been told yes.
clash = None
if quote.booking_id is None and quote.status != QUOTE_CANCELLED:
    window = (quote.check_in - timedelta(days=14), quote.check_out + timedelta(days=14))
    availability = is_available(
        quote.unit_id,
        quote.check_in,
        quote.check_out,
        queries.list_bookings(*window, unit_ids=[quote.unit_id]),
        queries.list_turnover_rules(quote.unit_id),
        queries.list_seasons(),
        queries.list_unit_blocks(*window),
    )
    if not availability.available:
        clash = availability
        st.error(
            f"{availability.reason} These dates are no longer free, so this quote "
            "cannot be turned into a booking. Search again for something else to offer."
        )

answer = st.columns([3, 2, 3])
if quote.booking_id is None and quote.status != QUOTE_CANCELLED:
    if answer[0].button(
        "Accept and book it", type="primary", disabled=clash is not None
    ):
        if clash is not None:
            st.error("Those dates are not free - nothing was booked.")
        else:
            try:
                booking_id = queries.accept_quote(quote, notes=f"From quote #{quote.id}")
            except queries.BookingClash as taken:
                st.error(str(taken))
            else:
                st.success(f"Booked as #{booking_id}. The calendar now shows it.")
                st.rerun()

if quote.status != QUOTE_CANCELLED and answer[1].button("Mark cancelled"):
    queries.cancel_quote(quote.id, quote.booking_id)
    st.rerun()

if quote.booking_id is not None:
    st.caption(
        "Cancelling this quote also cancels the booking it made, so the flat stops "
        "being held on the calendar."
    )
