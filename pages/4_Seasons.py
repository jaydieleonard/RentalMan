"""The one shared season calendar every flat prices against (spec 3.3).

Deliberately a plain list of "start date, end date, season" rows, because it
has to be updatable year to year without technical help. The year map above the
list is there so an uncovered stretch is obvious before someone runs into it
mid-quote.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from db import queries
from lib.models import SEASON_LABELS
from lib.seasons import validate_calendar
from ui import page
from ui.grid import render_year_ribbon

page.start("Season calendar")

st.caption(
    "One calendar covers every flat. These dates drive what a guest is charged and, "
    "from Phase 5, what is due back to each owner."
)

known_years = queries.list_season_years()
this_year = date.today().year
year_choices = sorted({*known_years, this_year, this_year + 1}, reverse=True)
year = st.selectbox("Year", year_choices, index=year_choices.index(this_year))

definitions = queries.list_seasons(int(year))

# --- The year at a glance -------------------------------------------------

if definitions:
    st.markdown(render_year_ribbon(definitions, int(year)), unsafe_allow_html=True)
else:
    st.info(f"No season dates set for {year} yet.")

for problem in validate_calendar(definitions, year=int(year)):
    (st.error if problem.severity == "error" else st.warning)(problem.message)

# --- The rows themselves --------------------------------------------------

st.subheader(f"{year} season dates")

if definitions:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Season": definition.label,
                    "From": definition.start_date,
                    "To (inclusive)": definition.end_date,
                    "Nights": (definition.end_date - definition.start_date).days + 1,
                }
                for definition in definitions
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )

with st.form("add_season", clear_on_submit=True):
    st.markdown("**Add a season period**")
    columns = st.columns([2, 2, 2, 1])
    label = columns[0].selectbox("Season", SEASON_LABELS)
    start = columns[1].date_input("From", value=date(int(year), 1, 1), format="DD/MM/YYYY")
    end = columns[2].date_input("To (inclusive)", value=date(int(year), 1, 31), format="DD/MM/YYYY")
    columns[3].markdown("&nbsp;")
    if columns[3].form_submit_button("Add", type="primary"):
        if end < start:
            st.error("The end date cannot be before the start date.")
        else:
            try:
                queries.create_season(label, start, end, int(year))
                st.success(f"Added {label}: {start} to {end}.")
                st.rerun()
            except Exception as error:
                # The database refuses overlapping periods outright, which is
                # worth saying in plain words rather than showing a traceback.
                st.error(
                    "Those dates overlap a season period that already exists. "
                    "Every date must belong to exactly one season."
                )
                st.caption(str(error))

st.caption(
    "A period may run past the end of the year - 1 December to 15 January is one row, "
    "filed under the year it starts in, and prices at that year's rates throughout."
)

if definitions:
    with st.expander("Change or remove a period"):
        options = {
            f"{d.label}: {d.start_date} to {d.end_date}": d for d in definitions
        }
        chosen = st.selectbox("Period", list(options), key="edit_season_pick")
        definition = options[chosen]
        with st.form("edit_season"):
            columns = st.columns([2, 2, 2])
            new_label = columns[0].selectbox(
                "Season", SEASON_LABELS, index=SEASON_LABELS.index(definition.label)
            )
            new_start = columns[1].date_input("From", value=definition.start_date, format="DD/MM/YYYY")
            new_end = columns[2].date_input(
                "To (inclusive)", value=definition.end_date, format="DD/MM/YYYY"
            )
            save, delete = st.columns([1, 1])
            if save.form_submit_button("Save changes", type="primary"):
                if new_end < new_start:
                    st.error("The end date cannot be before the start date.")
                else:
                    try:
                        queries.update_season(
                            definition.id, new_label, new_start, new_end, int(year)
                        )
                        st.success("Saved.")
                        st.rerun()
                    except Exception as error:
                        st.error("Those dates overlap another season period.")
                        st.caption(str(error))
            if delete.form_submit_button("Delete this period"):
                queries.delete_season(definition.id)
                st.success("Removed.")
                st.rerun()

# --- Setting up the next year --------------------------------------------

st.divider()
st.markdown("**Start next year from this one**")
st.caption(
    f"Copies every {year} period forward to {int(year) + 1} on the same calendar dates, "
    "ready to be nudged where the school holidays have moved. It will not touch a year "
    "that already has dates set."
)

target = int(year) + 1
if st.button(f"Copy {year} dates into {target}"):
    if queries.list_seasons(target):
        st.warning(f"{target} already has season dates - clear them first if you want to start over.")
    elif not definitions:
        st.warning(f"There is nothing in {year} to copy.")
    else:
        copied = 0
        for definition in definitions:
            # 29 February has no counterpart in a non-leap year, so it lands on
            # the 28th rather than failing the whole copy.
            def shift(day: date) -> date:
                try:
                    return day.replace(year=day.year + 1)
                except ValueError:
                    return day.replace(year=day.year + 1, day=28)

            queries.create_season(
                definition.label, shift(definition.start_date), shift(definition.end_date), target
            )
            copied += 1
        st.success(f"Copied {copied} period(s) into {target}. Check the dates before pricing against them.")
        st.rerun()
