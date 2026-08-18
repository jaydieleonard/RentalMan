"""A password gate in front of the whole app (spec 5).

Deliberately minimal: two people share one password, held in the same secrets
file as the database URL, so Community Cloud serves it from its secrets store
on deploy and it never reaches Git. That is enough to keep owner banking
details and financial statements off the open web without building user
management nobody asked for.

With no password set - local development - the gate stands aside rather than
locking the developer out of their own machine.
"""

from __future__ import annotations

import hmac

import streamlit as st

SESSION_KEY = "rentalman_authenticated"


def configured_password() -> str | None:
    try:
        return st.secrets["auth"]["password"]
    except Exception:
        return None


def require_login() -> None:
    """Stop the page unless the visitor has entered the shared password."""
    password = configured_password()
    if not password:
        return
    if st.session_state.get(SESSION_KEY):
        return

    st.title("RentalMan")
    st.caption("Please sign in to continue.")
    entered = st.text_input("Password", type="password")
    if entered:
        # hmac.compare_digest rather than == so a wrong password cannot be
        # narrowed down by how long the check took.
        if hmac.compare_digest(entered, password):
            st.session_state[SESSION_KEY] = True
            st.rerun()
        else:
            st.error("That password is not right.")
    st.stop()
