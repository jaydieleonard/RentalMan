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


def migrate_over_https() -> list[str]:
    """Apply outstanding files through Neon's HTTPS endpoint.

    Used when port 5432 is unreachable - some networks allow web traffic and
    nothing else. Each file goes as one batch, which the endpoint runs as a
    single transaction, so a file that fails leaves nothing behind exactly as
    it would over the normal connection.
    """
    from db import http_sql

    http_sql.run(CREATE_MIGRATIONS_TABLE)
    already = {row["filename"] for row in http_sql.run("SELECT filename FROM schema_migrations")}

    applied_now: list[str] = []
    for path in schema_files():
        if path.name in already:
            continue
        print(f"applying {path.name} over HTTPS ...", flush=True)
        statements = http_sql.split_statements(path.read_text(encoding="utf-8"))
        statements.append(
            "INSERT INTO schema_migrations (filename) VALUES ('%s')" % path.name.replace("'", "''")
        )
        http_sql.run_batch(statements)
        applied_now.append(path.name)
    return applied_now


def migrate() -> list[str]:
    """Apply every outstanding schema file. Returns the names applied."""
    applied_now: list[str] = []
    try:
        connection_manager = connect()
        connection_manager.__enter__()
    except Exception as error:
        print(f"Port 5432 is unreachable ({type(error).__name__}); trying HTTPS instead.")
        return migrate_over_https()
    connection_manager.__exit__(None, None, None)

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
