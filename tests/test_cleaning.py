"""Tests for which cleans get scheduled, and when (spec 3.9, 3.10)."""

from datetime import date
from decimal import Decimal

from lib.cleaning import (
    CHANGEOVER_CLEAN,
    DEEP_CLEAN,
    LIGHT_CLEAN,
    POST_CLEAN,
    PRE_CLEAN,
    cost_for,
    deep_clean_dates,
    light_clean_dates,
    plan_for_unit,
)
from lib.models import CANCELLED, CONFIRMED, Booking, SeasonDefinition, TurnoverRule

UNIT = 1
JANUARY = date(2027, 1, 1)
FEBRUARY = date(2027, 2, 1)

SEASONS = [
    SeasonDefinition(1, "High", date(2027, 1, 1), date(2027, 1, 15), 2027),
    SeasonDefinition(2, "Low", date(2027, 1, 16), date(2027, 1, 31), 2027),
]


def stay(check_in, check_out, id=1, status=CONFIRMED, unit_id=UNIT):
    return Booking(id, unit_id, 1, date(*check_in), date(*check_out), status)


def plan(bookings, rules=(), deep=None, **kwargs):
    return plan_for_unit(
        UNIT, JANUARY, FEBRUARY, bookings, rules, SEASONS, deep_every_days=deep, **kwargs
    )


def labels_on(jobs, day):
    return sorted(job.service_label for job in jobs if job.date == date(*day))


def test_a_same_day_turnover_is_one_changeover_clean():
    """The normal arrangement: out in the morning, cleaned, in that afternoon."""
    jobs = plan([stay((2027, 1, 4), (2027, 1, 8), id=1), stay((2027, 1, 8), (2027, 1, 12), id=2)])

    assert labels_on(jobs, (2027, 1, 8)) == [CHANGEOVER_CLEAN]
    # One visit, not a post-clean and a pre-clean stacked on the same day.
    assert POST_CLEAN not in [job.service_label for job in jobs if job.date == date(2027, 1, 8)]


def test_a_buffer_day_is_a_post_clean_rather_than_a_changeover():
    """One clear night between guests, so it is not a same-day turnaround."""
    rules = [TurnoverRule(UNIT, None, 1)]
    jobs = plan(
        [stay((2027, 1, 4), (2027, 1, 8), id=1), stay((2027, 1, 9), (2027, 1, 12), id=2)],
        rules=rules,
    )

    assert labels_on(jobs, (2027, 1, 8)) == [POST_CLEAN]


def test_one_clear_night_does_not_mean_two_cleaners_on_one_day():
    """With a single buffer night the post-clean and pre-clean collide, and
    sending somebody twice would charge the owner twice for one visit."""
    rules = [TurnoverRule(UNIT, None, 1)]
    jobs = plan(
        [stay((2027, 1, 4), (2027, 1, 8), id=1), stay((2027, 1, 9), (2027, 1, 12), id=2)],
        rules=rules,
    )

    assert labels_on(jobs, (2027, 1, 8)) == [POST_CLEAN]
    assert len([job for job in jobs if job.date == date(2027, 1, 8)]) == 1


def test_a_longer_gap_does_get_both_a_post_clean_and_a_pre_clean():
    """Two clear nights, so there is room for the clean and the final check."""
    rules = [TurnoverRule(UNIT, None, 2)]
    jobs = plan(
        [stay((2027, 1, 4), (2027, 1, 8), id=1), stay((2027, 1, 11), (2027, 1, 14), id=2)],
        rules=rules,
    )

    assert labels_on(jobs, (2027, 1, 8)) == [POST_CLEAN]
    assert labels_on(jobs, (2027, 1, 10)) == [PRE_CLEAN]


def test_a_checkout_with_nobody_following_still_gets_a_post_clean():
    jobs = plan([stay((2027, 1, 4), (2027, 1, 8))])

    assert labels_on(jobs, (2027, 1, 8)) == [POST_CLEAN]


def test_an_arrival_after_a_gap_gets_a_pre_clean_the_day_before():
    jobs = plan([stay((2027, 1, 20), (2027, 1, 24))])

    assert labels_on(jobs, (2027, 1, 19)) == [PRE_CLEAN]


def test_a_long_stay_gets_tidied_partway_through():
    jobs = plan([stay((2027, 1, 2), (2027, 1, 26))])

    tidies = sorted(job.date for job in jobs if job.service_label == LIGHT_CLEAN)
    assert tidies == [date(2027, 1, 9), date(2027, 1, 16), date(2027, 1, 23)]


def test_a_short_stay_is_not_tidied_partway_through():
    jobs = plan([stay((2027, 1, 2), (2027, 1, 9))])

    assert not [job for job in jobs if job.service_label == LIGHT_CLEAN]


def test_cancelled_stays_are_not_cleaned():
    jobs = plan([stay((2027, 1, 4), (2027, 1, 8), status=CANCELLED)])

    assert jobs == []


def test_another_flats_stays_are_not_cleaned_here():
    jobs = plan([stay((2027, 1, 4), (2027, 1, 8), unit_id=99)])

    assert jobs == []


def test_the_buffer_rule_that_drives_booking_also_drives_cleaning():
    """One flat, one policy: high season needs a clear day, low season does not."""
    rules = [TurnoverRule(UNIT, None, 0), TurnoverRule(UNIT, "High", 1)]
    in_high = plan([stay((2027, 1, 4), (2027, 1, 8), id=1), stay((2027, 1, 9), (2027, 1, 12), id=2)],
                   rules=rules)
    in_low = plan([stay((2027, 1, 20), (2027, 1, 24), id=3), stay((2027, 1, 24), (2027, 1, 28), id=4)],
                  rules=rules)

    assert labels_on(in_high, (2027, 1, 8)) == [POST_CLEAN]
    assert labels_on(in_low, (2027, 1, 24)) == [CHANGEOVER_CLEAN]


def test_deep_cleans_happen_whether_or_not_anyone_is_staying():
    jobs = plan([], deep=14)

    deep = [job.date for job in jobs if job.service_label == DEEP_CLEAN]
    assert deep == [date(2027, 1, 1), date(2027, 1, 15), date(2027, 1, 29)]
    assert all(job.booking_id is None for job in jobs if job.service_label == DEEP_CLEAN)


def test_a_deep_clean_is_counted_from_the_last_one_actually_done():
    """A flat cleaned late should not fall due again the next morning."""
    dates = deep_clean_dates(date(2027, 1, 1), date(2027, 4, 1), 30, last_done=date(2026, 12, 20))

    assert dates == [date(2027, 1, 19), date(2027, 2, 18), date(2027, 3, 20)]


def test_every_job_says_why_it_exists():
    jobs = plan([stay((2027, 1, 4), (2027, 1, 20))], deep=None)

    assert all(job.reason for job in jobs)
    assert any("Mid-stay" in job.reason for job in jobs)


def test_jobs_outside_the_window_are_left_out():
    jobs = plan([stay((2026, 12, 20), (2026, 12, 28))])

    assert jobs == []


def test_a_negotiated_price_for_one_flat_beats_the_standard_rate():
    standard = {CHANGEOVER_CLEAN: Decimal("450.00"), DEEP_CLEAN: Decimal("900.00")}
    overrides = {(7, CHANGEOVER_CLEAN): Decimal("620.00")}

    assert cost_for(7, CHANGEOVER_CLEAN, standard, overrides) == Decimal("620.00")
    assert cost_for(7, DEEP_CLEAN, standard, overrides) == Decimal("900.00")
    assert cost_for(1, CHANGEOVER_CLEAN, standard, overrides) == Decimal("450.00")
    assert cost_for(1, "unpriced service", standard, overrides) == Decimal("0.00")


def test_splitting_a_migration_file_respects_quotes_and_comments():
    """The HTTPS endpoint takes one statement at a time, so files get cut up -
    and a semicolon inside a string or a comment ends nothing."""
    from db.http_sql import split_statements

    sql = """
    -- a comment; with a semicolon in it
    CREATE TABLE t (label TEXT CHECK (label IN ('a;b', 'c')));
    /* block ; comment */
    INSERT INTO t VALUES ('x;y');
    """

    statements = split_statements(sql)

    assert len(statements) == 2
    assert statements[0].strip().startswith("-- a comment")
    assert "'a;b'" in statements[0]
    assert statements[1].strip().endswith("INSERT INTO t VALUES ('x;y')")


def test_splitting_drops_chunks_that_are_only_comments():
    from db.http_sql import split_statements

    assert split_statements("-- nothing here\n\n") == []
    assert len(split_statements("SELECT 1; -- trailing note\n")) == 1
