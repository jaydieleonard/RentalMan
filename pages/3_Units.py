"""The flats themselves: details, client rates, turnover rules and owners.

Spec 3.4, 3.7 and 3.10. Owner records live here for now because a flat cannot
be added without one; Phase 5 gives owners their own page alongside owner rates
and statements, and this tab moves there.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import pandas as pd
import streamlit as st

from db import queries
from lib.models import SEASON_LABELS
from ui import page
from ui.format import money

page.start("Units")

#: Buffers written out in words. The database stores a number of nights; nobody
#: setting one up should have to know that 0 means "same day".
BUFFER_WORDING = {
    0: "Same day - out in the morning, cleaned, in that afternoon",
    1: "1 night free in between",
    2: "2 nights free in between",
    3: "3 nights free in between",
}
SAME_AS_ALL_YEAR = "Same as the rest of the year"

owners = queries.list_owners()
owners_by_id = {owner.id: owner for owner in owners}
units = queries.list_units(include_inactive=True)

flats_tab, rates_tab, owner_rates_tab, turnover_tab, owners_tab = st.tabs(
    ["Flats", "Client rates", "Owner rates", "Turnover & blocks", "Owners"]
)

# --- Flats ----------------------------------------------------------------

with flats_tab:
    if not owners:
        st.warning("Add an owner first - every flat belongs to exactly one.")
    else:
        if units:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Flat": unit.name,
                            "Beds": unit.beds,
                            "Sleeps": unit.sleeps,
                            "Owner": owners_by_id[unit.owner_id].name,
                            "Group": unit.group_tag,
                            "Min nights": unit.min_nights,
                            "Management fee": money(unit.monthly_management_fee),
                            "Active": "Yes" if unit.active else "No",
                        }
                        for unit in units
                    ]
                ),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("No flats yet. Add the first one below.")

        with st.expander("Add a flat"):
            with st.form("add_unit", clear_on_submit=True):
                name = st.text_input("Name", placeholder="e.g. Seaview 3")
                columns = st.columns(4)
                beds = columns[0].number_input("Beds", min_value=1, value=2, step=1)
                sleeps = columns[1].number_input("Sleeps", min_value=1, value=4, step=1)
                min_nights = columns[2].number_input(
                    "Minimum nights", min_value=1, value=2, step=1,
                    help="2 for most flats; 1 for the one that takes single nights.",
                )
                fee = columns[3].number_input(
                    "Monthly management fee", min_value=0.0, value=0.0, step=100.0,
                    help="Negotiated per flat - a flat amount, not a percentage.",
                )
                owner_name = st.selectbox("Owner", [owner.name for owner in owners])
                group_tag = st.text_input("Group / area (optional)", help="Used to filter the calendar.")
                times = st.columns(2)
                checkout_time = times[0].time_input("Checkout time", value=time(10, 0))
                checkin_time = times[1].time_input("Check-in time", value=time(14, 0))
                notes = st.text_area("Notes", height=80)

                if st.form_submit_button("Add flat", type="primary"):
                    if not name.strip():
                        st.error("The flat needs a name.")
                    else:
                        owner_id = next(o.id for o in owners if o.name == owner_name)
                        queries.create_unit(
                            name.strip(), int(beds), int(sleeps), owner_id,
                            Decimal(str(fee)), int(min_nights),
                            checkout_time, checkin_time, group_tag.strip(), notes,
                        )
                        st.success(f"Added {name}.")
                        st.rerun()

        if units:
            with st.expander("Edit a flat"):
                chosen = st.selectbox("Flat", [unit.name for unit in units], key="edit_unit_pick")
                unit = next(u for u in units if u.name == chosen)
                with st.form("edit_unit"):
                    new_name = st.text_input("Name", value=unit.name)
                    columns = st.columns(4)
                    beds = columns[0].number_input("Beds", min_value=1, value=unit.beds, step=1)
                    sleeps = columns[1].number_input("Sleeps", min_value=1, value=unit.sleeps, step=1)
                    min_nights = columns[2].number_input(
                        "Minimum nights", min_value=1, value=unit.min_nights, step=1
                    )
                    fee = columns[3].number_input(
                        "Monthly management fee", min_value=0.0,
                        value=float(unit.monthly_management_fee), step=100.0,
                    )
                    owner_name = st.selectbox(
                        "Owner", [owner.name for owner in owners],
                        index=[o.id for o in owners].index(unit.owner_id),
                    )
                    group_tag = st.text_input("Group / area", value=unit.group_tag)
                    times = st.columns(2)
                    checkout_time = times[0].time_input(
                        "Checkout time", value=unit.checkout_time or time(10, 0)
                    )
                    checkin_time = times[1].time_input(
                        "Check-in time", value=unit.checkin_time or time(14, 0)
                    )
                    notes = st.text_area("Notes", value=unit.notes, height=80)
                    active = st.checkbox(
                        "Active", value=unit.active,
                        help="Inactive flats drop off the calendar but keep their history.",
                    )

                    if st.form_submit_button("Save changes", type="primary"):
                        queries.update_unit(
                            unit.id,
                            name=new_name.strip(),
                            beds=int(beds),
                            sleeps=int(sleeps),
                            owner_id=next(o.id for o in owners if o.name == owner_name),
                            monthly_management_fee=Decimal(str(fee)),
                            min_nights=int(min_nights),
                            checkout_time=checkout_time,
                            checkin_time=checkin_time,
                            group_tag=group_tag.strip(),
                            notes=notes,
                            active=active,
                        )
                        st.success("Saved.")
                        st.rerun()

# --- Client rates ---------------------------------------------------------

with rates_tab:
    st.caption(
        "What the guest is charged per night, per season. Rates are kept per year, "
        "so setting next year's does not disturb this year's."
    )
    if not units:
        page.no_data("flats", "Flats tab")
    else:
        picker = st.columns([3, 1])
        unit_name = picker[0].selectbox("Flat", [unit.name for unit in units], key="rate_unit")
        year = picker[1].number_input(
            "Year", min_value=2020, max_value=2100, value=date.today().year, step=1, key="rate_year"
        )
        unit = next(u for u in units if u.name == unit_name)
        existing = {
            rate.season_label: rate
            for rate in queries.list_client_rates(unit.id, int(year))
        }

        with st.form("client_rates"):
            # The two figures per row look alike, so they are headed rather
            # than explained underneath.
            headings = st.columns([1, 2, 2])
            headings[0].markdown("**Season**")
            headings[1].markdown("**Nightly rate**")
            headings[2].markdown("**Minimum nights**")

            entered = {}
            for label in SEASON_LABELS:
                current = existing.get(label)
                columns = st.columns([1, 2, 2])
                columns[0].markdown(f"**{label}**")
                entered[label] = (
                    columns[1].number_input(
                        f"{label} nightly rate", min_value=0.0, step=50.0,
                        value=float(current.nightly_rate) if current else 0.0,
                        label_visibility="collapsed", key=f"rate_{unit.id}_{int(year)}_{label}",
                    ),
                    columns[2].number_input(
                        f"{label} minimum nights", min_value=0, step=1,
                        value=current.min_nights if current and current.min_nights else 0,
                        label_visibility="collapsed", key=f"min_{unit.id}_{int(year)}_{label}",
                        help="0 means this season asks for nothing beyond the flat's own minimum.",
                    ),
                )
            st.caption(
                "Minimum nights is this season's own rule, on top of the flat's general "
                "minimum - leave it at 0 if the season asks for nothing extra. On a stay "
                "crossing seasons, the minimum of the highest-rated season touched applies."
            )
            if st.form_submit_button("Save rates", type="primary"):
                for label, (rate_value, minimum) in entered.items():
                    if rate_value > 0:
                        queries.save_client_rate(
                            unit.id, label, int(year), Decimal(str(rate_value)),
                            int(minimum) or None,
                        )
                    elif label in existing:
                        queries.delete_client_rate(unit.id, label, int(year))
                st.success(f"{year} rates saved for {unit.name}.")
                st.rerun()

# --- Owner rates ----------------------------------------------------------

with owner_rates_tab:
    st.caption(
        "What is due to the **owner** per night, per season. This is not the client "
        "rate less a cut - the business earns from the monthly management fee, so "
        "the two figures are set independently and neither follows the other."
    )
    if not units:
        page.no_data("flats", "Flats tab")
    else:
        picker = st.columns([3, 1])
        unit_name = picker[0].selectbox(
            "Flat", [unit.name for unit in units], key="owner_rate_unit"
        )
        year = picker[1].number_input(
            "Year", min_value=2020, max_value=2100, value=date.today().year, step=1,
            key="owner_rate_year",
        )
        unit = next(u for u in units if u.name == unit_name)
        existing = {
            rate.season_label: rate for rate in queries.list_owner_rates(unit.id, int(year))
        }
        charged = {
            rate.season_label: rate for rate in queries.list_client_rates(unit.id, int(year))
        }

        with st.form("owner_rates"):
            headings = st.columns([1, 2, 3])
            headings[0].markdown("**Season**")
            headings[1].markdown("**Due to owner, per night**")
            headings[2].markdown("**Charged to guest**")

            entered = {}
            for label in SEASON_LABELS:
                current = existing.get(label)
                columns = st.columns([1, 2, 3])
                columns[0].markdown(f"**{label}**")
                entered[label] = columns[1].number_input(
                    f"{label} owner rate", min_value=0.0, step=50.0,
                    value=float(current.nightly_rate) if current else 0.0,
                    label_visibility="collapsed",
                    key=f"owner_rate_{unit.id}_{int(year)}_{label}",
                )
                guest_rate = charged.get(label)
                columns[2].caption(
                    f"guest pays {money(guest_rate.nightly_rate)}" if guest_rate
                    else "no client rate set for this season"
                )

            if st.form_submit_button("Save owner rates", type="primary"):
                for label, amount in entered.items():
                    if amount > 0:
                        queries.save_owner_rate(unit.id, label, int(year), Decimal(str(amount)))
                    elif label in existing:
                        queries.delete_owner_rate(unit.id, label, int(year))
                st.success(f"{year} owner rates saved for {unit.name}.")
                st.rerun()

        st.caption(
            f"{unit.name} also carries a management fee of "
            f"{money(unit.monthly_management_fee)} a month, charged to the owner "
            "whether or not the flat was let. Change it on the Flats tab."
        )

# --- Turnover rules and blocks -------------------------------------------

with turnover_tab:
    st.caption(
        "How long a flat needs between one guest leaving and the next arriving. "
        "Same-day turnover is the normal arrangement and the default. Ask for a night "
        "in between only where a flat genuinely cannot be turned around between "
        "checkout and check-in. Whatever is set here decides both where the flat can "
        "be booked and when it gets cleaned."
    )
    if not units:
        page.no_data("flats", "Flats tab")
    else:
        unit_name = st.selectbox("Flat", [unit.name for unit in units], key="turnover_unit")
        unit = next(u for u in units if u.name == unit_name)
        rules = {rule.season_label: rule.buffer_nights for rule in queries.list_turnover_rules(unit.id)}

        with st.form("turnover_rules"):
            default_buffer = st.selectbox(
                "Between one guest leaving and the next arriving",
                options=list(BUFFER_WORDING),
                format_func=lambda nights: BUFFER_WORDING[nights],
                index=list(BUFFER_WORDING).index(rules.get(None, 0))
                if rules.get(None, 0) in BUFFER_WORDING
                else 0,
                key=f"turnover_{unit.id}_all",
            )

            st.markdown("**Different in a particular season?**")
            st.caption(
                "Most flats work the same way all year, so leave these alone unless one "
                "genuinely needs longer at a busier time - a bigger flat in high season, "
                "when the cleaners are stretched across everything at once."
            )
            columns = st.columns(3)
            season_choices = {}
            # The "no override" choice is its own string rather than None:
            # Streamlit already uses None for "nothing selected", so a None
            # option cannot be told apart from an empty box.
            options = [SAME_AS_ALL_YEAR, *BUFFER_WORDING]
            for index, label in enumerate(SEASON_LABELS):
                current = rules.get(label)
                season_choices[label] = columns[index].selectbox(
                    f"{label} season",
                    options=options,
                    format_func=lambda choice: choice if isinstance(choice, str)
                    else BUFFER_WORDING[choice],
                    index=options.index(current) if current in BUFFER_WORDING else 0,
                    key=f"turnover_{unit.id}_{label}",
                )

            if st.form_submit_button("Save turnover rules", type="primary"):
                queries.save_turnover_rule(unit.id, None, int(default_buffer))
                for label, chosen in season_choices.items():
                    if chosen == SAME_AS_ALL_YEAR:
                        # Back to the all-seasons setting: the override row has
                        # to go, or it would quietly keep applying.
                        queries.delete_turnover_rule(unit.id, label)
                    else:
                        queries.save_turnover_rule(unit.id, label, int(chosen))
                st.success(f"Turnover rules saved for {unit.name}.")
                st.rerun()

        st.divider()
        st.markdown("**Blocked dates** - maintenance, or the owner using the flat themselves.")
        blocks = [block for block in queries.list_unit_blocks() if block.unit_id == unit.id]
        if blocks:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "From": block.start_date,
                            "Until (exclusive)": block.end_date,
                            "Nights": (block.end_date - block.start_date).days,
                            "Reason": block.reason,
                        }
                        for block in blocks
                    ]
                ),
                hide_index=True,
                use_container_width=True,
            )
        with st.form("add_block", clear_on_submit=True):
            columns = st.columns([2, 2, 3])
            start = columns[0].date_input("From", value=date.today(), format="DD/MM/YYYY")
            end = columns[1].date_input("Until (guest-free through)", value=date.today(), format="DD/MM/YYYY")
            reason = columns[2].text_input("Reason", placeholder="e.g. bathroom retile")
            if st.form_submit_button("Block these dates"):
                if end <= start:
                    st.error("The end date must be after the start date.")
                else:
                    queries.create_unit_block(unit.id, start, end, reason.strip())
                    st.success("Dates blocked - they now show grey on the calendar.")
                    st.rerun()

# --- Owners ---------------------------------------------------------------

with owners_tab:
    st.caption(
        "Banking details are kept here for reference only, so you know where to pay. "
        "Nothing in this app moves money."
    )
    if owners:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Owner": owner.name,
                        "Phone": owner.phone,
                        "Email": owner.email,
                        "Flats": sum(1 for unit in units if unit.owner_id == owner.id),
                    }
                    for owner in owners
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("No owners yet.")

    with st.expander("Add an owner", expanded=not owners):
        with st.form("add_owner", clear_on_submit=True):
            name = st.text_input("Name")
            columns = st.columns(2)
            phone = columns[0].text_input("Phone")
            email = columns[1].text_input("Email")
            banking = st.text_area("Banking details (reference only)", height=80)
            notes = st.text_area("Notes", height=80)
            if st.form_submit_button("Add owner", type="primary"):
                if not name.strip():
                    st.error("The owner needs a name.")
                else:
                    queries.create_owner(name.strip(), phone, email, banking, notes)
                    st.success(f"Added {name}.")
                    st.rerun()
