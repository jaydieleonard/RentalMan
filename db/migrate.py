"""Apply the schema files in db/schema to the database, in order, once each.

Run it from the project root with a DATABASE_URL set:

    python -m db.migrate            # apply anything outstanding
    python -m db.migrate --status   # just say what has and has not been applied

Each file runs inside its own transaction, so a file that fails leaves nothing
behind and can be fixed and re-run. Applied files are never re-applied: to
change the schema, add the next numbered file rather than editing an old one.
"""

from __future__ import annotations

import sys
from pathlib import Path

from db.connection import connect

SCHEMA_DIR = Path(__file__).parent / "schema"

CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename   TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def schema_files() -> list[Path]:
    return sorted(SCHEMA_DIR.glob("*.sql"))


def applied_filenames(connection) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(CREATE_MIGRATIONS_TABLE)
        cursor.execute("SELECT filename FROM schema_migrations")
        return {row["filename"] for row in cursor.fetchall()}


def migrate() -> list[str]:
    """Apply every outstanding schema file. Returns the names applied."""
    applied_now: list[str] = []
    with connect() as connection:
        already = applied_filenames(connection)
        connection.commit()

        for path in schema_files():
            if path.name in already:
                continue
            print(f"applying {path.name} ...", flush=True)
            with connection.cursor() as cursor:
                cursor.execute(path.read_text(encoding="utf-8"))
                cursor.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,)
                )
            connection.commit()
            applied_now.append(path.name)
    return applied_now


def status() -> None:
    with connect() as connection:
        already = applied_filenames(connection)
        connection.commit()
    for path in schema_files():
        mark = "applied" if path.name in already else "OUTSTANDING"
        print(f"  {path.name:<24} {mark}")


def main(argv: list[str]) -> int:
    if "--status" in argv:
        status()
        return 0
    applied = migrate()
    print(f"{len(applied)} file(s) applied." if applied else "Already up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
