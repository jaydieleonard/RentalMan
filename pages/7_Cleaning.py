"""The cleaning calendar: who is cleaning what, and when (spec 3.9, 3.10).

Jobs are normally generated from the bookings by the rules in lib.cleaning,
which read the same Turnover Rule the availability search uses - so a flat that
takes same-day guests gets a changeover clean, and one that needs a clear day
gets a post-clean and a pre-clean instead, without the two ever disagreeing.

Generating never touches a job that is already there. A job moved to another
day or handed to somebody else was moved by a person who knew something the
rules did not.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import streamlit as st

from db import queries
from lib.cleaning import cost_for, plan_for_unit
from lib.models import CLEAN_TYPES, JOB_STATUSES
from ui import page
from ui.format import money
from ui.grid import render_cleaning_grid

page.start("Cleaning")

units = queries.list_units()
if not units:
    page.no_data("units", "Units")
    st.stop()

units_by_id = {unit.id: unit for unit in units}
staff = queries.list_cleaning_staff(include_inactive=True)
staff_names = {member.id: member.name for member in staff}
service_types = queries.list_service_types()
standard_costs = {service.label: service.standard_cost for service in service_types}

calendar_tab, jobs_tab, staff_tab, costs_tab = st.tabs(
    ["Calendar", "Jobs", "Cleaners", "Services & costs"]
)

# --- The month at a glance -----------------------------------------------

with calendar_tab:
    if "cleaning_month" not in st.session_state:
        st.session_state.cleaning_month = date.today().replace(day=1)

    anchor = st.session_state.cleaning_month
    back, this_month, forward, _ = st.columns([1, 1, 1, 3])
    if back.button("< Previous", use_container_width=True):
        st.session_state.cleaning_month = (anchor - timedelta(days=1)).replace(day=1)
        st.rerun()
    if this_month.button("This month", use_container_width=True):
        st.session_state.cleaning_month = date.today().replace(day=1)
        st.rerun()
    if forward.button("Next >", use_container_width=True):
        last = calendar.monthrange(anchor.year, anchor.month)[1]
        st.session_state.cleaning_month = anchor.replace(day=last) + timedelta(days=1)
        st.rerun()

    anchor = st.session_state.cleaning_month
    days_in_month = calendar.monthrange(anchor.year, anchor.month)[1]
    month_end = anchor + timedelta(days=days_in_month)
    days = [anchor + timedelta(days=offset) for offset in range(days_in_month)]

    st.subheader(anchor.strftime("%B %Y"))

    who = st.selectbox(
        "Show", ["Everyone"] + [member.name for member in staff] + ["Nobody assigned yet"]
    )
    jobs = queries.list_cleaning_jobs(anchor, month_end)
    if who == "Nobody assigned yet":
        jobs = [job for job in jobs if job.staff_id is None]
    elif who != "Everyone":
        chosen = next(member.id for member in staff if member.name == who)
        jobs = [job for job in jobs if job.staff_id == chosen]

    by_unit: dict[int, dict[date, list]] = {}
    for job in jobs:
        by_unit.setdefault(job.unit_id, {}).setdefault(job.date, []).append(job)

    st.markdown(
        render_cleaning_grid(units, days, by_unit, staff_names, date.today()),
        unsafe_allow_html=True,
    )

    unassigned = [job for job in jobs if job.staff_id is None]
    if unassigned:
        st.warning(
            f"{len(unassigned)} job(s) this month have nobody assigned yet - "
            "they show grey with a question mark."
        )

    # The bottom row of the grid counts each day; this says what the month adds
    # up to and which day is worst, which is the question behind the question -
    # whether the cleaners can actually get through it.
    per_day: dict[date, int] = {}
    for job in jobs:
        per_day[job.date] = per_day.get(job.date, 0) + 1

    summary = st.columns(3)
    summary[0].metric("Cleans this month", len(jobs))
    if per_day:
        heaviest_day = max(per_day, key=lambda day: per_day[day])
        summary[1].metric("Busiest day", heaviest_day.strftime("%a %d %b"))
        summary[2].metric("Cleans on that day", per_day[heaviest_day])
        working_days = len(per_day)
        st.caption(
            f"Spread over {working_days} day(s) - an average of "
            f"{len(jobs) / working_days:.1f} a day on the days anything happens. "
            "The bottom row of the grid is the total for each day; hover a cell "
            "to see the clean, who has it, and whether it is done."
        )
    else:
        st.caption(
            "Nothing scheduled this month. Work the cleans out from the bookings "
            "on the Jobs tab."
        )

# --- Generating and adjusting jobs ---------------------------------------

with jobs_tab:
    st.markdown("**Work the cleans out from the bookings**")
    st.caption(
        "Reads the flats' turnover rules and the stays on the calendar, and adds "
        "anything missing. A flat gets at most one clean a day - where two would "
        "fall together, the guest's clean stays put and the deep clean or mid-stay "
        "tidy moves to the next free day. Jobs already scheduled are left exactly "
        "as they are, including ones you have moved or reassigned by hand."
    )

    span = st.columns([2, 2, 2])
    from_date = span[0].date_input(
        "From", value=date.today().replace(day=1), format="DD/MM/YYYY", key="gen_from"
    )
    to_date = span[1].date_input(
        "Until", value=date.today().replace(day=1) + timedelta(days=62),
        format="DD/MM/YYYY", key="gen_to",
    )

    if span[2].button("Work out the cleans", type="primary"):
        if to_date <= from_date:
            st.error("The end date must be after the start date.")
        else:
            bookings = queries.list_bookings(from_date - timedelta(days=30), to_date + timedelta(days=30))
            rules = queries.list_turnover_rules()
            seasons = queries.list_seasons()
            overrides = {
                (rate.unit_id, rate.service_label): rate.cost
                for rate in queries.list_unit_cleaning_rates()
            }

            planned = []
            for unit in units:
                settings = queries.get_cleaning_settings(unit.id)
                planned.extend(
                    plan_for_unit(
                        unit.id, from_date, to_date, bookings, rules, seasons,
                        light_after=settings["light_after_nights"],
                        light_every=settings["light_every_nights"],
                        deep_every_days=settings["deep_every_days"] or None,
                        last_deep_clean=queries.last_deep_clean(unit.id),
                    )
                )

            costs = {
                (job.unit_id, job.service_label): cost_for(
                    job.unit_id, job.service_label, standard_costs, overrides
                )
                for job in planned
            }
            added = queries.schedule_jobs(planned, costs)
            st.success(
                f"{len(planned)} clean(s) needed over that period; {added} added. "
                f"{len(planned) - added} were already on the calendar."
            )
            st.rerun()

    st.divider()

    filters = st.columns([2, 2, 2, 2])
    list_from = filters[0].date_input(
        "Showing from", value=date.today(), format="DD/MM/YYYY", key="jobs_from"
    )
    list_to = filters[1].date_input(
        "to", value=date.today() + timedelta(days=30), format="DD/MM/YYYY", key="jobs_to"
    )
    status_filter = filters[2].multiselect("Status", JOB_STATUSES, default=["scheduled"])
    unit_filter = filters[3].selectbox("Flat", ["All flats"] + [u.name for u in units])

    listed = queries.list_cleaning_jobs(
        list_from, list_to + timedelta(days=1),
        unit_ids=None if unit_filter == "All flats"
        else [next(u.id for u in units if u.name == unit_filter)],
        statuses=status_filter or None,
    )

    st.caption(f"{len(listed)} job(s).")
    if listed:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Date": job.date,
                        "Flat": units_by_id[job.unit_id].name,
                        "Clean": job.service_label,
                        "Cleaner": staff_names.get(job.staff_id, "-"),
                        "Status": job.status.title(),
                        "Cost": money(job.cost),
                        "Why": job.notes,
                    }
                    for job in listed
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )

    if listed:
        st.divider()
        st.markdown("**Move, reassign or tick one off**")
        labels = {
            f"#{job.id}  {job.date}  {units_by_id[job.unit_id].name}  -  {job.service_label}": job
            for job in listed
        }
        chosen = st.selectbox("Job", list(labels), key="job_pick")
        job = labels[chosen]

        edit = st.columns([2, 2, 2, 2])
        new_date = edit[0].date_input(
            "Date", value=job.date, format="DD/MM/YYYY", key=f"job_date_{job.id}"
        )
        cleaner_names = ["Nobody yet"] + [member.name for member in staff]
        current_name = staff_names.get(job.staff_id, "Nobody yet")
        new_cleaner = edit[1].selectbox(
            "Cleaner", cleaner_names,
            index=cleaner_names.index(current_name) if current_name in cleaner_names else 0,
            key=f"job_staff_{job.id}",
        )
        new_status = edit[2].selectbox(
            "Status", JOB_STATUSES, index=JOB_STATUSES.index(job.status),
            key=f"job_status_{job.id}",
        )
        new_cost = edit[3].number_input(
            "Cost", min_value=0.0, step=25.0, value=float(job.cost), key=f"job_cost_{job.id}",
            help="Billed on to the owner's monthly statement.",
        )

        actions = st.columns([2, 2, 4])
        if actions[0].button("Save job", type="primary", key=f"job_save_{job.id}"):
            try:
                queries.update_cleaning_job(
                    job.id,
                    date=new_date,
                    staff_id=None if new_cleaner == "Nobody yet"
                    else next(m.id for m in staff if m.name == new_cleaner),
                    status=new_status,
                    cost=Decimal(str(new_cost)),
                )
            except queries.CleaningClash as clash:
                st.error(str(clash))
            else:
                st.success(f"Job #{job.id} updated.")
                st.rerun()

        with actions[1].popover("Delete"):
            st.caption(
                "For a job that should not have been scheduled. A clean that was "
                "planned and then not done is better marked Missed, so the owner's "
                "statement and the history stay honest."
            )
            if st.button("Delete permanently", key=f"job_delete_{job.id}"):
                queries.delete_cleaning_job(job.id)
                st.rerun()

# --- The cleaners ---------------------------------------------------------

with staff_tab:
    st.caption(
        "Who cleans. They have no login of their own in this version - jobs are "
        "passed on however you do it now, by phone or a printed list."
    )
    if staff:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Name": member.name,
                        "Phone": member.phone,
                        "Working": "Yes" if member.active else "No",
                        "Notes": member.notes,
                    }
                    for member in staff
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("No cleaners on file yet.")

    with st.expander("Add a cleaner", expanded=not staff):
        with st.form("add_staff", clear_on_submit=True):
            columns = st.columns([3, 2])
            name = columns[0].text_input("Name")
            phone = columns[1].text_input("Phone")
            notes = st.text_input("Notes", placeholder="e.g. usually does the Harbour flats")
            if st.form_submit_button("Add cleaner", type="primary"):
                if not name.strip():
                    st.error("The cleaner needs a name.")
                else:
                    queries.create_cleaning_staff(name.strip(), phone.strip(), notes.strip())
                    st.rerun()

    if staff:
        with st.expander("Edit a cleaner"):
            chosen = st.selectbox("Cleaner", [m.name for m in staff], key="edit_staff_pick")
            member = next(m for m in staff if m.name == chosen)
            with st.form("edit_staff"):
                columns = st.columns([3, 2])
                new_name = columns[0].text_input("Name", value=member.name)
                new_phone = columns[1].text_input("Phone", value=member.phone)
                new_notes = st.text_input("Notes", value=member.notes)
                still_working = st.checkbox(
                    "Working", value=member.active,
                    help="Turning this off keeps their history but stops them being assigned.",
                )
                if st.form_submit_button("Save", type="primary"):
                    queries.update_cleaning_staff(
                        member.id, name=new_name.strip(), phone=new_phone.strip(),
                        notes=new_notes.strip(), active=still_working,
                    )
                    st.rerun()

# --- What each clean costs ------------------------------------------------

with costs_tab:
    st.caption(
        "What each service costs. These figures are billed on to the flat's owner "
        "on their monthly statement, so they are the business's cost of cleaning, "
        "not what the guest pays."
    )

    st.markdown("**Standard costs** - used for every flat unless one has its own")
    with st.form("service_costs"):
        entered = {}
        headings = st.columns([2, 2, 2])
        headings[0].markdown("**Service**")
        headings[1].markdown("**Cost**")
        headings[2].markdown("**Typical time (minutes)**")
        for service in service_types:
            row = st.columns([2, 2, 2])
            row[0].markdown(service.label.title())
            entered[service.label] = (
                row[1].number_input(
                    f"{service.label} cost", min_value=0.0, step=25.0,
                    value=float(service.standard_cost), label_visibility="collapsed",
                    key=f"cost_{service.label}",
                ),
                row[2].number_input(
                    f"{service.label} minutes", min_value=0, step=15,
                    value=service.default_minutes or 0, label_visibility="collapsed",
                    key=f"mins_{service.label}",
                ),
            )
        if st.form_submit_button("Save standard costs", type="primary"):
            for label, (cost, minutes) in entered.items():
                queries.save_service_cost(label, Decimal(str(cost)), int(minutes) or None)
            st.success("Standard costs saved.")
            st.rerun()

    st.divider()
    st.markdown("**A flat with its own negotiated price**")
    st.caption(
        "Only where a price was agreed separately with that owner. Anything left "
        "blank simply uses the standard cost above."
    )

    override_unit = st.selectbox("Flat", [unit.name for unit in units], key="override_unit")
    unit = next(u for u in units if u.name == override_unit)
    overrides = {rate.service_label: rate.cost for rate in queries.list_unit_cleaning_rates(unit.id)}

    with st.form("unit_costs"):
        chosen = {}
        for service in service_types:
            row = st.columns([2, 2, 3])
            row[0].markdown(service.label.title())
            chosen[service.label] = row[1].number_input(
                f"{service.label} for this flat", min_value=0.0, step=25.0,
                value=float(overrides.get(service.label, 0)), label_visibility="collapsed",
                key=f"unit_cost_{unit.id}_{service.label}",
            )
            row[2].caption(
                f"standard {money(service.standard_cost)}"
                + (" - overridden" if service.label in overrides else "")
            )
        if st.form_submit_button("Save this flat's prices", type="primary"):
            for label, cost in chosen.items():
                if cost > 0:
                    queries.save_unit_cleaning_rate(unit.id, label, Decimal(str(cost)))
                elif label in overrides:
                    queries.delete_unit_cleaning_rate(unit.id, label)
            st.success(f"Cleaning prices saved for {unit.name}.")
            st.rerun()

    st.divider()
    st.markdown("**How often this flat gets the extras**")
    settings = queries.get_cleaning_settings(unit.id)
    with st.form("cleaning_settings"):
        columns = st.columns(3)
        after = columns[0].number_input(
            "Tidy stays longer than (nights)", min_value=1, step=1,
            value=settings["light_after_nights"],
        )
        every = columns[1].number_input(
            "then every (nights)", min_value=1, step=1, value=settings["light_every_nights"]
        )
        deep = columns[2].number_input(
            "Deep clean every (days)", min_value=0, step=7, value=settings["deep_every_days"],
            help="0 means this flat has no periodic deep clean.",
        )
        if st.form_submit_button("Save", type="primary"):
            queries.save_cleaning_settings(unit.id, int(after), int(every), int(deep))
            st.success(f"Cleaning schedule saved for {unit.name}.")
            st.rerun()
