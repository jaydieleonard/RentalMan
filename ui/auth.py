"""A password gate in front of the whole app (spec 5).

Deliberately minimal: two people share one password, held in the same secrets
file as the database URL, so Community Cloud serves it from its secrets store
on deploy and it never reaches Git. That is enough to keep owner banking
details and financial statements off the open web without building user
management nobody asked for.

With no password set the gate stands aside on a developer's own machine, and
refuses outright on a hosted one. That asymmetry is the point: locking someone
out of their own laptop helps nobody, while a deployment with no password is
the flats, the owners, their banking details and every statement, open to
whoever has the address.
"""

from __future__ import annotations

import hmac
from pathlib import Path

import streamlit as st

from ui.brand import LOGO

SESSION_KEY = "rentalman_authenticated"

#: Where Streamlit Community Cloud checks the repository out. Running from
#: there means the app is on the open internet rather than on somebody's desk.
HOSTED_PREFIX = "/mount/src"

NO_PASSWORD_HELP = """This app is deployed without a password, so it is not showing anything.

Add a password in the app's secrets - Manage app, then Settings, then Secrets:

    [auth]
    password = "something you and your parents will remember"

Saving it restarts the app, and the sign-in screen appears."""


def configured_password() -> str | None:
    try:
        return st.secrets["auth"]["password"]
    except Exception:
        return None


def is_hosted() -> bool:
    """Is this running on a public host rather than a development machine?"""
    return str(Path(__file__).resolve()).replace("\\", "/").startswith(HOSTED_PREFIX)


def require_login() -> None:
    """Stop the page unless the visitor has entered the shared password."""
    password = configured_password()
    if not password:
        if is_hosted():
            # Fail closed. The alternative is a public address serving owner
            # banking details to anyone who finds it.
            st.error("No password is set for this app.")
            st.code(NO_PASSWORD_HELP, language="text")
            st.stop()
        return
    if st.session_state.get(SESSION_KEY):
        return

    centre = st.columns([1, 2, 1])[1]
    centre.image(str(LOGO), width=320)
    centre.caption("Please sign in to continue.")
    entered = centre.text_input("Password", type="password")
    if entered:
        # hmac.compare_digest rather than == so a wrong password cannot be
        # narrowed down by how long the check took.
        if hmac.compare_digest(entered, password):
            st.session_state[SESSION_KEY] = True
            st.rerun()
        else:
            centre.error("That password is not right.")
    st.stop()
