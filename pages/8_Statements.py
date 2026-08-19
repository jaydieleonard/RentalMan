"""Monthly owner statements: what each owner is owed, and whether it is paid.

Spec 3.8. Three figures per flat, kept apart on purpose - rental income at the
*owner* rate, less the flat monthly management fee, less what the cleans cost.
The net is simply what is owed; there is no tax line.

Nothing here moves money. The statement tells the parents what to pay and
records when they paid it; the transfer happens at the bank.
"""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

import pandas as pd
import streamlit as st

from db import queries
from lib.models import DRAFT, PAID, SENT, STATEMENT_STATUSES
from lib.statements import build_statement, month_bounds
from ui import page
from ui.format import money
from ui.pdf import statement_pdf

page.start("Owner statements")

owners = queries.list_owners()
if not owners:
    page.no_data("owners", "Units")
    st.stop()

owners_by_id = {owner.id: owner for owner in owners}
units = queries.list_units(include_inactive=True)

# --- Which month ----------------------------------------------------------

today = date.today()
last_month = (today.replace(day=1) - date.resolution)
period = st.columns([2, 2, 3])
year = period[0].number_input(
    "Year", min_value=2020, max_value=2100, value=last_month.year, step=1
)
month = period[1].selectbox(
    "Month",
    list(range(1, 13)),
    index=last_month.month - 1,
    format_func=lambda number: calendar.month_name[number],
)
month_start, month_end = month_bounds(int(year), int(month))
period_name = f"{calendar.month_name[int(month)]} {int(year)}"


def statement_for(owner_id: int):
    """Work out one owner's month from what is currently on file."""
    return build_statement(
        owner_id, units, int(year), int(month),
        queries.list_bookings(month_start, month_end),
        queries.list_owner_rates(),
        queries.list_seasons(),
        queries.list_cleaning_jobs(month_start, month_end),
    )


def lines_for(statement) -> list[tuple[int, str, str, Decimal]]:
    """Flatten a statement into the rows stored against it."""
    rows: list[tuple[int, str, str, Decimal]] = []
    for unit in statement.units:
        rows.append((
            unit.unit_id, "rental income",
            f"{unit.nights} night(s) let" if unit.nights else "not let this month",
            unit.rental_income,
        ))
        rows.append((unit.unit_id, "management fee", "Monthly management fee",
                     unit.management_fee))
        rows.append((unit.unit_id, "cleaning cost",
                     f"{len(unit.cleans)} clean(s) done", unit.cleaning_cost))
    return rows


if period[2].button(f"Work out {period_name} for every owner", type="primary"):
    written, problems = 0, []
    for owner in owners:
        statement = statement_for(owner.id)
        if not statement.units:
            continue
        queries.save_statement(statement, lines_for(statement))
        written += 1
        problems.extend(statement.problems)
    # Held over the rerun rather than shown before it: a message written and
    # then immediately rerun away is a message nobody ever reads.
    st.session_state.statement_outcome = (
        f"{written} statement(s) worked out for {period_name}.", problems[:8]
    )
    st.rerun()

outcome = st.session_state.pop("statement_outcome", None)
if outcome:
    message, problems = outcome
    st.success(message)
    for problem in problems:
        st.warning(problem)

# --- What has been worked out --------------------------------------------

saved = [
    row for row in queries.list_statements(int(year))
    if row["month"] == int(month)
]

if not saved:
    st.info(
        f"Nothing worked out for {period_name} yet. The button above reads the "
        "bookings, the owner rates and the cleans done, and produces one "
        "statement per owner."
    )
    st.stop()

outstanding = [row for row in saved if row["status"] != PAID]
summary = st.columns(3)
summary[0].metric("Statements", len(saved))
summary[1].metric("Total due to owners", money(sum(row["net_due"] for row in saved)))
summary[2].metric("Still to pay", money(sum(row["net_due"] for row in outstanding)))

st.dataframe(
    pd.DataFrame(
        [
            {
                "Owner": owners_by_id[row["owner_id"]].name,
                "Rental income": money(row["rental_income"]),
                "Management fees": money(row["management_fees"]),
                "Cleaning": money(row["cleaning_costs"]),
                "Net due": money(row["net_due"]),
                "Status": row["status"].title(),
                "Paid on": row["paid_on"] or "",
            }
            for row in saved
        ]
    ),
    hide_index=True,
    use_container_width=True,
)

# --- One owner's statement -----------------------------------------------

st.divider()
labels = {
    f"{owners_by_id[row['owner_id']].name} - {money(row['net_due'])} ({row['status']})": row
    for row in saved
}
chosen = st.selectbox("Open a statement", list(labels))
row = labels[chosen]
owner = owners_by_id[row["owner_id"]]

# Worked out again from what is on file now, so a booking or a clean added
# since the statement was produced is visible rather than silently absent.
current = statement_for(owner.id)
if current.net != row["net_due"]:
    st.warning(
        f"The figures have moved since this was worked out: it was saved at "
        f"{money(row['net_due'])} and now comes to {money(current.net)}. "
        "Work the month out again to bring it up to date."
    )

for problem in current.problems:
    st.error(problem)

heading = st.columns([3, 2, 2])
heading[0].markdown(f"### {owner.name}")
heading[1].metric("Net due", money(row["net_due"]))
heading[2].metric("Status", row["status"].title())

st.dataframe(
    pd.DataFrame(
        [
            {
                "Flat": unit.unit_name,
                "Nights let": unit.nights,
                "Rental income": money(unit.rental_income),
                "Management fee": f"({money(unit.management_fee)})",
                "Cleaning": f"({money(unit.cleaning_cost)})",
                "Net": money(unit.net),
            }
            for unit in current.units
        ]
    ),
    hide_index=True,
    use_container_width=True,
)
st.caption("Figures in brackets are deducted from that flat's rental income.")

with st.expander("The cleans billed on this statement"):
    billed = [(unit, job) for unit in current.units for job in unit.cleans]
    if billed:
        st.dataframe(
            pd.DataFrame(
                [
                    {"Flat": unit.unit_name, "Date": job.date,
                     "Clean": job.service_label, "Cost": money(job.cost)}
                    for unit, job in billed
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.caption(
            "None. Only cleans marked done are billed on - a job still showing as "
            "scheduled has not been carried out, and the owner should not be charged "
            "for it yet."
        )

# --- Sending it, and recording that it was paid --------------------------

st.markdown("**Send it, and mark it off when the money has gone across**")
actions = st.columns([2, 2, 2, 3])

actions[0].download_button(
    "Download PDF",
    data=statement_pdf(
        owner.name, current, reference=row["id"], generated_on=row["generated_on"]
    ),
    file_name=f"statement-{int(year)}-{int(month):02d}-"
              f"{owner.name.lower().replace(' ', '-').replace('.', '')}.pdf",
    mime="application/pdf",
)

if row["status"] == DRAFT and actions[1].button("Mark as sent"):
    queries.set_statement_status(row["id"], SENT)
    st.rerun()

if row["status"] != PAID:
    with actions[2].popover("Mark as paid"):
        paid_on = st.date_input("Paid on", value=date.today(), format="DD/MM/YYYY")
        st.caption(
            "Recording only. The transfer itself happens at the bank - nothing "
            "here moves money."
        )
        if st.button("Confirm payment", key=f"paid_{row['id']}"):
            queries.set_statement_status(row["id"], PAID, paid_on)
            st.rerun()
else:
    actions[2].success(f"Paid {row['paid_on']}")

if row["status"] != DRAFT and actions[3].button("Put back to draft"):
    queries.set_statement_status(row["id"], DRAFT, None)
    st.rerun()

st.caption(
    "Banking details for paying this owner are on their record, under Units -> Owners."
)
