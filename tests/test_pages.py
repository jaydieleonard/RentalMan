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
    CONFIRMED,
    QUOTE_OPEN,
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
                 "list_quotes"):
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
    app.selectbox(key="add_client_0").select("M. Abrahams").run()
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
    app.selectbox(key="add_client_0").select("M. Abrahams").run()
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

    app.selectbox(key="add_client_0").select("M. Abrahams").run()
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
    app = AppTest.from_file("pages/2_Search.py", default_timeout=30).run()

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
