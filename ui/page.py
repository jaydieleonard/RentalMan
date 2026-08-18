"""One entry point every page calls first, so they all behave the same.

Sets the page up, puts the password gate in front of it, and - because a page
full of tracebacks helps nobody - checks the database is reachable and explains
what to do if it is not.
"""

from __future__ import annotations

import streamlit as st

from db import connection
from ui.auth import require_login


def start(title: str, icon: str = "🏖️", require_database: bool = True) -> None:
    st.set_page_config(page_title=f"{title} - RentalMan", page_icon=icon, layout="wide")
    require_login()
    st.title(title)

    if not require_database:
        return

    connected, message = connection.check_connection()
    if connected:
        return

    st.error("The app cannot reach its database, so there is nothing to show yet.")
    st.code(message, language="text")
    st.caption(
        "Once the connection string is in place, run `python -m db.migrate` to create "
        "the tables, then reload this page."
    )
    st.stop()


def no_data(what: str, where: str) -> None:
    """A consistent way of saying 'nothing here yet, and here is where to add it'."""
    st.info(f"No {what} yet. Add {'them' if what.endswith('s') else 'it'} on the {where} page.")
