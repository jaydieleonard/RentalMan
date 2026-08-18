"""Streamlit-side helpers shared by the pages.

Separate from lib/ on purpose: lib/ is the business logic and imports neither
Streamlit nor the database, so it stays testable. Anything that knows about
widgets, colours or HTML lives here instead.
"""
