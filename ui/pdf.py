"""The quote as a PDF, for emailing (spec 3.5).

The WhatsApp-style text in lib.quotes covers most of what the parents send;
this is for when a guest wants something that looks like a document. Both show
the same build-up - a line per season touched, then the total - so a guest
comparing the two never sees different numbers.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Sequence

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image as ReportLabImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from lib.models import QuoteLine
from ui.brand import LOGO_PRINT, NAVY
from ui.format import CURRENCY, money

INK = colors.HexColor(NAVY)
MUTED = colors.HexColor("#6b6b6b")
RULE = colors.HexColor("#d9d9d9")
BAND = colors.HexColor("#f4f4f4")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontSize=20, leading=24,
            alignment=0, textColor=INK, spaceAfter=2,
        ),
        "sub": ParagraphStyle(
            "sub", parent=base["Normal"], fontSize=10, textColor=MUTED, spaceAfter=14
        ),
        "body": ParagraphStyle("body", parent=base["Normal"], fontSize=10.5, leading=15, textColor=INK),
        "right": ParagraphStyle("right", parent=base["Normal"], fontSize=10.5, alignment=TA_RIGHT),
        "small": ParagraphStyle("small", parent=base["Normal"], fontSize=9, textColor=MUTED, leading=13),
        "letterhead": ParagraphStyle(
            "letterhead", parent=base["Normal"], fontSize=11, leading=16,
            alignment=TA_RIGHT, textColor=MUTED,
        ),
    }


def _letterhead(style, reference: int | None, generated_on: date | None,
                business_name: str, heading: str = "Quote"):
    """Logo on the left, what the document is on the right.

    The guest sees this page and nothing else of the business, so it carries
    the mark rather than a plain word at the top of an otherwise blank sheet.
    """
    meta = heading
    if reference:
        meta += f"<br/>Reference {reference}"
    if generated_on:
        meta += f"<br/>{generated_on.strftime('%d %B %Y')}"

    if LOGO_PRINT.exists():
        badge = ReportLabImage(str(LOGO_PRINT), width=38 * mm, height=38 * mm * 515 / 720)
    else:
        badge = Paragraph(business_name, style["title"])

    head = Table(
        [[badge, Paragraph(meta, style["letterhead"])]],
        colWidths=[62 * mm, None],
        hAlign="LEFT",
    )
    head.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 0), (-1, -1), 0.8, RULE),
    ]))
    return head


def quote_pdf(
    unit_name: str,
    client_name: str,
    check_in: date,
    check_out: date,
    lines: Sequence[QuoteLine],
    total: Decimal,
    guests: int | None = None,
    reference: int | None = None,
    generated_on: date | None = None,
    business_name: str = "RentalMan",
    notes: str = "",
) -> bytes:
    """Render one quote and hand back the PDF bytes."""
    style = _styles()
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=22 * mm, rightMargin=22 * mm, topMargin=20 * mm, bottomMargin=20 * mm,
        title=f"Quote {reference or ''} - {unit_name}".strip(),
        author=business_name,
    )

    nights = (check_out - check_in).days
    story = [_letterhead(style, reference, generated_on, business_name), Spacer(1, 16)]

    details = [
        ["Guest", client_name],
        ["Flat", unit_name],
        ["Arrive", check_in.strftime("%A %d %B %Y")],
        ["Depart", check_out.strftime("%A %d %B %Y")],
        ["Nights", str(nights)],
    ]
    if guests:
        details.append(["Guests", str(guests)])

    detail_table = Table(details, colWidths=[30 * mm, None], hAlign="LEFT")
    detail_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), MUTED),
        ("FONTSIZE", (0, 0), (-1, -1), 10.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.extend([detail_table, Spacer(1, 14)])
    story.append(_price_table(lines, total, style))

    if notes:
        story.extend([Spacer(1, 12), Paragraph(notes, style["small"])])
    story.extend([
        Spacer(1, 18),
        Paragraph(
            "Prices are per night and include every night of the stay except the day of "
            "departure. Let us know if you would like to go ahead and we will hold the dates.",
            style["small"],
        ),
    ])

    document.build(story)
    return buffer.getvalue()


def _price_table(lines: Sequence[QuoteLine], total: Decimal, style) -> Table:
    """The build-up: one row per season segment, then the total.

    Shown even when a stay sits in a single season, so the guest always sees
    the nightly rate rather than only a lump sum.
    """
    header = ["Nights", "Season", "Per night", "Subtotal"]
    rows = [header]
    for line in lines:
        span = (
            line.first_night.strftime("%d %b")
            if line.nights == 1
            else f"{line.first_night.strftime('%d %b')} - {line.last_night.strftime('%d %b')}"
        )
        rows.append([
            f"{span}  ({line.nights})",
            line.season_label,
            money(line.nightly_rate),
            money(line.subtotal),
        ])
    rows.append(["", "", "Total", money(total)])

    table = Table(rows, colWidths=[52 * mm, 30 * mm, 34 * mm, 34 * mm], hAlign="LEFT")
    last = len(rows) - 1
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BACKGROUND", (0, 0), (-1, 0), BAND),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, RULE),
        ("LINEABOVE", (0, last), (-1, last), 0.9, INK),
        ("FONTNAME", (2, last), (-1, last), "Helvetica-Bold"),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def statement_pdf(
    owner_name: str,
    statement,
    reference: int | None = None,
    generated_on: date | None = None,
    business_name: str = "RentalMan",
) -> bytes:
    """An owner's month, itemised per flat then totalled (spec 3.8).

    Each flat gets its own block - income, then what comes off it, then the net
    for that flat - so an owner with several can see which one earned and which
    one cost. No tax line: the figure at the bottom is simply what is owed.
    """
    style = _styles()
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=22 * mm, rightMargin=22 * mm, topMargin=20 * mm, bottomMargin=20 * mm,
        title=f"Statement {statement.period_name} - {owner_name}",
        author=business_name,
    )

    story = [
        _letterhead(style, reference, generated_on, business_name, heading="Statement"),
        Spacer(1, 14),
        Paragraph(f"<b>{owner_name}</b>", style["body"]),
        Paragraph(statement.period_name, style["sub"]),
    ]

    for unit in statement.units:
        story.append(Paragraph(f"<b>{unit.unit_name}</b>", style["body"]))
        rows = [["", "", ""]]
        rows = [[
            "Rental income",
            f"{unit.nights} night(s) let" if unit.nights else "not let this month",
            money(unit.rental_income),
        ]]
        for share in unit.stays:
            for line in share.lines:
                rows.append([
                    "",
                    f"    {line.first_night.strftime('%d %b')} - "
                    f"{line.last_night.strftime('%d %b')}: {line.nights} x "
                    f"{money(line.nightly_rate)} ({line.season_label})",
                    money(line.subtotal),
                ])
        rows.append(["Management fee", "", f"({money(unit.management_fee)})"])
        rows.append([
            "Cleaning",
            f"{len(unit.cleans)} clean(s)" if unit.cleans else "none",
            f"({money(unit.cleaning_cost)})",
        ])
        for job in unit.cleans:
            rows.append(["", f"    {job.date.strftime('%d %b')}: {job.service_label}",
                         f"({money(job.cost)})"])
        rows.append(["Net for this flat", "", money(unit.net)])
        story.extend([_unit_table(rows), Spacer(1, 12)])

    story.extend([
        Spacer(1, 4),
        _totals_table([
            ["Rental income", money(statement.rental_income)],
            ["Less management fees", f"({money(statement.management_fees)})"],
            ["Less cleaning", f"({money(statement.cleaning_costs)})"],
            ["Net due to you", money(statement.net)],
        ]),
        Spacer(1, 16),
        Paragraph(
            "Figures in brackets are deducted. Rental income is the nights actually "
            "let during the month, valued at the agreed nightly rate for the season "
            "each night falls in.",
            style["small"],
        ),
    ])

    document.build(story)
    return buffer.getvalue()


def _unit_table(rows) -> Table:
    table = Table(rows, colWidths=[38 * mm, None, 30 * mm], hAlign="LEFT")
    last = len(rows) - 1
    table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("TEXTCOLOR", (1, 0), (1, -1), MUTED),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("LINEABOVE", (0, last), (-1, last), 0.5, RULE),
        ("FONTNAME", (0, last), (-1, last), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def _totals_table(rows) -> Table:
    table = Table(rows, colWidths=[None, 34 * mm], hAlign="LEFT")
    last = len(rows) - 1
    table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10.5),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BACKGROUND", (0, 0), (-1, -1), BAND),
        ("LINEABOVE", (0, last), (-1, last), 0.9, INK),
        ("FONTNAME", (0, last), (-1, last), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (0, -1), 8),
        ("RIGHTPADDING", (1, 0), (1, -1), 8),
    ]))
    return table
