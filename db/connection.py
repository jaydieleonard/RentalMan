"""Getting a connection to the Neon Postgres database (spec 5).

The connection string is read from, in order:

1. the DATABASE_URL environment variable (or a .env file), which is what the
   command-line scripts - migrate.py, seed.py - use;
2. .streamlit/secrets.toml, which is what the running app uses, and what
   Streamlit Community Cloud serves from its own secrets store on deploy.

Queries run on one shared connection that is kept open. Opening a fresh one
costs about 1.6 seconds against a Neon instance a continent away, and a single
page runs half a dozen queries, so paying that each time made the calendar take
ten seconds to draw.

The reason to avoid a cached connection was that Neon's free tier suspends an
idle database and drops the socket with it, leaving a connection that looks
fine and is not. That is handled directly instead: a dropped connection is
recognised, thrown away and reopened, and the query is tried once more. The
caller sees a slow query rather than an error.
"""

from __future__ import annotations

import os
import threading
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
    """Open a fresh connection of its own, and commit on success.

    Used where a run needs its own transaction - the migration runner applies
    each schema file inside one. Ordinary queries go through the shared
    connection below instead.
    """
    with psycopg.connect(database_url(), row_factory=dict_row) as connection:
        yield connection


# One connection shared by every query, guarded by a lock because Streamlit can
# run two sessions at once and a psycopg connection is not safe to use from two
# threads at the same time.
_shared_lock = threading.RLock()
_shared: psycopg.Connection | None = None

#: Losing the connection is expected rather than exceptional here - Neon
#: suspends an idle database - so these are retried once on a fresh socket.
_LOST_CONNECTION = (psycopg.OperationalError, psycopg.InterfaceError)


def _shared_connection() -> psycopg.Connection:
    global _shared
    if _shared is None or _shared.closed:
        # autocommit: every statement stands alone, so a failed one cannot
        # leave the shared connection sitting in an aborted transaction that
        # breaks the next caller's query.
        _shared = psycopg.connect(database_url(), row_factory=dict_row, autocommit=True)
    return _shared


def _discard_shared() -> None:
    global _shared
    if _shared is not None:
        try:
            _shared.close()
        except Exception:
            pass
    _shared = None


def _run(sql: str, params: Sequence[Any] | dict[str, Any], fetch: str) -> Any:
    with _shared_lock:
        for attempt in (1, 2):
            try:
                with _shared_connection().cursor() as cursor:
                    cursor.execute(sql, params)
                    if fetch == "all":
                        return cursor.fetchall()
                    if cursor.description is None:
                        return None
                    return cursor.fetchone()
            except _LOST_CONNECTION:
                # The database went to sleep, or the socket died under us.
                _discard_shared()
                if attempt == 2:
                    raise
        return None


def fetch_all(sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> list[dict[str, Any]]:
    return _run(sql, params, "all")


def fetch_one(sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> dict[str, Any] | None:
    return _run(sql, params, "one")


def execute(sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> dict[str, Any] | None:
    """Run a write. Returns the RETURNING row if the statement has one."""
    return _run(sql, params, "one")


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
        # Goes through the shared connection like everything else: this runs on
        # every page load, and a fresh handshake here would undo the point.
        row = fetch_one(
            "SELECT current_database() AS name, to_regclass('public.units') AS units"
        )
    except MissingDatabaseURL as missing:
        return False, str(missing)
    except Exception as error:
        return False, f"Could not reach the database: {error}"

    if row is None:
        return False, "The database answered, but not in a way we understand."
    if row["units"] is None:
        return False, NOT_MIGRATED_HELP.format(name=row["name"])
    return True, f"Connected to {row['name']}."
