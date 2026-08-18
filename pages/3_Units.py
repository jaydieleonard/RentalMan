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

owners = queries.list_owners()
owners_by_id = {owner.id: owner for owner in owners}
units = queries.list_units(include_inactive=True)

flats_tab, rates_tab, turnover_tab, owners_tab = st.tabs(
    ["Flats", "Client rates", "Turnover & blocks", "Owners"]
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
            entered = {}
            for label in SEASON_LABELS:
                current = existing.get(label)
                columns = st.columns([1, 2, 2])
                columns[0].markdown(f"**{label}**")
                entered[label] = (
                    columns[1].number_input(
                        f"{label} nightly rate", min_value=0.0, step=50.0,
                        value=float(current.nightly_rate) if current else 0.0,
                        label_visibility="collapsed", key=f"rate_{label}",
                    ),
                    columns[2].number_input(
                        f"{label} minimum nights", min_value=0, step=1,
                        value=current.min_nights if current and current.min_nights else 0,
                        label_visibility="collapsed", key=f"min_{label}",
                        help="0 means this season asks for nothing beyond the flat's own minimum.",
                    ),
                )
            st.caption(
                "Left: nightly rate. Right: this season's own minimum nights. On a stay "
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

# --- Turnover rules and blocks -------------------------------------------

with turnover_tab:
    st.caption(
        "How long a flat needs between one guest leaving and the next arriving. "
        "Same-day turnover - out in the morning, cleaned at midday, in that afternoon - "
        "is the normal arrangement, so 0 is the default. Set 1 or more only for a flat "
        "that genuinely cannot be turned around inside that window."
    )
    if not units:
        page.no_data("flats", "Flats tab")
    else:
        unit_name = st.selectbox("Flat", [unit.name for unit in units], key="turnover_unit")
        unit = next(u for u in units if u.name == unit_name)
        rules = {rule.season_label: rule.buffer_nights for rule in queries.list_turnover_rules(unit.id)}

        with st.form("turnover_rules"):
            default_buffer = st.number_input(
                "Buffer nights - all seasons", min_value=0, max_value=7, step=1,
                value=rules.get(None, 0),
                help="0 = same-day turnover allowed.",
            )
            st.markdown("**Season overrides** (leave matching the default to keep it simple)")
            columns = st.columns(3)
            season_values = {
                label: columns[index].number_input(
                    f"{label} season", min_value=-1, max_value=7, step=1,
                    value=rules.get(label, -1),
                    help="-1 means no override: this season uses the all-seasons buffer.",
                )
                for index, label in enumerate(SEASON_LABELS)
            }
            if st.form_submit_button("Save turnover rules", type="primary"):
                queries.save_turnover_rule(unit.id, None, int(default_buffer))
                for label, value in season_values.items():
                    if value >= 0:
                        queries.save_turnover_rule(unit.id, label, int(value))
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
