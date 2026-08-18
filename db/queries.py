"""The reads and writes the pages need, returning lib.models objects.

Kept deliberately thin: no business rules live here. Anything that decides
something - whether a unit is free, what a stay costs - belongs in lib/, which
these functions feed.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from typing import Any, Iterable

from db.connection import execute, fetch_all, fetch_one
from lib.models import (
    Booking,
    Client,
    ClientRate,
    Owner,
    SeasonDefinition,
    TurnoverRule,
    Unit,
    UnitBlock,
)


def _owner(row: dict[str, Any]) -> Owner:
    return Owner(
        id=row["id"],
        name=row["name"],
        phone=row["phone"],
        email=row["email"],
        banking_details=row["banking_details"],
        notes=row["notes"],
    )


def _unit(row: dict[str, Any]) -> Unit:
    return Unit(
        id=row["id"],
        name=row["name"],
        beds=row["beds"],
        sleeps=row["sleeps"],
        owner_id=row["owner_id"],
        monthly_management_fee=row["monthly_management_fee"],
        min_nights=row["min_nights"],
        checkout_time=row["checkout_time"],
        checkin_time=row["checkin_time"],
        group_tag=row["group_tag"],
        notes=row["notes"],
        active=row["active"],
    )


def _booking(row: dict[str, Any]) -> Booking:
    return Booking(
        id=row["id"],
        unit_id=row["unit_id"],
        client_id=row["client_id"],
        check_in=row["check_in"],
        check_out=row["check_out"],
        status=row["status"],
        total_price=row["total_price"],
        notes=row["notes"],
    )


# --- Owners ---------------------------------------------------------------

def list_owners() -> list[Owner]:
    return [_owner(row) for row in fetch_all("SELECT * FROM owners ORDER BY name")]


def create_owner(name: str, phone: str = "", email: str = "", banking_details: str = "", notes: str = "") -> int:
    row = execute(
        """INSERT INTO owners (name, phone, email, banking_details, notes)
           VALUES (%s, %s, %s, %s, %s) RETURNING id""",
        (name, phone, email, banking_details, notes),
    )
    return row["id"]


def update_owner(owner_id: int, **fields: Any) -> None:
    allowed = ("name", "phone", "email", "banking_details", "notes")
    sets = [f"{name} = %s" for name in fields if name in allowed]
    if not sets:
        return
    values = [fields[name] for name in fields if name in allowed]
    execute(f"UPDATE owners SET {', '.join(sets)} WHERE id = %s", (*values, owner_id))


# --- Units ----------------------------------------------------------------

def list_units(include_inactive: bool = False) -> list[Unit]:
    sql = "SELECT * FROM units"
    if not include_inactive:
        sql += " WHERE active"
    return [_unit(row) for row in fetch_all(sql + " ORDER BY name")]


def get_unit(unit_id: int) -> Unit | None:
    row = fetch_one("SELECT * FROM units WHERE id = %s", (unit_id,))
    return _unit(row) if row else None


def create_unit(
    name: str,
    beds: int,
    sleeps: int,
    owner_id: int,
    monthly_management_fee: Decimal = Decimal("0.00"),
    min_nights: int = 2,
    checkout_time: time | None = None,
    checkin_time: time | None = None,
    group_tag: str = "",
    notes: str = "",
) -> int:
    row = execute(
        """INSERT INTO units (name, beds, sleeps, owner_id, monthly_management_fee,
                              min_nights, checkout_time, checkin_time, group_tag, notes)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (name, beds, sleeps, owner_id, monthly_management_fee, min_nights,
         checkout_time, checkin_time, group_tag, notes),
    )
    return row["id"]


def update_unit(unit_id: int, **fields: Any) -> None:
    allowed = ("name", "beds", "sleeps", "owner_id", "monthly_management_fee",
               "min_nights", "checkout_time", "checkin_time", "group_tag", "notes", "active")
    names = [name for name in fields if name in allowed]
    if not names:
        return
    sets = ", ".join(f"{name} = %s" for name in names)
    execute(f"UPDATE units SET {sets} WHERE id = %s", (*(fields[n] for n in names), unit_id))


# --- Season calendar ------------------------------------------------------

def list_seasons(year: int | None = None) -> list[SeasonDefinition]:
    """Season definitions, newest year first within date order.

    Passing no year returns the whole calendar, which is what pricing wants: a
    stay crossing New Year reads rows filed under two different years.
    """
    sql = "SELECT * FROM season_definitions"
    params: tuple[Any, ...] = ()
    if year is not None:
        sql += " WHERE year = %s"
        params = (year,)
    rows = fetch_all(sql + " ORDER BY start_date", params)
    return [
        SeasonDefinition(row["id"], row["label"], row["start_date"], row["end_date"], row["year"])
        for row in rows
    ]


def list_season_years() -> list[int]:
    rows = fetch_all("SELECT DISTINCT year FROM season_definitions ORDER BY year DESC")
    return [row["year"] for row in rows]


def create_season(label: str, start_date: date, end_date: date, year: int) -> int:
    row = execute(
        """INSERT INTO season_definitions (label, start_date, end_date, year)
           VALUES (%s, %s, %s, %s) RETURNING id""",
        (label, start_date, end_date, year),
    )
    return row["id"]


def update_season(season_id: int, label: str, start_date: date, end_date: date, year: int) -> None:
    execute(
        """UPDATE season_definitions
              SET label = %s, start_date = %s, end_date = %s, year = %s
            WHERE id = %s""",
        (label, start_date, end_date, year, season_id),
    )


def delete_season(season_id: int) -> None:
    execute("DELETE FROM season_definitions WHERE id = %s", (season_id,))


# --- Client rates ---------------------------------------------------------

def list_client_rates(unit_id: int | None = None, year: int | None = None) -> list[ClientRate]:
    clauses, params = [], []
    if unit_id is not None:
        clauses.append("unit_id = %s")
        params.append(unit_id)
    if year is not None:
        clauses.append("year = %s")
        params.append(year)
    sql = "SELECT * FROM client_rates"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    rows = fetch_all(sql + " ORDER BY year DESC, season_label", tuple(params))
    return [
        ClientRate(row["unit_id"], row["season_label"], row["year"],
                   row["nightly_rate"], row["min_nights"])
        for row in rows
    ]


def save_client_rate(
    unit_id: int, season_label: str, year: int, nightly_rate: Decimal, min_nights: int | None
) -> None:
    """Insert or update the one rate row for this unit, season and year."""
    execute(
        """INSERT INTO client_rates (unit_id, season_label, year, nightly_rate, min_nights)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (unit_id, season_label, year)
           DO UPDATE SET nightly_rate = EXCLUDED.nightly_rate,
                         min_nights   = EXCLUDED.min_nights""",
        (unit_id, season_label, year, nightly_rate, min_nights),
    )


def delete_client_rate(unit_id: int, season_label: str, year: int) -> None:
    execute(
        "DELETE FROM client_rates WHERE unit_id = %s AND season_label = %s AND year = %s",
        (unit_id, season_label, year),
    )


# --- Clients and bookings -------------------------------------------------

def list_clients() -> list[Client]:
    rows = fetch_all("SELECT * FROM clients ORDER BY name")
    return [Client(r["id"], r["name"], r["phone"], r["email"], r["notes"]) for r in rows]


def create_client(name: str, phone: str = "", email: str = "", notes: str = "") -> int:
    row = execute(
        "INSERT INTO clients (name, phone, email, notes) VALUES (%s, %s, %s, %s) RETURNING id",
        (name, phone, email, notes),
    )
    return row["id"]


def list_bookings(
    start: date | None = None,
    end: date | None = None,
    unit_ids: Iterable[int] | None = None,
    statuses: Iterable[str] | None = None,
) -> list[Booking]:
    """Bookings overlapping [start, end).

    The overlap test is on nights, not on the raw dates: a stay checking out on
    the first day of the window does not reach into it, because that night was
    slept the day before.
    """
    clauses, params = [], []
    if start is not None:
        clauses.append("check_out > %s")
        params.append(start)
    if end is not None:
        clauses.append("check_in < %s")
        params.append(end)
    if unit_ids is not None:
        unit_ids = list(unit_ids)
        if not unit_ids:
            return []
        clauses.append("unit_id = ANY(%s)")
        params.append(unit_ids)
    if statuses is not None:
        statuses = list(statuses)
        if not statuses:
            return []
        clauses.append("status = ANY(%s)")
        params.append(statuses)

    sql = "SELECT * FROM bookings"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    return [_booking(row) for row in fetch_all(sql + " ORDER BY check_in", tuple(params))]


def create_booking(
    unit_id: int,
    client_id: int | None,
    check_in: date,
    check_out: date,
    status: str = "enquiry",
    total_price: Decimal | None = None,
    notes: str = "",
) -> int:
    try:
        row = execute(
            """INSERT INTO bookings (unit_id, client_id, check_in, check_out, status,
                                     total_price, notes)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (unit_id, client_id, check_in, check_out, status, total_price, notes),
        )
    except Exception as error:
        raise _as_clash(error) from error
    return row["id"]


# --- Turnover rules and blocks -------------------------------------------

def list_turnover_rules(unit_id: int | None = None) -> list[TurnoverRule]:
    sql = "SELECT * FROM turnover_rules"
    params: tuple[Any, ...] = ()
    if unit_id is not None:
        sql += " WHERE unit_id = %s"
        params = (unit_id,)
    rows = fetch_all(sql + " ORDER BY unit_id, season_label NULLS FIRST", params)
    return [TurnoverRule(r["unit_id"], r["season_label"], r["buffer_nights"]) for r in rows]


def save_turnover_rule(unit_id: int, season_label: str | None, buffer_nights: int) -> None:
    """Set the buffer for a unit, either as its default or for one season.

    Written as delete-then-insert because the uniqueness that matters is
    enforced by two partial indexes (a NULL season_label being the unit's
    default), which ON CONFLICT cannot target as a single constraint.
    """
    if season_label is None:
        execute("DELETE FROM turnover_rules WHERE unit_id = %s AND season_label IS NULL", (unit_id,))
    else:
        execute(
            "DELETE FROM turnover_rules WHERE unit_id = %s AND season_label = %s",
            (unit_id, season_label),
        )
    execute(
        "INSERT INTO turnover_rules (unit_id, season_label, buffer_nights) VALUES (%s, %s, %s)",
        (unit_id, season_label, buffer_nights),
    )


def list_unit_blocks(start: date | None = None, end: date | None = None) -> list[UnitBlock]:
    clauses, params = [], []
    if start is not None:
        clauses.append("end_date > %s")
        params.append(start)
    if end is not None:
        clauses.append("start_date < %s")
        params.append(end)
    sql = "SELECT * FROM unit_blocks"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    rows = fetch_all(sql + " ORDER BY start_date", tuple(params))
    return [UnitBlock(r["id"], r["unit_id"], r["start_date"], r["end_date"], r["reason"]) for r in rows]


def create_unit_block(unit_id: int, start_date: date, end_date: date, reason: str = "") -> int:
    row = execute(
        """INSERT INTO unit_blocks (unit_id, start_date, end_date, reason)
           VALUES (%s, %s, %s, %s) RETURNING id""",
        (unit_id, start_date, end_date, reason),
    )
    return row["id"]


class BookingClash(Exception):
    """The database refused a booking because those nights are already taken.

    lib.availability catches this case before it gets here, buffers included,
    so reaching this exception means something changed between the check and
    the save - the other laptop got there first. That is exactly the race the
    exclusion constraint on `bookings` exists to lose safely.
    """


def get_booking(booking_id: int) -> Booking | None:
    row = fetch_one("SELECT * FROM bookings WHERE id = %s", (booking_id,))
    return _booking(row) if row else None


def update_booking(booking_id: int, **fields: Any) -> None:
    allowed = ("unit_id", "client_id", "check_in", "check_out", "status", "total_price", "notes")
    names = [name for name in fields if name in allowed]
    if not names:
        return
    sets = ", ".join(f"{name} = %s" for name in names)
    try:
        execute(
            f"UPDATE bookings SET {sets} WHERE id = %s",
            (*(fields[name] for name in names), booking_id),
        )
    except Exception as error:
        raise _as_clash(error) from error


def delete_booking(booking_id: int) -> None:
    """Remove a booking outright - for a capture mistake, not for a cancellation.

    A stay that was booked and then called off should be set to `cancelled`, so
    the history survives; this is for the row that should never have existed.
    """
    execute("DELETE FROM bookings WHERE id = %s", (booking_id,))


def update_client(client_id: int, **fields: Any) -> None:
    allowed = ("name", "phone", "email", "notes")
    names = [name for name in fields if name in allowed]
    if not names:
        return
    sets = ", ".join(f"{name} = %s" for name in names)
    execute(f"UPDATE clients SET {sets} WHERE id = %s", (*(fields[n] for n in names), client_id))


def _as_clash(error: Exception) -> Exception:
    """Turn Postgres' exclusion-violation into something a page can explain."""
    import psycopg

    if isinstance(error, psycopg.errors.ExclusionViolation):
        return BookingClash(
            "Those nights are already confirmed for this flat. Reload the calendar - "
            "someone may have booked it a moment ago."
        )
    return error
