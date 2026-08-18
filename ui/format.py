"""Formatting shared by every screen, so money and dates read the same way.

CURRENCY is the one place to change the symbol if these are not rands.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

CURRENCY = "R"


def money(amount: Decimal | float | int | None, blank: str = "-") -> str:
    """A figure a person can scan: R1 250.00, with a thin space as separator."""
    if amount is None:
        return blank
    return f"{CURRENCY}{Decimal(amount):,.2f}".replace(",", " ")


def short_date(day: date) -> str:
    # Built by hand rather than with %-d, which is a Linux-only strftime
    # extension and raises on Windows - where these laptops actually are.
    return f"{day.day} {day.strftime('%b')}"


def full_date(day: date) -> str:
    return day.strftime("%d %b %Y")


def date_range(check_in: date, check_out: date) -> str:
    """'12-15 Mar 2027' or '28 Feb - 3 Mar 2027', whichever the dates call for."""
    if check_in.year == check_out.year and check_in.month == check_out.month:
        return f"{check_in.day}-{check_out.day} {check_in.strftime('%b %Y')}"
    if check_in.year == check_out.year:
        return f"{check_in.strftime('%d %b')} - {check_out.strftime('%d %b %Y')}"
    return f"{full_date(check_in)} - {full_date(check_out)}"


def nights(count: int) -> str:
    return "1 night" if count == 1 else f"{count} nights"
