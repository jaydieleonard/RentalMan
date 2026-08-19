"""Guest records, and what each one's history adds up to (spec 3.6).

The reason for keeping them is the repeat guest. Knowing that the family
asking about March stayed twice last year, and what they paid, turns a quote
into a conversation - so this page is built around finding somebody quickly
and then seeing everything about them on one screen.

Nothing here is a second place to create a guest. New ones are made where the
booking or the quote is, which is where their name comes up naturally.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from db import queries
from lib.clients import summarise
from ui import page
from ui.format import date_range, money, nights as night_count

page.start("Guests")

today = date.today()

# Held over the rerun that follows a merge, so the result is readable.
outcome = st.session_state.pop("client_outcome", None)
if outcome:
    st.success(outcome)

search = st.text_input(
    "Find a guest", placeholder="Name, phone or email - leave blank to see everyone"
)
found = queries.list_clients_with_stays(search)

if not found:
    if search.strip():
        st.info(f"Nobody on file matches '{search.strip()}'.")
    else:
        st.info(
            "No guests yet. They are added as you take a booking or make a quote, "
            "so there is nothing to fill in here first."
        )
    st.stop()

repeat = [row for row in found if (row["stays"] or 0) > 1]
summary = st.columns(3)
summary[0].metric("Guests found", len(found))
summary[1].metric("Repeat guests", len(repeat))
summary[2].metric(
    "Stayed before", sum(1 for row in found if (row["stays"] or 0) > 0)
)

st.dataframe(
    pd.DataFrame(
        [
            {
                "Name": row["name"],
                "Phone": row["phone"],
                "Email": row["email"],
                "Stays": row["stays"] or 0,
                "Last here": row["last_stay"] or "",
            }
            for row in found
        ]
    ),
    hide_index=True,
    use_container_width=True,
)
if len(found) >= 50:
    st.caption("Showing the first 50. Narrow the search to see others.")

# --- One guest ------------------------------------------------------------

st.divider()
labels = {
    f"{row['name']}" + (f"  ({row['phone']})" if row["phone"] else ""): row for row in found
}
chosen = st.selectbox("Open a guest", list(labels))
client = labels[chosen]

bookings = queries.bookings_for_client(client["id"])
quotes = queries.quotes_for_client(client["id"])
history = summarise(bookings, quotes, today)
units = {unit.id: unit.name for unit in queries.list_units(include_inactive=True)}

heading = st.columns([3, 2, 2, 2])
heading[0].markdown(f"### {client['name']}")
heading[1].metric("Stays", history.stays)
heading[2].metric("Nights", history.nights)
heading[3].metric("Spent with us", money(history.spent))

st.caption(history.describe(today))
if history.is_repeat_guest:
    st.success("A repeat guest - worth saying so when you answer.")
if history.open_quotes:
    st.info(f"{history.open_quotes} quote(s) still waiting on an answer from them.")
if history.cancelled:
    st.caption(f"{history.cancelled} cancelled booking(s) on the record.")

details, stays_tab, quotes_tab = st.tabs(["Contact details", "Stays", "Quotes"])

with details:
    with st.form(f"edit_client_{client['id']}"):
        columns = st.columns([3, 2, 3])
        name = columns[0].text_input("Name", value=client["name"])
        phone = columns[1].text_input("Phone", value=client["phone"])
        email = columns[2].text_input("Email", value=client["email"])
        notes = st.text_area(
            "Notes", value=client["notes"], height=90,
            placeholder="Anything worth remembering next time - a favourite flat, "
                        "travels with a dog, always asks for a late checkout",
        )
        if st.form_submit_button("Save", type="primary"):
            if not name.strip():
                st.error("The guest needs a name.")
            else:
                queries.update_client(
                    client["id"], name=name.strip(), phone=phone.strip(),
                    email=email.strip(), notes=notes.strip(),
                )
                st.rerun()

with stays_tab:
    if not bookings:
        st.caption("No bookings on this record yet.")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Ref": booking.id,
                        "Flat": units.get(booking.unit_id, "?"),
                        "Dates": date_range(booking.check_in, booking.check_out),
                        "Nights": booking.nights,
                        "Status": booking.status.title(),
                        "Total": money(booking.total_price),
                        "Notes": booking.notes,
                    }
                    for booking in bookings
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
        favourite = max(
            {units.get(b.unit_id, "?") for b in bookings},
            key=lambda name: sum(1 for b in bookings if units.get(b.unit_id) == name),
        )
        if history.stays > 1:
            st.caption(f"Usually stays in {favourite}.")

with quotes_tab:
    if not quotes:
        st.caption("No quotes on this record yet.")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Ref": quote.id,
                        "Flat": units.get(quote.unit_id, "?"),
                        "Dates": date_range(quote.check_in, quote.check_out),
                        "Nights": night_count(quote.nights),
                        "Total": money(quote.total),
                        "Sent": quote.generated_on,
                        "Status": quote.status.title(),
                    }
                    for quote in quotes
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )

# --- Two records, one person ---------------------------------------------

st.divider()
with st.expander("This is the same person as another record"):
    st.caption(
        "Typing a name slightly differently makes a second record, and two "
        "half-histories are worse than one whole one. Everything - bookings and "
        "quotes - moves onto the record you keep, and the duplicate goes."
    )
    others = [row for row in found if row["id"] != client["id"]]
    if not others:
        st.caption("Nobody else is listed to merge with. Widen the search above first.")
    else:
        other_labels = {
            f"{row['name']}"
            + (f"  ({row['phone']})" if row["phone"] else "")
            + f"  -  {row['stays'] or 0} stay(s)": row
            for row in others
        }
        duplicate = other_labels[st.selectbox("Duplicate record", list(other_labels))]
        st.warning(
            f"**{duplicate['name']}** will be removed, and their "
            f"{duplicate['stays'] or 0} stay(s) and any quotes will move onto "
            f"**{client['name']}**."
        )
        if st.button("Merge them", type="primary"):
            moved = queries.merge_clients(duplicate["id"], client["id"])
            st.session_state.client_outcome = (
                f"Merged {duplicate['name']} into {client['name']} - "
                f"{moved} record(s) moved across."
            )
            st.rerun()

if not bookings and not quotes:
    with st.expander("Remove this record"):
        st.caption(
            "Only for one created by mistake. A guest with any history should be "
            "merged into the right record rather than deleted."
        )
        if st.button("Delete permanently"):
            queries.delete_client(client["id"])
            st.session_state.client_outcome = f"Removed {client['name']}."
            st.rerun()
