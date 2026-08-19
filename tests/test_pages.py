"""Every page is actually run, with the database stubbed out.

Streamlit's own AppTest executes a page script in-process, so these catch the
things a syntax check cannot: a widget given a bad argument, a lookup against a
missing key, a page that falls over when there is nothing on file yet. The
database functions are replaced with fakes, so no connection is needed and the
data each page sees is known.
"""

from datetime import date, time, timedelta
from decimal import Decimal

import pytest
from streamlit.testing.v1 import AppTest

from db import connection, queries
from lib.models import (
    CLEAN_TYPES,
    CONFIRMED,
    QUOTE_OPEN,
    CleaningJob,
    CleaningServiceType,
    CleaningStaff,
    Booking,
    Client,
    ClientRate,
    Owner,
    QuoteLine,
    SavedQuote,
    SeasonDefinition,
    TurnoverRule,
    Unit,
    UnitBlock,
)

PAGES = [
    "app.py",
    "pages/1_Calendar.py",
    "pages/2_Search.py",
    "pages/3_Units.py",
    "pages/4_Seasons.py",
    "pages/5_Bookings.py",
    "pages/6_Quotes.py",
    "pages/7_Cleaning.py",
]

TODAY = date.today()
YEAR = TODAY.year

OWNERS = [Owner(1, "A. Petersen", "082 555 0101"), Owner(2, "S. Nkosi")]
UNITS = [
    Unit(1, "Seaview 3", 2, 4, 1, Decimal("1800.00"), 2, time(10, 0), time(14, 0), "Beachfront"),
    Unit(2, "Harbour View 6", 4, 8, 2, Decimal("3200.00"), 2, group_tag="Harbour"),
]
SEASONS = [
    SeasonDefinition(1, "High", date(YEAR, 1, 1), date(YEAR, 1, 15), YEAR),
    SeasonDefinition(2, "Medium", date(YEAR, 1, 16), date(YEAR, 12, 31), YEAR),
]
RATES = [
    ClientRate(unit.id, definition.label, YEAR, Decimal("2400.00"), None)
    for unit in UNITS
    for definition in SEASONS
]
CLIENTS = [Client(1, "M. Abrahams", "082 555 0201")]
BOOKINGS = [
    Booking(1, 1, 1, TODAY - timedelta(days=2), TODAY + timedelta(days=3), CONFIRMED,
            Decimal("12000.00"), "Repeat guest"),
]
RULES = [TurnoverRule(2, "High", 1)]
CLEANERS = [CleaningStaff(1, "Nomsa Dlamini", "082 555 0777")]
SERVICES = [
    CleaningServiceType(None, label, Decimal("450.00"), 120) for label in CLEAN_TYPES
]
CLEANING_JOBS = [
    CleaningJob(1, 1, TODAY, "changeover clean", 1, None, "scheduled", Decimal("450.00"),
                "Guest out and the next guest in the same day"),
    CleaningJob(2, 2, TODAY + timedelta(days=2), "deep clean", None, None, "scheduled",
                Decimal("900.00"), "Periodic deep clean"),
]
QUOTE_LINES = (
    QuoteLine("Medium", TODAY, TODAY + timedelta(days=2), 3,
              Decimal("2400.00"), Decimal("7200.00")),
)
QUOTES = [
    SavedQuote(1, 2, 1, TODAY, TODAY + timedelta(days=3), 4, Decimal("7200.00"),
               QUOTE_OPEN, TODAY - timedelta(days=9), QUOTE_LINES, "", None),
]
BLOCKS = [UnitBlock(1, 2, TODAY + timedelta(days=10), TODAY + timedelta(days=12), "Repaint")]


@pytest.fixture
def stubbed_database(monkeypatch):
    """Point every query at fixed data, and tell the pages the database is up."""
    monkeypatch.setattr(connection, "check_connection", lambda: (True, "Connected to test."))
    monkeypatch.setattr(queries, "list_owners", lambda: OWNERS)
    monkeypatch.setattr(queries, "list_units", lambda include_inactive=False: UNITS)
    monkeypatch.setattr(queries, "get_unit", lambda unit_id: UNITS[0])
    monkeypatch.setattr(queries, "list_seasons", lambda year=None: SEASONS)
    monkeypatch.setattr(queries, "list_season_years", lambda: [YEAR])
    monkeypatch.setattr(queries, "list_client_rates", lambda unit_id=None, year=None: RATES)
    monkeypatch.setattr(queries, "list_clients", lambda: CLIENTS)
    monkeypatch.setattr(
        queries, "list_bookings",
        lambda start=None, end=None, unit_ids=None, statuses=None: BOOKINGS,
    )
    monkeypatch.setattr(queries, "list_turnover_rules", lambda unit_id=None: RULES)
    monkeypatch.setattr(queries, "list_unit_blocks", lambda start=None, end=None: BLOCKS)
    monkeypatch.setattr(queries, "list_quotes", lambda statuses=None: QUOTES)
    monkeypatch.setattr(queries, "get_quote", lambda quote_id: QUOTES[0])
    monkeypatch.setattr(queries, "save_quote", lambda *args, **kwargs: 1)
    monkeypatch.setattr(queries, "set_quote_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(queries, "get_booking", lambda booking_id: BOOKINGS[0])
    monkeypatch.setattr(
        queries, "find_clients",
        lambda term, limit=8: [c for c in CLIENTS if term.strip().lower() in c.name.lower()],
    )
    monkeypatch.setattr(
        queries, "get_clients",
        lambda ids: {c.id: c for c in CLIENTS if c.id in set(ids)},
    )
    monkeypatch.setattr(
        queries, "get_client", lambda cid: next((c for c in CLIENTS if c.id == cid), None)
    )
    monkeypatch.setattr(queries, "create_client", lambda *args, **kwargs: 77)
    monkeypatch.setattr(queries, "accept_quote", lambda quote, notes="": 99)
    monkeypatch.setattr(queries, "cancel_quote", lambda *args, **kwargs: None)
    monkeypatch.setattr(queries, "list_cleaning_staff", lambda include_inactive=False: CLEANERS)
    monkeypatch.setattr(queries, "list_service_types", lambda: SERVICES)
    monkeypatch.setattr(
        queries, "list_cleaning_jobs",
        lambda start=None, end=None, unit_ids=None, staff_id=None, statuses=None: CLEANING_JOBS,
    )
    monkeypatch.setattr(queries, "list_unit_cleaning_rates", lambda unit_id=None: [])
    monkeypatch.setattr(
        queries, "get_cleaning_settings",
        lambda unit_id: {"light_after_nights": 10, "light_every_nights": 7, "deep_every_days": 91},
    )
    monkeypatch.setattr(queries, "last_deep_clean", lambda unit_id: None)
    monkeypatch.setattr(queries, "schedule_jobs", lambda planned, costs: len(planned))
    monkeypatch.setattr(queries, "update_cleaning_job", lambda *args, **kwargs: None)
    return monkeypatch


@pytest.mark.parametrize("path", PAGES)
def test_page_runs_without_error(path, stubbed_database):
    app = AppTest.from_file(path, default_timeout=30).run()

    assert not app.exception, [str(e) for e in app.exception]


@pytest.mark.parametrize("path", PAGES)
def test_page_runs_with_an_empty_database(path, stubbed_database, monkeypatch):
    """Day one, before anything has been captured, must not be a wall of errors."""
    for name in ("list_owners", "list_units", "list_seasons", "list_client_rates",
                 "list_clients", "list_bookings", "list_turnover_rules", "list_unit_blocks",
                 "list_quotes", "list_cleaning_staff", "list_cleaning_jobs",
                 "list_unit_cleaning_rates"):
        monkeypatch.setattr(queries, name, lambda *args, **kwargs: [])
    monkeypatch.setattr(queries, "list_season_years", lambda: [])

    app = AppTest.from_file(path, default_timeout=30).run()

    assert not app.exception, [str(e) for e in app.exception]


def test_home_page_reports_what_is_set_up(stubbed_database):
    app = AppTest.from_file("app.py", default_timeout=30).run()

    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Units"] == "2"
    assert metrics["Owners"] == "2"
    assert any("rate for every season" in element.value for element in app.success)


def test_home_page_names_the_units_missing_a_rate(stubbed_database, monkeypatch):
    monkeypatch.setattr(queries, "list_client_rates", lambda unit_id=None, year=None: [])

    app = AppTest.from_file("app.py", default_timeout=30).run()

    assert any("Seaview 3" in element.value for element in app.warning)


def test_calendar_draws_the_grid_and_lists_the_months_bookings(stubbed_database):
    app = AppTest.from_file("pages/1_Calendar.py", default_timeout=30).run()

    grid = "".join(element.value for element in app.markdown)
    assert "rm-grid" in grid
    assert "M. Abrahams" in grid  # the tooltip on the booked cells
    assert any("Bookings in" in element.value for element in app.subheader)


def test_calendar_says_so_when_filters_match_nothing(stubbed_database):
    app = AppTest.from_file("pages/1_Calendar.py", default_timeout=30)
    app.run()

    app.expander[0].number_input[0].set_value(99).run()  # minimum beds

    assert any("No units match" in element.value for element in app.info)


def test_seasons_page_shows_the_year_map_and_flags_gaps(stubbed_database, monkeypatch):
    monkeypatch.setattr(
        queries, "list_seasons",
        lambda year=None: [SeasonDefinition(1, "High", date(YEAR, 1, 1), date(YEAR, 1, 15), YEAR)],
    )

    app = AppTest.from_file("pages/4_Seasons.py", default_timeout=30).run()

    assert any("rm-year" in element.value for element in app.markdown)
    assert any("No season covers" in element.value for element in app.warning)


def test_pages_explain_themselves_when_the_database_is_unreachable(monkeypatch):
    monkeypatch.setattr(
        connection, "check_connection", lambda: (False, "No database connection string found.")
    )

    app = AppTest.from_file("pages/1_Calendar.py", default_timeout=30).run()

    assert not app.exception
    assert any("cannot use its database" in element.value for element in app.error)
    # The heading is the same whatever went wrong; the cause is what matters.
    assert any("No database connection string found." in element.value for element in app.code)


def button_labelled(app, label):
    return next(button for button in app.button if button.label == label)


def test_bookings_page_refuses_dates_that_are_already_taken(stubbed_database):
    """The stubbed booking covers today, which is what the form defaults to."""
    app = AppTest.from_file("pages/5_Bookings.py", default_timeout=30).run()

    assert any("already booked" in element.value for element in app.error)


def test_bookings_page_prices_the_stay_from_the_rate_file(stubbed_database, monkeypatch):
    monkeypatch.setattr(
        queries, "list_bookings",
        lambda start=None, end=None, unit_ids=None, statuses=None: [],
    )

    app = AppTest.from_file("pages/5_Bookings.py", default_timeout=30).run()

    assert any("is free for these dates" in element.value for element in app.success)
    # One night at the stubbed rate of 2400.
    assert any("R2 400.00" in element.value for element in app.caption)


def test_saving_a_booking_writes_it_once_with_the_dates_entered(stubbed_database, monkeypatch):
    monkeypatch.setattr(
        queries, "list_bookings",
        lambda start=None, end=None, unit_ids=None, statuses=None: [],
    )
    recorded = []
    monkeypatch.setattr(
        queries, "create_booking",
        lambda *args, **kwargs: (recorded.append((args, kwargs)), 42)[1],
    )

    app = AppTest.from_file("pages/5_Bookings.py", default_timeout=30).run()
    app.text_input(key="add_client_0_name").set_value("Abrahams").run()
    app.radio(key="add_client_0_match").set_value(1).run()  # the guest already on file
    button_labelled(app, "Save booking").click().run()

    assert len(recorded) == 1
    args, _ = recorded[0]
    unit_id, client_id, check_in, check_out, status = args[:5]
    assert (unit_id, client_id, status) == (1, 1, "confirmed")
    assert check_out == check_in + timedelta(days=1)


def test_a_booking_that_would_land_on_another_is_not_saved(stubbed_database, monkeypatch):
    """The clash is caught before the write, not reported after it."""
    recorded = []
    monkeypatch.setattr(
        queries, "create_booking", lambda *args, **kwargs: recorded.append(args) or 1
    )

    app = AppTest.from_file("pages/5_Bookings.py", default_timeout=30).run()
    app.text_input(key="add_client_0_name").set_value("New Guest").run()
    button_labelled(app, "Save booking").click().run()

    assert any("already booked" in element.value for element in app.error)
    assert recorded == [], "a clashing booking must not reach the database"


def test_bookings_page_lists_what_is_on_file(stubbed_database):
    app = AppTest.from_file("pages/5_Bookings.py", default_timeout=30).run()

    assert any("1 booking(s)." in element.value for element in app.caption)


def test_a_stay_over_a_turnover_gap_warns_but_can_still_be_captured(stubbed_database, monkeypatch):
    """History is a fact: a past same-day turnover is recorded, not refused."""
    yesterday = TODAY - timedelta(days=3)
    monkeypatch.setattr(
        queries, "list_bookings",
        lambda start=None, end=None, unit_ids=None, statuses=None: [
            Booking(9, 1, 1, yesterday, TODAY, CONFIRMED)
        ],
    )
    monkeypatch.setattr(queries, "list_turnover_rules", lambda unit_id=None: [TurnoverRule(1, None, 1)])
    recorded = []
    monkeypatch.setattr(
        queries, "create_booking", lambda *args, **kwargs: recorded.append(args) or 43
    )

    app = AppTest.from_file("pages/5_Bookings.py", default_timeout=30).run()

    assert any("turnover gap" in element.value for element in app.warning)
    assert not app.error

    app.text_input(key="add_client_0_name").set_value("New Guest").run()
    button_labelled(app, "Save booking").click().run()

    assert len(recorded) == 1


def test_a_reachable_but_empty_database_names_the_command_that_fixes_it(monkeypatch):
    """A fresh Neon project answers fine and has no tables - say so, don't crash."""
    from db.connection import NOT_MIGRATED_HELP

    monkeypatch.setattr(
        connection,
        "check_connection",
        lambda: (False, NOT_MIGRATED_HELP.format(name="neondb")),
    )

    app = AppTest.from_file("app.py", default_timeout=30).run()

    assert not app.exception
    assert any("python -m db.migrate" in element.value for element in app.code)


def test_search_offers_the_free_flat_and_holds_back_the_booked_one(stubbed_database):
    """Seaview 3 is booked across today; Harbour View 6 is not."""
    app = AppTest.from_file("pages/2_Search.py", default_timeout=30)
    app.run()
    app.date_input[1].set_value(TODAY + timedelta(days=3)).run()  # a three-night stay

    assert any("1 flat(s) available" in element.value for element in app.subheader)
    offered = "".join(element.value for element in app.markdown)
    assert "Harbour View 6" in offered
    # 3 nights at the stubbed 2400 rate.
    assert "R7 200.00" in offered
    assert any("not available" in element.label for element in app.expander)


def test_search_will_not_offer_a_stay_below_the_minimum(stubbed_database, monkeypatch):
    """Both flats take 2 nights minimum, so a single night is offered by neither."""
    monkeypatch.setattr(
        queries, "list_bookings",
        lambda start=None, end=None, unit_ids=None, statuses=None: [],
    )

    app = AppTest.from_file("pages/2_Search.py", default_timeout=30)
    app.run()
    app.date_input[1].set_value(TODAY + timedelta(days=1)).run()  # check-out

    assert any("0 flat(s) available" in element.value for element in app.subheader)
    assert any("too short" in element.label for element in app.expander)


def test_choosing_a_check_in_moves_the_check_out_to_the_night_after(stubbed_database):
    """So the two dates are never left in an impossible order."""
    app = AppTest.from_file("pages/2_Search.py", default_timeout=30)
    app.run()
    app.date_input[1].set_value(TODAY + timedelta(days=10)).run()
    assert app.date_input[1].value == TODAY + timedelta(days=10)

    moved_to = TODAY + timedelta(days=30)
    app.date_input[0].set_value(moved_to).run()

    assert app.date_input[0].value == moved_to
    assert app.date_input[1].value == moved_to + timedelta(days=1)


def test_the_search_results_do_not_name_the_owner(stubbed_database):
    """Not what you are choosing between with a guest on the phone."""
    app = AppTest.from_file("pages/2_Search.py", default_timeout=30)
    app.run()
    app.date_input[1].set_value(TODAY + timedelta(days=3)).run()

    shown = "".join(element.value for element in app.markdown)
    assert "Harbour View 6" in shown
    assert "S. Nkosi" not in shown
    assert "Petersen" not in shown


def test_search_says_which_flats_cannot_be_priced(stubbed_database, monkeypatch):
    """A flat with no rate on file is free but unquotable - and that is actionable."""
    monkeypatch.setattr(queries, "list_client_rates", lambda unit_id=None, year=None: [])
    monkeypatch.setattr(
        queries, "list_bookings",
        lambda start=None, end=None, unit_ids=None, statuses=None: [],
    )

    app = AppTest.from_file("pages/2_Search.py", default_timeout=30).run()

    assert any("cannot be priced" in element.label for element in app.expander)
    assert any("No " in element.value and "rate is set" in element.value for element in app.warning)


def test_quotes_page_flags_one_that_has_gone_quiet(stubbed_database):
    """The stubbed quote went out nine days ago and is still unanswered."""
    app = AppTest.from_file("pages/6_Quotes.py", default_timeout=30).run()

    assert any("waiting 7 days or more" in element.value for element in app.warning)
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Needing a follow-up"] == "1"


def test_quotes_page_shows_the_lines_as_they_were_sent(stubbed_database):
    app = AppTest.from_file("pages/6_Quotes.py", default_timeout=30).run()

    assert any("as it was quoted" in element.value for element in app.caption)
    assert any("R7 200.00" in metric.value for metric in app.metric)


def test_quotes_page_is_calm_when_there_are_none(stubbed_database, monkeypatch):
    monkeypatch.setattr(queries, "list_quotes", lambda statuses=None: [])

    app = AppTest.from_file("pages/6_Quotes.py", default_timeout=30).run()

    assert not app.exception
    assert any("No quotes yet" in element.value for element in app.info)


def test_accepting_a_quote_books_it(stubbed_database, monkeypatch):
    """One action: the flat is held on the calendar, not just marked accepted."""
    booked = []
    monkeypatch.setattr(
        queries, "accept_quote",
        lambda quote, notes="": booked.append((quote.id, notes)) or 99,
    )

    app = AppTest.from_file("pages/6_Quotes.py", default_timeout=30).run()
    button_labelled(app, "Accept and book it").click().run()

    assert booked == [(1, "From quote #1")]
    assert any("Booked as #99" in element.value for element in app.success)


def test_a_quote_whose_dates_have_gone_cannot_be_booked(stubbed_database, monkeypatch):
    """A quote holds nothing, so the flat may be sold from under it."""
    quote = QUOTES[0]
    monkeypatch.setattr(
        queries, "list_bookings",
        lambda start=None, end=None, unit_ids=None, statuses=None: [
            Booking(5, quote.unit_id, 1, quote.check_in, quote.check_out, CONFIRMED)
        ],
    )
    booked = []
    monkeypatch.setattr(
        queries, "accept_quote", lambda quote, notes="": booked.append(quote.id) or 99
    )

    app = AppTest.from_file("pages/6_Quotes.py", default_timeout=30).run()

    assert any("no longer free" in element.value for element in app.error)

    button_labelled(app, "Accept and book it").click().run()
    assert booked == [], "a quote whose dates are taken must not become a booking"


def test_an_accepted_quote_shows_the_booking_holding_the_dates(stubbed_database, monkeypatch):
    accepted = SavedQuote(
        1, 2, 1, TODAY, TODAY + timedelta(days=3), 4, Decimal("7200.00"),
        "accepted", TODAY - timedelta(days=9), QUOTE_LINES, "", 42,
    )
    monkeypatch.setattr(queries, "get_quote", lambda quote_id: accepted)
    monkeypatch.setattr(queries, "list_quotes", lambda statuses=None: [accepted])

    app = AppTest.from_file("pages/6_Quotes.py", default_timeout=30).run()

    assert any("holds Harbour View 6" in element.value for element in app.success)
    # Already booked, so there is nothing left to accept.
    assert not any(button.label == "Accept and book it" for button in app.button)


def test_cancelling_an_accepted_quote_also_cancels_its_booking(stubbed_database, monkeypatch):
    accepted = SavedQuote(
        1, 2, 1, TODAY, TODAY + timedelta(days=3), 4, Decimal("7200.00"),
        "accepted", TODAY, QUOTE_LINES, "", 42,
    )
    monkeypatch.setattr(queries, "get_quote", lambda quote_id: accepted)
    monkeypatch.setattr(queries, "list_quotes", lambda statuses=None: [accepted])
    cancelled = []
    monkeypatch.setattr(
        queries, "cancel_quote",
        lambda quote_id, booking_id=None: cancelled.append((quote_id, booking_id)),
    )

    app = AppTest.from_file("pages/6_Quotes.py", default_timeout=30).run()
    button_labelled(app, "Mark cancelled").click().run()

    assert cancelled == [(1, 42)], "the booking it made must be cancelled too"


def test_a_new_guest_needs_no_lookup_at_all(stubbed_database, monkeypatch):
    """The common case: type a name nobody matches, and that is the whole step."""
    monkeypatch.setattr(
        queries, "list_bookings",
        lambda start=None, end=None, unit_ids=None, statuses=None: [],
    )
    created, booked = [], []
    monkeypatch.setattr(
        queries, "create_client",
        lambda name, phone="", email="", notes="": created.append((name, phone)) or 77,
    )
    monkeypatch.setattr(
        queries, "create_booking", lambda *args, **kwargs: booked.append(args) or 5
    )

    app = AppTest.from_file("pages/5_Bookings.py", default_timeout=30)
    app.run()
    app.text_input(key="add_client_0_name").set_value("T. Willemse").run()
    app.text_input(key="add_client_0_phone").set_value("082 555 0999").run()

    # Nobody on file matches, so there is nothing to choose between.
    assert not [radio for radio in app.radio if radio.key == "add_client_0_match"]

    button_labelled(app, "Save booking").click().run()

    assert created == [("T. Willemse", "082 555 0999")]
    assert booked and booked[0][1] == 77


def test_a_repeat_guest_is_found_by_typing_and_is_not_duplicated(stubbed_database, monkeypatch):
    monkeypatch.setattr(
        queries, "list_bookings",
        lambda start=None, end=None, unit_ids=None, statuses=None: [],
    )
    created, booked = [], []
    monkeypatch.setattr(
        queries, "create_client",
        lambda name, phone="", email="", notes="": created.append(name) or 77,
    )
    monkeypatch.setattr(
        queries, "create_booking", lambda *args, **kwargs: booked.append(args) or 5
    )

    app = AppTest.from_file("pages/5_Bookings.py", default_timeout=30)
    app.run()
    app.text_input(key="add_client_0_name").set_value("Abrahams").run()

    offered = app.radio(key="add_client_0_match")
    assert offered.value == 0, "a new guest is the default even when one matches"

    offered.set_value(1).run()
    button_labelled(app, "Save booking").click().run()

    assert created == [], "picking the guest on file must not create a second copy"
    assert booked and booked[0][1] == 1


def test_editing_a_booking_keeps_its_guest_without_being_asked(stubbed_database, monkeypatch):
    """Changing dates must not quietly make a second copy of the same guest."""
    created, updated = [], []
    monkeypatch.setattr(
        queries, "create_client", lambda *args, **kwargs: created.append(args) or 77
    )
    monkeypatch.setattr(
        queries, "update_booking", lambda booking_id, **fields: updated.append(fields)
    )

    app = AppTest.from_file("pages/5_Bookings.py", default_timeout=30).run()
    button_labelled(app, "Save changes").click().run()

    assert created == []
    assert updated and updated[0]["client_id"] == 1


def test_every_page_carries_the_logo(stubbed_database):
    """The mark in the sidebar and the tab icon, on all of them."""
    from ui.brand import ICON, LOGO

    assert LOGO.exists() and ICON.exists()

    for path in PAGES:
        app = AppTest.from_file(path, default_timeout=30).run()
        assert not app.exception, (path, [str(e) for e in app.exception])


def test_the_quote_pdf_is_on_letterhead():
    """The one document a guest ever sees of the business."""
    from datetime import date as real_date

    from ui.pdf import quote_pdf

    pdf = quote_pdf(
        "Seaview 3", "M. Abrahams", real_date(2027, 1, 1), real_date(2027, 1, 4),
        QUOTE_LINES, Decimal("7200.00"), guests=2, reference=8,
        generated_on=real_date(2026, 8, 19),
    )

    assert pdf[:5] == b"%PDF-"
    # An image stream is in there, which a text-only letterhead would not have.
    assert b"/Image" in pdf
    # ...and it is the print-sized copy, not the full-resolution one.
    assert len(pdf) < 200_000


def test_the_rate_columns_are_headed(stubbed_database):
    """Two similar-looking numbers per row needed saying which is which."""
    app = AppTest.from_file("pages/3_Units.py", default_timeout=30).run()

    headings = "".join(element.value for element in app.markdown)
    assert "**Nightly rate**" in headings or "Nightly rate" in headings
    assert "Minimum nights" in headings


def test_turnover_is_offered_in_words_not_sentinel_numbers(stubbed_database):
    """-1 meaning 'no override' was shorthand leaking out of the database."""
    app = AppTest.from_file("pages/3_Units.py", default_timeout=30).run()

    # AppTest reports the options as the user sees them, already formatted.
    labels = [option for box in app.selectbox for option in box.options]

    assert any("Same day" in label for label in labels)
    assert any("Same as the rest of the year" in label for label in labels)
    assert "-1" not in "".join(labels)


def test_clearing_a_season_override_removes_it(stubbed_database, monkeypatch):
    """Otherwise the override would quietly keep applying after being cleared."""
    monkeypatch.setattr(
        queries, "list_turnover_rules", lambda unit_id=None: [TurnoverRule(1, "High", 1)]
    )
    removed, saved = [], []
    monkeypatch.setattr(
        queries, "delete_turnover_rule",
        lambda unit_id, season_label: removed.append((unit_id, season_label)),
    )
    monkeypatch.setattr(
        queries, "save_turnover_rule",
        lambda unit_id, season_label, buffer_nights: saved.append((season_label, buffer_nights)),
    )

    app = AppTest.from_file("pages/3_Units.py", default_timeout=30).run()
    high = next(box for box in app.selectbox if box.label == "High season")
    assert high.value == 1, "the override on file should be showing"

    # No run() in between: a form's fields are read when it is submitted, so
    # a change followed by its own rerun would simply be discarded.
    high.set_value("Same as the rest of the year")
    button_labelled(app, "Save turnover rules").click().run()

    assert (1, "High") in removed
    assert ("Low", None) not in saved


def test_switching_flat_shows_that_flats_rates(stubbed_database, monkeypatch):
    """A keyed widget keeps its value across reruns and ignores the new default,
    so a key shared by every flat would leave the previous flat's rates on
    screen - and save them against the wrong flat."""
    def rates_for(unit_id=None, year=None):
        amounts = {1: Decimal("2400.00"), 2: Decimal("5900.00")}
        if unit_id is None:
            return RATES
        return [
            ClientRate(unit_id, definition.label, YEAR, amounts[unit_id], None)
            for definition in SEASONS
        ]

    monkeypatch.setattr(queries, "list_client_rates", rates_for)

    app = AppTest.from_file("pages/3_Units.py", default_timeout=30).run()
    shown = {box.value for box in app.number_input if box.key and box.key.startswith("rate_")}
    assert 2400.0 in shown, shown

    app.selectbox(key="rate_unit").select("Harbour View 6").run()

    shown = {box.value for box in app.number_input if box.key and box.key.startswith("rate_")}
    assert 5900.0 in shown, shown
    assert 2400.0 not in shown, "the previous flat's rates must not follow it across"


def test_the_cleaning_calendar_marks_who_has_each_job(stubbed_database):
    app = AppTest.from_file("pages/7_Cleaning.py", default_timeout=30).run()

    grid = "".join(element.value for element in app.markdown)
    assert "rm-grid" in grid
    assert "Nomsa Dlamini" in grid          # in the cell's tooltip
    assert ">ND<" in grid                    # and as initials in the cell itself


def test_a_job_nobody_has_been_given_is_called_out(stubbed_database):
    """The deep clean in the fixture has no cleaner on it."""
    app = AppTest.from_file("pages/7_Cleaning.py", default_timeout=30).run()

    assert any("nobody assigned yet" in element.value for element in app.warning)


def test_working_out_the_cleans_schedules_what_the_rules_say(stubbed_database, monkeypatch):
    """A four-night stay ending today, on a flat that takes same-day guests."""
    monkeypatch.setattr(
        queries, "list_bookings",
        lambda start=None, end=None, unit_ids=None, statuses=None: [
            Booking(1, 1, 1, TODAY - timedelta(days=4), TODAY, CONFIRMED)
        ],
    )
    scheduled = []
    monkeypatch.setattr(
        queries, "schedule_jobs",
        lambda planned, costs: scheduled.extend(planned) or len(planned),
    )

    app = AppTest.from_file("pages/7_Cleaning.py", default_timeout=30).run()
    button_labelled(app, "Work out the cleans").click().run()

    labels = {job.service_label for job in scheduled}
    assert "post-clean" in labels, labels
    assert any("deep clean" in label for label in labels)
    # Every job says why it was scheduled, so a surprising one can be understood.
    assert all(job.reason for job in scheduled)


def test_the_cleaning_page_is_calm_before_anything_is_set_up(stubbed_database, monkeypatch):
    for name in ("list_cleaning_staff", "list_cleaning_jobs", "list_unit_cleaning_rates"):
        monkeypatch.setattr(queries, name, lambda *args, **kwargs: [])

    app = AppTest.from_file("pages/7_Cleaning.py", default_timeout=30).run()

    assert not app.exception
    assert any("No cleaners on file yet" in element.value for element in app.info)


def test_the_cleaning_grid_totals_each_day(stubbed_database, monkeypatch):
    """The question the calendar is really asked is whether a day is coverable."""
    monkeypatch.setattr(
        queries, "list_cleaning_jobs",
        lambda start=None, end=None, unit_ids=None, staff_id=None, statuses=None: [
            CleaningJob(1, 1, TODAY, "changeover clean", 1, None, "scheduled", Decimal("450")),
            CleaningJob(2, 2, TODAY, "post-clean", 1, None, "scheduled", Decimal("400")),
            CleaningJob(3, 1, TODAY + timedelta(days=1), "deep clean", None, None,
                        "scheduled", Decimal("900")),
        ],
    )

    app = AppTest.from_file("pages/7_Cleaning.py", default_timeout=30).run()

    grid = "".join(element.value for element in app.markdown)
    assert "Cleans that day" in grid
    assert f'title="2 clean(s) on {TODAY.strftime("%a %d %b")}"' in grid
    assert f'title="1 clean(s) on {(TODAY + timedelta(days=1)).strftime("%a %d %b")}"' in grid

    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Cleans this month"] == "3"
    assert metrics["Cleans on that day"] == "2"
    assert metrics["Busiest day"] == TODAY.strftime("%a %d %b")


def test_the_totals_follow_the_cleaner_being_shown(stubbed_database, monkeypatch):
    """Filtering to one person answers 'what is on my plate', not the whole team's."""
    monkeypatch.setattr(
        queries, "list_cleaning_jobs",
        lambda start=None, end=None, unit_ids=None, staff_id=None, statuses=None: [
            CleaningJob(1, 1, TODAY, "changeover clean", 1, None, "scheduled", Decimal("450")),
            CleaningJob(2, 2, TODAY, "post-clean", None, None, "scheduled", Decimal("400")),
        ],
    )

    app = AppTest.from_file("pages/7_Cleaning.py", default_timeout=30)
    app.run()
    assert {m.label: m.value for m in app.metric}["Cleans this month"] == "2"

    app.selectbox[0].select("Nomsa Dlamini").run()

    assert {m.label: m.value for m in app.metric}["Cleans this month"] == "1"


def test_moving_a_job_onto_a_day_that_is_taken_is_explained(stubbed_database, monkeypatch):
    """The flat only gets one clean a day, and the message should say so."""
    def refuse(job_id, **fields):
        raise queries.CleaningClash(
            "That flat is already being cleaned that day, and it only gets one clean a day."
        )

    monkeypatch.setattr(queries, "update_cleaning_job", refuse)

    app = AppTest.from_file("pages/7_Cleaning.py", default_timeout=30).run()
    button_labelled(app, "Save job").click().run()

    assert any("only gets one clean a day" in element.value for element in app.error)
    assert not app.exception
