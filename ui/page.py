"""One entry point every page calls first, so they all behave the same.

Sets the page up, puts the password gate in front of it, and - because a page
full of tracebacks helps nobody - checks the database is reachable and explains
what to do if it is not.
"""

from __future__ import annotations

import streamlit as st

from db import connection
from ui.auth import require_login
from ui.brand import BUSINESS_NAME, ICON, LOGO


def start(title: str, require_database: bool = True, hero: bool = False) -> None:
    """Set the page up, put the login gate in front of it, check the database.

    `hero` swaps the text heading for the logo itself - used on the home page,
    where the app is introducing itself rather than labelling a screen.
    """
    st.set_page_config(
        page_title=f"{title} - {BUSINESS_NAME}",
        page_icon=str(ICON),
        layout="wide",
    )
    require_login()

    # Sits above the page list in the sidebar; the mark alone is used when the
    # sidebar is collapsed to a strip.
    st.logo(str(LOGO), icon_image=str(ICON), size="large")

    if hero:
        st.image(str(LOGO), width=300)
    else:
        st.title(title)

    if not require_database:
        return

    connected, message = connection.check_connection()
    if connected:
        return

    # The message says which of the two it is - no connection string, an
    # unreachable database, or a reachable one with no tables in it yet.
    st.error("The app cannot use its database yet, so there is nothing to show.")
    st.code(message, language="text")
    st.stop()


def no_data(what: str, where: str) -> None:
    """A consistent way of saying 'nothing here yet, and here is where to add it'."""
    st.info(f"No {what} yet. Add {'them' if what.endswith('s') else 'it'} on the {where} page.")
