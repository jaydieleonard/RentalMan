"""Business logic for RentalMan.

Everything in this package is pure: it takes plain domain objects in and
returns plain domain objects out, with no database connection, no Streamlit
import, and no clock of its own. That is deliberate — the money calculations
(quote totals, owner statements) and the availability rules are the parts that
must be right, so they are kept where they can be unit-tested directly. The
`db` package fetches rows and hands them here; `pages/` renders what comes back.
"""
