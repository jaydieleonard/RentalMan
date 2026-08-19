"""The reads and writes the pages need, returning lib.models objects.

Kept deliberately thin: no business rules live here. Anything that decides
something - whether a unit is free, what a stay costs - belongs in lib/, which
these functions feed.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

from db.connection import execute, fetch_all, fetch_one, transaction
from lib.payments import OwnerPayment
from lib.models import (
    Booking,
    CleaningJob,
    CleaningServiceType,
    CleaningStaff,
    Client,
    ClientRate,
    Owner,
    OwnerRate,
    QuoteLine,
    SavedQuote,
    SeasonDefinition,
    TurnoverRule,
    Unit,
    UnitBlock,
    UnitCleaningRate,
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


class CleaningClash(Exception):
    """That flat already has a clean on that day, and it only gets one."""


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


# --- Quotes ---------------------------------------------------------------

def _quote_line(row: dict[str, Any]) -> QuoteLine:
    return QuoteLine(
        season_label=row["season_label"],
        first_night=row["first_night"],
        last_night=row["last_night"],
        nights=row["nights"],
        nightly_rate=row["nightly_rate"],
        subtotal=row["subtotal"],
    )


def _saved_quote(row: dict[str, Any], lines: tuple[QuoteLine, ...] = ()) -> SavedQuote:
    return SavedQuote(
        id=row["id"],
        unit_id=row["unit_id"],
        client_id=row["client_id"],
        check_in=row["check_in"],
        check_out=row["check_out"],
        guests=row["guests"],
        total=row["total"],
        status=row["status"],
        generated_on=row["generated_on"],
        lines=lines,
        notes=row["notes"],
        booking_id=row["booking_id"],
    )


def save_quote(
    unit_id: int,
    client_id: int | None,
    check_in: date,
    check_out: date,
    guests: int | None,
    total: Decimal,
    lines: Iterable[QuoteLine],
    notes: str = "",
) -> int:
    """Store a quote and the priced lines behind it, as one unit.

    Written in a transaction because a quote without its breakdown is worse
    than no quote at all - it would reopen showing a total nobody can explain.
    """
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO quotes (unit_id, client_id, check_in, check_out, guests,
                                   total, notes)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (unit_id, client_id, check_in, check_out, guests, total, notes),
        )
        quote_id = cursor.fetchone()["id"]
        for number, line in enumerate(lines, start=1):
            cursor.execute(
                """INSERT INTO quote_lines (quote_id, line_number, season_label,
                                            first_night, last_night, nights,
                                            nightly_rate, subtotal)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (quote_id, number, line.season_label, line.first_night, line.last_night,
                 line.nights, line.nightly_rate, line.subtotal),
            )
    return quote_id


def list_quotes(statuses: Iterable[str] | None = None) -> list[SavedQuote]:
    """Quotes newest first, without their lines - the list view does not need them."""
    sql = "SELECT * FROM quotes"
    params: tuple[Any, ...] = ()
    if statuses is not None:
        statuses = list(statuses)
        if not statuses:
            return []
        sql += " WHERE status = ANY(%s)"
        params = (statuses,)
    rows = fetch_all(sql + " ORDER BY generated_on DESC, id DESC", params)
    return [_saved_quote(row) for row in rows]


def get_quote(quote_id: int) -> SavedQuote | None:
    """One quote with the priced lines exactly as they were sent."""
    row = fetch_one("SELECT * FROM quotes WHERE id = %s", (quote_id,))
    if row is None:
        return None
    lines = fetch_all(
        "SELECT * FROM quote_lines WHERE quote_id = %s ORDER BY line_number", (quote_id,)
    )
    return _saved_quote(row, tuple(_quote_line(line) for line in lines))


def set_quote_status(quote_id: int, status: str) -> None:
    execute("UPDATE quotes SET status = %s WHERE id = %s", (status, quote_id))


def accept_quote(quote: SavedQuote, notes: str = "") -> int:
    """Turn an accepted quote into a confirmed booking, in one action (3.6).

    Both writes happen together: a booking with no quote pointing at it, or an
    accepted quote with no booking holding the dates, would each be a worse
    state than the one we started in.

    The caller is expected to have checked availability first - a quote does
    not hold dates, so the flat may well have gone since it was sent. The
    exclusion constraint on `bookings` is the backstop if the other laptop got
    there in the meantime.
    """
    with transaction() as connection, connection.cursor() as cursor:
        try:
            cursor.execute(
                """INSERT INTO bookings (unit_id, client_id, check_in, check_out,
                                         status, total_price, notes)
                   VALUES (%s, %s, %s, %s, 'confirmed', %s, %s) RETURNING id""",
                (quote.unit_id, quote.client_id, quote.check_in, quote.check_out,
                 quote.total, notes),
            )
        except Exception as error:
            raise _as_clash(error) from error
        booking_id = cursor.fetchone()["id"]
        cursor.execute(
            "UPDATE quotes SET status = 'accepted', booking_id = %s WHERE id = %s",
            (booking_id, quote.id),
        )
    return booking_id


def cancel_quote(quote_id: int, booking_id: int | None = None) -> None:
    """Cancel a quote, and the booking it created if it made one.

    Leaving the booking confirmed would keep the flat blocked on the calendar
    for a stay nobody is taking - the opposite of what cancelling means.
    """
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE quotes SET status = 'cancelled' WHERE id = %s", (quote_id,))
        if booking_id is not None:
            cursor.execute(
                "UPDATE bookings SET status = 'cancelled' WHERE id = %s", (booking_id,)
            )


def get_client(client_id: int) -> Client | None:
    row = fetch_one("SELECT * FROM clients WHERE id = %s", (client_id,))
    return Client(row["id"], row["name"], row["phone"], row["email"], row["notes"]) if row else None


def find_clients(term: str, limit: int = 8) -> list[Client]:
    """Clients whose name, phone or email contains `term`.

    Deliberately a search rather than a list: the client table only grows, and
    a dropdown of every guest the business has ever had stops being usable long
    before it stops loading. Names that *start* with what was typed come first,
    since that is what someone half-way through typing a name is looking for.
    """
    term = term.strip()
    if len(term) < 2:
        return []
    contains, prefix = f"%{term}%", f"{term.lower()}%"
    rows = fetch_all(
        """SELECT * FROM clients
            WHERE name ILIKE %s OR phone ILIKE %s OR email ILIKE %s
            ORDER BY (lower(name) LIKE %s) DESC, name
            LIMIT %s""",
        (contains, contains, contains, prefix, limit),
    )
    return [Client(r["id"], r["name"], r["phone"], r["email"], r["notes"]) for r in rows]


def get_clients(client_ids: Iterable[int]) -> dict[int, Client]:
    """The named clients only, keyed by id.

    Used where a screen needs the names behind the rows it is showing. Loading
    every client to look up a handful of names stops being reasonable long
    before the list stops fitting in memory.
    """
    client_ids = [cid for cid in client_ids if cid is not None]
    if not client_ids:
        return {}
    rows = fetch_all("SELECT * FROM clients WHERE id = ANY(%s)", (client_ids,))
    return {
        row["id"]: Client(row["id"], row["name"], row["phone"], row["email"], row["notes"])
        for row in rows
    }


def delete_turnover_rule(unit_id: int, season_label: str) -> None:
    """Remove a season's override so the unit's all-seasons buffer applies again."""
    execute(
        "DELETE FROM turnover_rules WHERE unit_id = %s AND season_label = %s",
        (unit_id, season_label),
    )


# --- Cleaning staff and services -----------------------------------------

def list_cleaning_staff(include_inactive: bool = False) -> list[CleaningStaff]:
    sql = "SELECT * FROM cleaning_staff"
    if not include_inactive:
        sql += " WHERE active"
    rows = fetch_all(sql + " ORDER BY name")
    return [CleaningStaff(r["id"], r["name"], r["phone"], r["notes"], r["active"]) for r in rows]


def create_cleaning_staff(name: str, phone: str = "", notes: str = "") -> int:
    row = execute(
        "INSERT INTO cleaning_staff (name, phone, notes) VALUES (%s, %s, %s) RETURNING id",
        (name, phone, notes),
    )
    return row["id"]


def update_cleaning_staff(staff_id: int, **fields: Any) -> None:
    allowed = ("name", "phone", "notes", "active")
    names = [name for name in fields if name in allowed]
    if not names:
        return
    sets = ", ".join(f"{name} = %s" for name in names)
    execute(f"UPDATE cleaning_staff SET {sets} WHERE id = %s",
            (*(fields[n] for n in names), staff_id))


def list_service_types() -> list[CleaningServiceType]:
    rows = fetch_all("SELECT * FROM cleaning_service_types ORDER BY label")
    return [
        CleaningServiceType(None, r["label"], r["standard_cost"], r["default_minutes"])
        for r in rows
    ]


def save_service_cost(label: str, standard_cost: Decimal, default_minutes: int | None) -> None:
    execute(
        """UPDATE cleaning_service_types
              SET standard_cost = %s, default_minutes = %s
            WHERE label = %s""",
        (standard_cost, default_minutes, label),
    )


def list_unit_cleaning_rates(unit_id: int | None = None) -> list[UnitCleaningRate]:
    sql = "SELECT * FROM unit_cleaning_rates"
    params: tuple[Any, ...] = ()
    if unit_id is not None:
        sql += " WHERE unit_id = %s"
        params = (unit_id,)
    rows = fetch_all(sql + " ORDER BY unit_id, service_label", params)
    return [UnitCleaningRate(r["unit_id"], r["service_label"], r["cost"]) for r in rows]


def save_unit_cleaning_rate(unit_id: int, service_label: str, cost: Decimal) -> None:
    execute(
        """INSERT INTO unit_cleaning_rates (unit_id, service_label, cost)
           VALUES (%s, %s, %s)
           ON CONFLICT (unit_id, service_label) DO UPDATE SET cost = EXCLUDED.cost""",
        (unit_id, service_label, cost),
    )


def delete_unit_cleaning_rate(unit_id: int, service_label: str) -> None:
    execute(
        "DELETE FROM unit_cleaning_rates WHERE unit_id = %s AND service_label = %s",
        (unit_id, service_label),
    )


def get_cleaning_settings(unit_id: int) -> dict[str, int]:
    """A flat's cleaning cadences, falling back to the business-wide defaults."""
    row = fetch_one("SELECT * FROM unit_cleaning_settings WHERE unit_id = %s", (unit_id,))
    if row is None:
        return {"light_after_nights": 10, "light_every_nights": 7, "deep_every_days": 91}
    return {
        "light_after_nights": row["light_after_nights"],
        "light_every_nights": row["light_every_nights"],
        "deep_every_days": row["deep_every_days"],
    }


def save_cleaning_settings(
    unit_id: int, light_after_nights: int, light_every_nights: int, deep_every_days: int
) -> None:
    execute(
        """INSERT INTO unit_cleaning_settings
               (unit_id, light_after_nights, light_every_nights, deep_every_days)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (unit_id) DO UPDATE
               SET light_after_nights = EXCLUDED.light_after_nights,
                   light_every_nights = EXCLUDED.light_every_nights,
                   deep_every_days    = EXCLUDED.deep_every_days""",
        (unit_id, light_after_nights, light_every_nights, deep_every_days),
    )


# --- Cleaning jobs --------------------------------------------------------

def _cleaning_job(row: dict[str, Any]) -> CleaningJob:
    return CleaningJob(
        id=row["id"],
        unit_id=row["unit_id"],
        date=row["date"],
        service_label=row["service_label"],
        staff_id=row["staff_id"],
        booking_id=row["booking_id"],
        status=row["status"],
        cost=row["cost"],
        notes=row["notes"],
    )


def list_cleaning_jobs(
    start: date | None = None,
    end: date | None = None,
    unit_ids: Iterable[int] | None = None,
    staff_id: int | None = None,
    statuses: Iterable[str] | None = None,
) -> list[CleaningJob]:
    clauses, params = [], []
    if start is not None:
        clauses.append("date >= %s")
        params.append(start)
    if end is not None:
        clauses.append("date < %s")
        params.append(end)
    if unit_ids is not None:
        unit_ids = list(unit_ids)
        if not unit_ids:
            return []
        clauses.append("unit_id = ANY(%s)")
        params.append(unit_ids)
    if staff_id is not None:
        clauses.append("staff_id = %s")
        params.append(staff_id)
    if statuses is not None:
        statuses = list(statuses)
        if not statuses:
            return []
        clauses.append("status = ANY(%s)")
        params.append(statuses)

    sql = "SELECT * FROM cleaning_jobs"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    return [_cleaning_job(row) for row in fetch_all(sql + " ORDER BY date, unit_id", tuple(params))]


def create_cleaning_job(
    unit_id: int,
    day: date,
    service_label: str,
    cost: Decimal,
    staff_id: int | None = None,
    booking_id: int | None = None,
    notes: str = "",
) -> int | None:
    """Add one job. Returns None if that flat is already being cleaned that day."""
    row = execute(
        """INSERT INTO cleaning_jobs (unit_id, date, service_label, cost, staff_id,
                                      booking_id, notes)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (unit_id, date) DO NOTHING
           RETURNING id""",
        (unit_id, day, service_label, cost, staff_id, booking_id, notes),
    )
    return row["id"] if row else None


def update_cleaning_job(job_id: int, **fields: Any) -> None:
    allowed = ("unit_id", "date", "service_label", "staff_id", "status", "cost", "notes")
    names = [name for name in fields if name in allowed]
    if not names:
        return
    sets = ", ".join(f"{name} = %s" for name in names)
    try:
        execute(f"UPDATE cleaning_jobs SET {sets} WHERE id = %s",
                (*(fields[n] for n in names), job_id))
    except Exception as error:
        raise _as_cleaning_clash(error) from error


def _as_cleaning_clash(error: Exception) -> Exception:
    """Turn the one-clean-a-day constraint into something a page can explain."""
    import psycopg

    if isinstance(error, psycopg.errors.UniqueViolation):
        return CleaningClash(
            "That flat is already being cleaned that day, and it only gets one clean "
            "a day. Move the other job first, or pick a different date."
        )
    return error


def delete_cleaning_job(job_id: int) -> None:
    execute("DELETE FROM cleaning_jobs WHERE id = %s", (job_id,))


def last_deep_clean(unit_id: int) -> date | None:
    """When this flat was last deep cleaned, so the next one is counted from it."""
    row = fetch_one(
        """SELECT max(date) AS last FROM cleaning_jobs
            WHERE unit_id = %s AND service_label = 'deep clean' AND status = 'done'""",
        (unit_id,),
    )
    return row["last"] if row else None


def schedule_jobs(planned: Sequence, costs: Mapping[tuple[int, str], Decimal]) -> int:
    """Put planned jobs on the calendar, skipping any that are already there.

    Existing jobs are never touched. A job moved to another day or handed to
    somebody else was moved by a person who knew something the rules did not,
    and re-running the rules must not undo that.
    """
    added = 0
    with transaction() as connection, connection.cursor() as cursor:
        for job in planned:
            cursor.execute(
                """INSERT INTO cleaning_jobs (unit_id, date, service_label, cost, booking_id, notes)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (unit_id, date) DO NOTHING
                   RETURNING id""",
                (job.unit_id, job.date, job.service_label,
                 costs.get((job.unit_id, job.service_label), Decimal("0.00")),
                 job.booking_id, job.reason),
            )
            if cursor.fetchone():
                added += 1
    return added


# --- Owner rates ----------------------------------------------------------

def list_owner_rates(unit_id: int | None = None, year: int | None = None) -> list[OwnerRate]:
    clauses, params = [], []
    if unit_id is not None:
        clauses.append("unit_id = %s")
        params.append(unit_id)
    if year is not None:
        clauses.append("year = %s")
        params.append(year)
    sql = "SELECT * FROM owner_rates"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    rows = fetch_all(sql + " ORDER BY year DESC, season_label", tuple(params))
    return [
        OwnerRate(r["unit_id"], r["season_label"], r["year"], r["nightly_rate"]) for r in rows
    ]


def save_owner_rate(unit_id: int, season_label: str, year: int, nightly_rate: Decimal) -> None:
    execute(
        """INSERT INTO owner_rates (unit_id, season_label, year, nightly_rate)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (unit_id, season_label, year)
           DO UPDATE SET nightly_rate = EXCLUDED.nightly_rate""",
        (unit_id, season_label, year, nightly_rate),
    )


def delete_owner_rate(unit_id: int, season_label: str, year: int) -> None:
    execute(
        "DELETE FROM owner_rates WHERE unit_id = %s AND season_label = %s AND year = %s",
        (unit_id, season_label, year),
    )


# --- Owner statements -----------------------------------------------------

def list_statements(year: int | None = None, statuses: Iterable[str] | None = None) -> list[dict]:
    clauses, params = [], []
    if year is not None:
        clauses.append("year = %s")
        params.append(year)
    if statuses is not None:
        statuses = list(statuses)
        if not statuses:
            return []
        clauses.append("status = ANY(%s)")
        params.append(statuses)
    sql = "SELECT * FROM owner_statements"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    return fetch_all(sql + " ORDER BY year DESC, month DESC, owner_id", tuple(params))


def get_statement(statement_id: int) -> dict | None:
    row = fetch_one("SELECT * FROM owner_statements WHERE id = %s", (statement_id,))
    if row is None:
        return None
    row["lines"] = fetch_all(
        "SELECT * FROM owner_statement_lines WHERE statement_id = %s ORDER BY line_number",
        (statement_id,),
    )
    return row


def find_statement(owner_id: int, year: int, month: int) -> dict | None:
    return fetch_one(
        "SELECT * FROM owner_statements WHERE owner_id = %s AND year = %s AND month = %s",
        (owner_id, year, month),
    )


def save_statement(statement, lines: Sequence[tuple[int, str, str, Decimal]]) -> int:
    """Store a worked-out statement, replacing any earlier run for that month.

    Replacing rather than adding: one statement per owner per month is the
    whole point, and regenerating after a late booking should correct the
    figures rather than leave the owner holding two different answers.
    """
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO owner_statements
                   (owner_id, year, month, rental_income, management_fees,
                    cleaning_costs, net_due)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (owner_id, year, month) DO UPDATE
                   SET rental_income   = EXCLUDED.rental_income,
                       management_fees = EXCLUDED.management_fees,
                       cleaning_costs  = EXCLUDED.cleaning_costs,
                       net_due         = EXCLUDED.net_due,
                       generated_on    = CURRENT_DATE
               RETURNING id""",
            (statement.owner_id, statement.year, statement.month, statement.rental_income,
             statement.management_fees, statement.cleaning_costs, statement.net),
        )
        statement_id = cursor.fetchone()["id"]
        cursor.execute(
            "DELETE FROM owner_statement_lines WHERE statement_id = %s", (statement_id,)
        )
        for number, (unit_id, kind, description, amount) in enumerate(lines, start=1):
            cursor.execute(
                """INSERT INTO owner_statement_lines
                       (statement_id, unit_id, line_number, kind, description, amount)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (statement_id, unit_id, number, kind, description, amount),
            )
    return statement_id


def set_statement_status(statement_id: int, status: str, paid_on: date | None = None) -> None:
    execute(
        "UPDATE owner_statements SET status = %s, paid_on = %s WHERE id = %s",
        (status, paid_on, statement_id),
    )


def save_season_making_room(
    changes: Sequence,
    season_id: int | None,
    label: str,
    start_date: date,
    end_date: date,
    year: int,
) -> None:
    """Write a season period, moving whatever else held those dates.

    `changes` is the plan from lib.seasons.carve_out - this only applies it.
    Order matters and is the whole reason it is one transaction: the periods
    giving way are shrunk or removed first, so that by the time the new period
    is written there is nothing left for it to collide with.
    """
    with transaction() as connection, connection.cursor() as cursor:
        for change in changes:
            if change.kind == "removed":
                cursor.execute(
                    "DELETE FROM season_definitions WHERE id = %s", (change.original.id,)
                )
                continue
            first, *rest = change.replacements
            cursor.execute(
                """UPDATE season_definitions
                      SET start_date = %s, end_date = %s WHERE id = %s""",
                (first.start_date, first.end_date, change.original.id),
            )
            for part in rest:
                cursor.execute(
                    """INSERT INTO season_definitions (label, start_date, end_date, year)
                       VALUES (%s, %s, %s, %s)""",
                    (part.label, part.start_date, part.end_date, part.year),
                )

        if season_id is None:
            cursor.execute(
                """INSERT INTO season_definitions (label, start_date, end_date, year)
                   VALUES (%s, %s, %s, %s)""",
                (label, start_date, end_date, year),
            )
        else:
            cursor.execute(
                """UPDATE season_definitions
                      SET label = %s, start_date = %s, end_date = %s, year = %s
                    WHERE id = %s""",
                (label, start_date, end_date, year, season_id),
            )


def list_clients_with_stays(search: str = "", limit: int = 50) -> list[dict[str, Any]]:
    """Clients with how much history each has, for the list view.

    Counted in the database rather than by loading every booking: the list is
    for finding somebody, and it should not get slower as the business does.
    """
    clauses, params = [], []
    if search.strip():
        clauses.append("(c.name ILIKE %s OR c.phone ILIKE %s OR c.email ILIKE %s)")
        term = f"%{search.strip()}%"
        params.extend([term, term, term])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    return fetch_all(
        f"""SELECT c.*,
                   count(b.id) FILTER (WHERE b.status = 'confirmed') AS stays,
                   max(b.check_out) FILTER (WHERE b.status = 'confirmed') AS last_stay
              FROM clients c
              LEFT JOIN bookings b ON b.client_id = c.id
              {where}
             GROUP BY c.id
             ORDER BY stays DESC, c.name
             LIMIT %s""",
        tuple(params),
    )


def bookings_for_client(client_id: int) -> list[Booking]:
    rows = fetch_all(
        "SELECT * FROM bookings WHERE client_id = %s ORDER BY check_in DESC", (client_id,)
    )
    return [_booking(row) for row in rows]


def quotes_for_client(client_id: int) -> list[SavedQuote]:
    rows = fetch_all(
        "SELECT * FROM quotes WHERE client_id = %s ORDER BY generated_on DESC", (client_id,)
    )
    return [_saved_quote(row) for row in rows]


def merge_clients(from_id: int, into_id: int) -> int:
    """Move one client's history onto another and remove the duplicate.

    Typing a guest's name slightly differently makes a second record, and two
    half-histories are worse than one whole one. Everything is moved before the
    duplicate goes, so nothing is orphaned.
    """
    if from_id == into_id:
        return 0
    moved = 0
    with transaction() as connection, connection.cursor() as cursor:
        for table in ("bookings", "quotes"):
            cursor.execute(
                f"UPDATE {table} SET client_id = %s WHERE client_id = %s", (into_id, from_id)
            )
            moved += cursor.rowcount
        cursor.execute("DELETE FROM clients WHERE id = %s", (from_id,))
    return moved


def delete_client(client_id: int) -> None:
    """Remove a client. Their bookings keep the dates but lose the name."""
    execute("DELETE FROM clients WHERE id = %s", (client_id,))


# --- Owner payments -------------------------------------------------------

def _payment(row: dict[str, Any]) -> OwnerPayment:
    return OwnerPayment(
        row["id"], row["statement_id"], row["paid_on"], row["amount"],
        row["reference"], row["notes"],
    )


def list_payments(statement_id: int) -> list[OwnerPayment]:
    rows = fetch_all(
        "SELECT * FROM owner_payments WHERE statement_id = %s ORDER BY paid_on, id",
        (statement_id,),
    )
    return [_payment(row) for row in rows]


def _resettle(cursor, statement_id: int) -> None:
    """Bring a statement's flag back in line with what has been paid.

    The payments are the record; the flag is a convenience for the list view.
    Recomputed in the same transaction as every change to them, so the two
    cannot drift apart.
    """
    cursor.execute(
        """SELECT s.net_due,
                  COALESCE((SELECT sum(amount) FROM owner_payments p
                             WHERE p.statement_id = s.id), 0) AS paid,
                  (SELECT max(paid_on) FROM owner_payments p
                    WHERE p.statement_id = s.id) AS last_paid,
                  s.status
             FROM owner_statements s WHERE s.id = %s""",
        (statement_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return
    settled = abs(row["net_due"] - row["paid"]) <= Decimal("0.01")
    if settled and row["paid"] != 0:
        cursor.execute(
            "UPDATE owner_statements SET status = 'paid', paid_on = %s WHERE id = %s",
            (row["last_paid"], statement_id),
        )
    elif row["status"] == "paid":
        # A payment was removed or corrected downwards - it is not settled now.
        cursor.execute(
            "UPDATE owner_statements SET status = 'sent', paid_on = NULL WHERE id = %s",
            (statement_id,),
        )


def record_payment(
    statement_id: int,
    paid_on: date,
    amount: Decimal,
    reference: str = "",
    notes: str = "",
) -> int:
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO owner_payments (statement_id, paid_on, amount, reference, notes)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (statement_id, paid_on, amount, reference, notes),
        )
        payment_id = cursor.fetchone()["id"]
        _resettle(cursor, statement_id)
    return payment_id


def delete_payment(payment_id: int) -> None:
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM owner_payments WHERE id = %s RETURNING statement_id", (payment_id,)
        )
        row = cursor.fetchone()
        if row:
            _resettle(cursor, row["statement_id"])


def payment_history(year: int | None = None, owner_id: int | None = None) -> list[dict[str, Any]]:
    """Every payment made, with the owner and month it settles.

    One query rather than a payment list per statement: the question this
    answers is "what have we paid this owner, and when", which is about the
    run of them rather than any single month.
    """
    clauses, params = [], []
    if year is not None:
        clauses.append("EXTRACT(YEAR FROM p.paid_on) = %s")
        params.append(year)
    if owner_id is not None:
        clauses.append("s.owner_id = %s")
        params.append(owner_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return fetch_all(
        f"""SELECT p.*, s.owner_id, s.year AS statement_year, s.month AS statement_month,
                   s.net_due, o.name AS owner_name
              FROM owner_payments p
              JOIN owner_statements s ON s.id = p.statement_id
              JOIN owners o ON o.id = s.owner_id
              {where}
             ORDER BY p.paid_on DESC, p.id DESC""",
        tuple(params),
    )


def unsettled_statements() -> list[dict[str, Any]]:
    """Statements with money still outstanding, oldest first."""
    return fetch_all(
        """SELECT s.*, o.name AS owner_name,
                  COALESCE((SELECT sum(amount) FROM owner_payments p
                             WHERE p.statement_id = s.id), 0) AS paid
             FROM owner_statements s
             JOIN owners o ON o.id = s.owner_id
            WHERE s.status <> 'draft'
              AND abs(s.net_due - COALESCE((SELECT sum(amount) FROM owner_payments p
                                             WHERE p.statement_id = s.id), 0)) > 0.01
            ORDER BY s.year, s.month, o.name"""
    )
