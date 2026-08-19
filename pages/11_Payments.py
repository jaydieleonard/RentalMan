"""What has been paid to owners, and what is still owed (spec 9, Phase 6).

The statements page answers "is this month settled". This one answers the
questions that span months: what have we paid this owner this year, what is
still outstanding, and when did that transfer in March actually go across.

Payments are recorded against a statement on the statements page; this is the
run of them, read across owners and months.
"""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

import pandas as pd
import streamlit as st

from db import queries
from ui import page
from ui.format import money

page.start("Owner payments")

owners = queries.list_owners()
if not owners:
    page.no_data("owners", "Units")
    st.stop()

today = date.today()
filters = st.columns([2, 3, 3])
year = filters[0].selectbox(
    "Year", list(range(today.year, today.year - 5, -1)), index=0
)
owner_name = filters[1].selectbox("Owner", ["All owners"] + [owner.name for owner in owners])
owner_id = (
    None if owner_name == "All owners"
    else next(owner.id for owner in owners if owner.name == owner_name)
)

payments = queries.payment_history(int(year), owner_id)
unsettled = [
    row for row in queries.unsettled_statements()
    if owner_id is None or row["owner_id"] == owner_id
]

# --- Where things stand ---------------------------------------------------

paid_total = sum((row["amount"] for row in payments), Decimal("0.00"))
still_owed = sum(
    (row["net_due"] - row["paid"] for row in unsettled if row["net_due"] > row["paid"]),
    Decimal("0.00"),
)

headline = st.columns(3)
headline[0].metric(f"Paid out in {year}", money(paid_total))
headline[1].metric("Payments made", len(payments))
headline[2].metric("Still outstanding", money(still_owed))

if unsettled:
    st.warning(
        f"{len(unsettled)} statement(s) not settled: "
        + ", ".join(
            f"{row['owner_name']} {calendar.month_abbr[row['month']]} {row['year']}"
            f" ({money(row['net_due'] - row['paid'])})"
            for row in unsettled[:6]
        )
        + ("..." if len(unsettled) > 6 else "")
    )
else:
    st.success("Every statement that has been sent is settled.")

# --- Every payment --------------------------------------------------------

st.subheader(f"Payments in {year}")

if not payments:
    st.info(
        f"No payments recorded in {year}. They are entered against a statement, "
        "on the Statements page."
    )
    st.stop()

st.dataframe(
    pd.DataFrame(
        [
            {
                "Paid on": row["paid_on"],
                "Owner": row["owner_name"],
                "For": f"{calendar.month_abbr[row['statement_month']]} {row['statement_year']}",
                "Amount": money(row["amount"]),
                "Reference": row["reference"],
                "Note": row["notes"],
            }
            for row in payments
        ]
    ),
    hide_index=True,
    use_container_width=True,
)

# --- Owner by owner -------------------------------------------------------

if owner_id is None:
    st.subheader("Owner by owner")
    by_owner: dict[str, list] = {}
    for row in payments:
        by_owner.setdefault(row["owner_name"], []).append(row)

    outstanding_by_owner: dict[str, Decimal] = {}
    for row in unsettled:
        if row["net_due"] > row["paid"]:
            outstanding_by_owner[row["owner_name"]] = (
                outstanding_by_owner.get(row["owner_name"], Decimal("0.00"))
                + (row["net_due"] - row["paid"])
            )

    names = sorted(set(by_owner) | set(outstanding_by_owner))
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Owner": name,
                    "Payments": len(by_owner.get(name, [])),
                    f"Paid in {year}": money(
                        sum((row["amount"] for row in by_owner.get(name, [])), Decimal("0.00"))
                    ),
                    "Last paid": max(
                        (row["paid_on"] for row in by_owner.get(name, [])), default=""
                    ),
                    "Still owed": money(outstanding_by_owner.get(name, Decimal("0.00"))),
                }
                for name in names
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )

# --- Month by month -------------------------------------------------------

st.subheader("Month by month")
monthly: dict[int, Decimal] = {}
for row in payments:
    monthly[row["paid_on"].month] = monthly.get(row["paid_on"].month, Decimal("0.00")) + row["amount"]

st.dataframe(
    pd.DataFrame(
        [
            {"Month": calendar.month_name[month], "Paid out": float(monthly[month])}
            for month in sorted(monthly)
        ]
    ),
    hide_index=True,
    use_container_width=True,
    column_config={
        "Paid out": st.column_config.ProgressColumn(
            "Paid out", format="R%.0f", min_value=0,
            max_value=float(max(monthly.values())) if monthly else 1,
        ),
    },
)
st.caption(
    "When the money went across, not which month it settles - a March statement "
    "paid in April shows here under April."
)
