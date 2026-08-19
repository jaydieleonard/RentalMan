"""Talking to Neon over HTTPS, for when port 5432 is blocked.

Plenty of office and guest networks allow ordinary web traffic and nothing
else, which leaves Postgres's own port unreachable while the very same host
answers fine on 443. Neon serves SQL over HTTPS there, so this is the way in
when the normal route is closed.

This is a development escape hatch, not a second way for the app to run:

* it carries one statement per request, so `db/connection.py` and everything
  above it still speak the real protocol through psycopg;
* values come back as text - a count arrives as "15", not 15 - which is fine
  for DDL and for looking around, and exactly wrong for money;
* the deployed app never needs it, because it connects from its own host.

What it is genuinely good for is applying a migration from a machine that
cannot reach 5432, which is what `db/migrate.py` uses it for.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Sequence
from urllib.parse import urlparse

from db.connection import database_url

TIMEOUT = 60


class HttpSqlError(RuntimeError):
    """The HTTPS endpoint refused a statement."""


def endpoint() -> str:
    return f"https://{urlparse(database_url()).hostname}/sql"


def _post(payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        endpoint(),
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Neon-Connection-String": database_url(),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        try:
            detail = json.loads(detail).get("message", detail)
        except Exception:
            pass
        raise HttpSqlError(f"HTTP {error.code}: {detail.strip()}") from None


def run(query: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    """One statement. Rows come back with every value as text."""
    return _post({"query": query, "params": list(params)}).get("rows", [])


def run_batch(statements: Sequence[str]) -> None:
    """Several statements as one transaction - all of them, or none."""
    _post({"queries": [{"query": statement, "params": []} for statement in statements]})


def reachable() -> bool:
    try:
        run("SELECT 1")
        return True
    except Exception:
        return False


def split_statements(sql: str) -> list[str]:
    """Cut a .sql file into statements.

    The endpoint takes one statement per request, so a migration file has to be
    broken up. Quoted text and comments are tracked rather than the file being
    split on every semicolon, since a semicolon inside a string or a comment is
    not the end of anything.
    """
    statements: list[str] = []
    current: list[str] = []
    in_string = in_line_comment = in_block_comment = False
    index = 0

    while index < len(sql):
        char = sql[index]
        pair = sql[index:index + 2]

        if in_line_comment:
            if char == "\n":
                in_line_comment = False
            current.append(char)
        elif in_block_comment:
            current.append(char)
            if pair == "*/":
                current.append(sql[index + 1])
                index += 1
                in_block_comment = False
        elif in_string:
            current.append(char)
            if char == "'":
                in_string = False
        elif pair == "--":
            in_line_comment = True
            current.append(char)
        elif pair == "/*":
            in_block_comment = True
            current.append(char)
        elif char == "'":
            in_string = True
            current.append(char)
        elif char == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(char)
        index += 1

    trailing = "".join(current).strip()
    if trailing:
        statements.append(trailing)
    # A chunk that is only a comment executes as nothing and errors, so drop it.
    return [s for s in statements if any(
        line.strip() and not line.strip().startswith("--") for line in s.splitlines()
    )]
