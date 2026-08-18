"""Fill an empty database with plausible demo data.

    python -m db.seed          # only if the database is empty
    python -m db.seed --force  # add it anyway

This is for trying the calendar out before the real flats are captured - the
names and figures are invented. It is not part of the app.
"""

from __future__ import annotations

import sys
from datetime import date, time, timedelta
from decimal import Decimal

from db import queries

OWNERS = [
    ("A. & M. Petersen", "082 555 0101", "petersen@example.com"),
    ("Rademeyer Family Trust", "083 555 0144", "trust@example.com"),
    ("S. Nkosi", "084 555 0177", "nkosi@example.com"),
]

# name, beds, sleeps, owner index, management fee, min nights, group
UNITS = [
    ("Seaview 1", 1, 2, 0, "1800", 2, "Beachfront"),
    ("Seaview 2", 2, 4, 0, "1800", 2, "Beachfront"),
    ("Seaview 3", 2, 4, 0, "1800", 2, "Beachfront"),
    ("Seaview 5", 3, 6, 0, "2200", 2, "Beachfront"),
    ("Dune Cottage", 3, 6, 1, "2500", 2, "Beachfront"),
    ("Milkwood 2", 2, 4, 1, "1800", 2, "Village"),
    ("Milkwood 4", 2, 4, 1, "1800", 2, "Village"),
    ("Milkwood 7", 1, 2, 1, "1500", 1, "Village"),
    ("Protea Flat", 2, 5, 1, "1900", 2, "Village"),
    ("Aloe Cottage", 3, 6, 2, "2400", 2, "Village"),
    ("Harbour View 1", 2, 4, 2, "2000", 2, "Harbour"),
    ("Harbour View 2", 2, 4, 2, "2000", 2, "Harbour"),
    ("Harbour View 6", 4, 8, 2, "3200", 2, "Harbour"),
    ("Lighthouse Loft", 1, 2, 2, "1600", 2, "Harbour"),
    ("Bay Cottage", 3, 7, 0, "2600", 2, "Harbour"),
]

# Rates per season, by how many beds the flat has.
NIGHTLY = {
    1: {"Low": "750", "Medium": "1100", "High": "1900"},
    2: {"Low": "950", "Medium": "1450", "High": "2400"},
    3: {"Low": "1250", "Medium": "1850", "High": "3100"},
    4: {"Low": "1700", "Medium": "2500", "High": "4200"},
}

CLIENTS = [
    ("M. Abrahams", "082 555 0201"),
    ("The Coetzee family", "083 555 0233"),
    ("J. & P. Naidoo", "084 555 0266"),
    ("D. Fourie", "079 555 0288"),
    ("H. Steyn", "071 555 0299"),
]


def season_rows(year: int) -> list[tuple[str, date, date]]:
    """A southern-hemisphere coastal year: full over the December holidays."""
    return [
        ("High", date(year, 1, 1), date(year, 1, 15)),
        ("Medium", date(year, 1, 16), date(year, 2, 28)),
        ("Low", date(year, 3, 1), date(year, 6, 30)),
        ("Medium", date(year, 7, 1), date(year, 7, 15)),
        ("Low", date(year, 7, 16), date(year, 9, 15)),
        ("Medium", date(year, 9, 16), date(year, 11, 30)),
        ("High", date(year, 12, 1), date(year, 12, 31)),
    ]


def database_is_empty() -> bool:
    return not queries.list_owners() and not queries.list_units(include_inactive=True)


def seed() -> None:
    owner_ids = [queries.create_owner(name, phone, email) for name, phone, email in OWNERS]

    unit_ids = []
    for name, beds, sleeps, owner_index, fee, min_nights, group in UNITS:
        unit_ids.append(
            queries.create_unit(
                name=name,
                beds=beds,
                sleeps=sleeps,
                owner_id=owner_ids[owner_index],
                monthly_management_fee=Decimal(fee),
                min_nights=min_nights,
                checkout_time=time(10, 0),
                checkin_time=time(14, 0),
                group_tag=group,
            )
        )

    this_year = date.today().year
    for year in (this_year, this_year + 1):
        for label, start, end in season_rows(year):
            queries.create_season(label, start, end, year)

        for unit_id, (_, beds, *_rest) in zip(unit_ids, UNITS):
            for label, amount in NIGHTLY[beds].items():
                # High season asks for a longer stay than the flat's own minimum -
                # the case the multi-season minimum rule exists to handle.
                queries.save_client_rate(
                    unit_id, label, year, Decimal(amount), 5 if label == "High" else None
                )

    # Same-day turnover everywhere, which is the norm, except the largest flat,
    # which cannot be turned around inside the midday window in high season.
    biggest = unit_ids[UNITS.index(("Harbour View 6", 4, 8, 2, "3200", 2, "Harbour"))]
    queries.save_turnover_rule(biggest, None, 0)
    queries.save_turnover_rule(biggest, "High", 1)

    client_ids = [queries.create_client(name, phone) for name, phone in CLIENTS]

    # A month or so of bookings around today, so the grid has something on it.
    today = date.today()
    plan = [
        (0, 0, -6, 4, "confirmed"),
        (0, 1, 2, 5, "confirmed"),
        (2, 2, -2, 7, "confirmed"),
        (4, 3, 1, 3, "confirmed"),
        (4, 4, 6, 4, "confirmed"),
        (6, 0, -4, 9, "confirmed"),
        (8, 1, 3, 2, "quoted"),
        (10, 2, 0, 5, "confirmed"),
        (12, 3, -1, 6, "confirmed"),
        (12, 4, 8, 4, "confirmed"),
        (14, 0, 4, 10, "confirmed"),
        (5, 1, 12, 3, "enquiry"),
    ]
    for unit_index, client_index, offset, length, status in plan:
        check_in = today + timedelta(days=offset)
        queries.create_booking(
            unit_ids[unit_index], client_ids[client_index], check_in,
            check_in + timedelta(days=length), status,
        )

    queries.create_unit_block(
        unit_ids[3], today + timedelta(days=20), today + timedelta(days=24), "Repaint"
    )

    print(f"Seeded {len(owner_ids)} owners, {len(unit_ids)} units, "
          f"{len(plan)} bookings and two years of seasons and rates.")


def main(argv: list[str]) -> int:
    if not database_is_empty() and "--force" not in argv:
        print("The database already has data in it. Re-run with --force to add more anyway.")
        return 1
    seed()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
