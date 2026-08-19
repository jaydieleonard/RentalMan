"""Which flats are free for these dates, and what would they cost (spec 3.2).

The screen an enquiry lands on: dates in, a list of flats that can actually be
sold for them out, each already priced so the parents can answer the "how much"
question in the same breath as the "is it free" one.

A flat is only offered if it is free for every night *and* the turnover gap
around any neighbouring stay is clear *and* the stay meets the minimum-night
rules. The near-misses are shown separately rather than hidden - "free, but it
needs five nights in high season" is worth knowing when there is a guest on the
phone.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

import streamlit as st

from db import queries
from lib.availability import is_available
from lib.rates import MinimumStayError, PricingError, build_quote
from lib.quotes import quote_message
from lib.seasons import SeasonCalendarError
from ui import page
from ui.clients import client_picker
from ui.format import CURRENCY, money, nights as night_count
from ui.pdf import quote_pdf

page.start("Availability search")

units = queries.list_units()
if not units:
    page.no_data("units", "Units")
    st.stop()

# --- What are we looking for ---------------------------------------------

# Picking a check-in moves the check-out to the night after it, so the pair is
# never left invalid while the second date is still being chosen. Done in a
# callback because Streamlit refuses to have a widget's value rewritten once
# that widget exists - a callback runs before it is rebuilt, so it is allowed.
if "search_in" not in st.session_state:
    st.session_state.search_in = date.today()
if "search_out" not in st.session_state:
    st.session_state.search_out = date.today() + timedelta(days=1)


def follow_check_in() -> None:
    st.session_state.search_out = st.session_state.search_in + timedelta(days=1)


search = st.columns([2, 2, 1, 2])
check_in = search[0].date_input(
    "Check-in", key="search_in", format="DD/MM/YYYY", on_change=follow_check_in
)
check_out = search[1].date_input("Check-out", key="search_out", format="DD/MM/YYYY")
minimum_sleeps = search[2].number_input("Sleeps at least", min_value=0, value=0, step=1)
tags = sorted({unit.group_tag for unit in units if unit.group_tag})
chosen_tags = search[3].multiselect("Group", tags) if tags else []

if check_out <= check_in:
    st.error("Check-out must be after check-in.")
    st.stop()

st.caption(f"{night_count((check_out - check_in).days)}, arriving {check_in.strftime('%A %d %B %Y')}.")

# --- Work out what can be sold -------------------------------------------

window_start, window_end = check_in - timedelta(days=14), check_out + timedelta(days=14)
bookings = queries.list_bookings(window_start, window_end)
rules = queries.list_turnover_rules()
blocks = queries.list_unit_blocks(window_start, window_end)
seasons = queries.list_seasons()

rates_by_unit: dict[int, list] = defaultdict(list)
for rate in queries.list_client_rates():
    rates_by_unit[rate.unit_id].append(rate)

offerable, too_short, unpriced, taken = [], [], [], []

for unit in units:
    if minimum_sleeps and unit.sleeps < minimum_sleeps:
        continue
    if chosen_tags and unit.group_tag not in chosen_tags:
        continue

    availability = is_available(
        unit.id, check_in, check_out, bookings, rules, seasons, blocks
    )
    if not availability.available:
        taken.append((unit, availability))
        continue

    try:
        quote = build_quote(unit, seasons, rates_by_unit[unit.id], check_in, check_out)
    except MinimumStayError as short:
        too_short.append((unit, short.check))
    except (PricingError, SeasonCalendarError) as problem:
        unpriced.append((unit, str(problem)))
    else:
        offerable.append((unit, quote))

offerable.sort(key=lambda pair: pair[1].total)

# Reserved now, filled at the end of the file: picking a flat should put the
# quote in front of you, not below fifteen rows of search results.
quote_panel = st.container()

# --- What we can offer ----------------------------------------------------

st.subheader(f"{len(offerable)} flat(s) available")

if not offerable:
    st.info("Nothing is free for these dates that also meets the minimum-stay rules.")
else:
    heading = st.columns([4, 2, 2, 2, 2])
    for column, label in zip(heading, ["Flat", "Sleeps", "Group", "Total", ""]):
        column.markdown(f"**{label}**" if label else "")

    for unit, quote in offerable:
        row = st.columns([4, 2, 2, 2, 2])
        row[0].markdown(f"**{unit.name}**")
        row[1].write(f"{unit.sleeps} ({unit.beds} bed)")
        row[2].write(unit.group_tag or "-")
        row[3].markdown(f"**{money(quote.total)}**  \n<small>{money(quote.total / quote.nights)}"
                        f" / night</small>", unsafe_allow_html=True)
        if row[4].button("Quote this", key=f"quote_{unit.id}", type="primary"):
            st.session_state.quote_target = unit.id
            st.session_state.quote_dates = (check_in, check_out)
            st.rerun()

# --- Near misses, worth knowing about ------------------------------------

if too_short:
    with st.expander(f"{len(too_short)} flat(s) free, but the stay is too short"):
        for unit, check in too_short:
            st.write(f"**{unit.name}** - {check.explain()}")

if unpriced:
    with st.expander(f"{len(unpriced)} flat(s) free, but cannot be priced", expanded=True):
        st.caption("These are available. The rate file or the season calendar needs filling in.")
        for unit, problem in unpriced:
            st.warning(f"**{unit.name}**: {problem}")

if taken:
    with st.expander(f"{len(taken)} flat(s) not available"):
        for unit, availability in taken:
            st.write(f"**{unit.name}** - {availability.reason}")

# --- Turning a chosen flat into a quote ----------------------------------

with quote_panel:
    finished = st.session_state.get("saved_quote_id")
    target_id = st.session_state.get("quote_target")

    if finished:
        saved = queries.get_quote(finished)
        if saved is None:
            st.session_state.pop("saved_quote_id", None)
        else:
            unit = next(u for u in units if u.id == saved.unit_id)
            client = queries.get_client(saved.client_id) if saved.client_id else None
            client_name = client.name if client else "there"

            st.success(f"Quote #{saved.id} saved for {unit.name}.")
            message = quote_message(
                unit.name, client_name, saved.check_in, saved.check_out,
                saved.lines, saved.total, saved.guests, CURRENCY, saved.id,
            )
            st.markdown("**Copy this into WhatsApp or an email**")
            st.code(message, language="text")

            buttons = st.columns([2, 2, 4])
            buttons[0].download_button(
                "Download PDF",
                data=quote_pdf(
                    unit.name, client_name, saved.check_in, saved.check_out,
                    saved.lines, saved.total, saved.guests, saved.id, saved.generated_on,
                    notes=saved.notes,
                ),
                file_name=f"quote-{saved.id}-{unit.name.lower().replace(' ', '-')}.pdf",
                mime="application/pdf",
            )
            if buttons[1].button("Start another quote"):
                st.session_state.pop("saved_quote_id", None)
                st.session_state.pop("quote_target", None)
                st.rerun()
            st.divider()

    elif target_id:
        unit = next(u for u in units if u.id == target_id)
        quoted_in, quoted_out = st.session_state.get("quote_dates", (check_in, check_out))
        quote = build_quote(unit, seasons, rates_by_unit[unit.id], quoted_in, quoted_out)

        st.subheader(f"Quote for {unit.name}")
        st.caption(
            f"{quoted_in.strftime('%d %b %Y')} to {quoted_out.strftime('%d %b %Y')} - "
            f"{night_count(quote.nights)}, {money(quote.total)}"
        )
        for line in quote.lines:
            st.write(
                f"- {line.nights} x {money(line.nightly_rate)} ({line.season_label} season) "
                f"= **{money(line.subtotal)}**"
            )

        guest = client_picker(f"quote_client_{unit.id}")
        entry = st.columns([1, 4])
        guests = entry[0].number_input("Guests", min_value=1, value=min(2, unit.sleeps), step=1)
        note = entry[1].text_input("Note on the quote (optional)")

        actions = st.columns([2, 2, 4])
        if actions[0].button("Save quote", type="primary"):
            if not guest.is_usable:
                st.error("Give the guest a name, or pick one already on file.")
            else:
                st.session_state.saved_quote_id = queries.save_quote(
                    unit.id, guest.commit(), quoted_in, quoted_out, int(guests),
                    quote.total, quote.lines, note.strip(),
                )
                st.rerun()
        if actions[1].button("Cancel"):
            st.session_state.pop("quote_target", None)
            st.rerun()
        st.divider()
