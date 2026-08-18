"""Getting a connection to the Neon Postgres database (spec 5).

The connection string is read from, in order:

1. the DATABASE_URL environment variable (or a .env file), which is what the
   command-line scripts - migrate.py, seed.py - use;
2. .streamlit/secrets.toml, which is what the running app uses, and what
   Streamlit Community Cloud serves from its own secrets store on deploy.

A connection is opened per call rather than held open. Neon's free tier
suspends an idle database and drops the socket with it, so a cached connection
would work all day and then fail on the first quiet morning - which is exactly
when nobody wants to debug it. At two users the extra handshake costs nothing
worth saving.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator, Sequence

import psycopg
from psycopg.rows import dict_row

SETUP_HELP = """No database connection string found.

For the app: copy .streamlit/secrets.toml.example to .streamlit/secrets.toml and
paste your Neon connection string into it.

For scripts (migrate, seed): set DATABASE_URL in your shell or in a .env file at
the project root, e.g.

    DATABASE_URL=postgresql://user:pass@ep-xxx-pooler.region.aws.neon.tech/rentalman?sslmode=require
"""


class MissingDatabaseURL(RuntimeError):
    """No connection string is configured anywhere we look."""

    def __init__(self) -> None:
        super().__init__(SETUP_HELP)


def _from_env() -> str | None:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    try:
        from dotenv import load_dotenv
    except ImportError:
        return None
    load_dotenv()
    return os.environ.get("DATABASE_URL")


def _from_streamlit_secrets() -> str | None:
    try:
        import streamlit as st
    except ImportError:
        return None
    try:
        return st.secrets["connections"]["database_url"]
    except Exception:
        # No secrets file, or no such key: not an error here, just not the
        # source we are getting the URL from.
        return None


def database_url() -> str:
    """The Neon connection string, or a message explaining how to set one."""
    url = _from_env() or _from_streamlit_secrets()
    if not url:
        raise MissingDatabaseURL()
    return url


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    """Open a connection whose rows come back as dicts, and commit on success."""
    with psycopg.connect(database_url(), row_factory=dict_row) as connection:
        yield connection


def fetch_all(sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> list[dict[str, Any]]:
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def fetch_one(sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> dict[str, Any] | None:
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()


def execute(sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> dict[str, Any] | None:
    """Run a write. Returns the RETURNING row if the statement has one."""
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(sql, params)
        if cursor.description is None:
            return None
        return cursor.fetchone()


NOT_MIGRATED_HELP = """Connected to {name}, but the tables have not been created yet.

Run this once, from the project folder, with DATABASE_URL pointing at the same
database:

    python -m db.migrate

Then reload this page."""


def check_connection() -> tuple[bool, str]:
    """Say plainly whether the app can actually use its database.

    Reaching Postgres is only half of it: a brand new Neon project answers
    perfectly well and has nothing in it. Checking for a table we know the
    schema creates turns "relation units does not exist" three screens later
    into one sentence naming the command that fixes it.
    """
    try:
        with connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_database() AS name, to_regclass('public.units') AS units"
            )
            row = cursor.fetchone()
    except MissingDatabaseURL as missing:
        return False, str(missing)
    except Exception as error:
        return False, f"Could not reach the database: {error}"

    if row is None:
        return False, "The database answered, but not in a way we understand."
    if row["units"] is None:
        return False, NOT_MIGRATED_HELP.format(name=row["name"])
    return True, f"Connected to {row['name']}."
