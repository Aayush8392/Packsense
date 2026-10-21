"""p7_triage_ml/replay_lib.py: both sides of every boundary (run on sqlite3, the SQL is plain), the leakage guard, and agreement with the dbt macros."""
import datetime as dt
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p7_triage_ml"))
import replay_lib as rp  # noqa: E402

D = dt.date(2026, 10, 5)
T = rp.end_of_day_t(D)  # 2026-10-05 23:59:59 UTC
START = T - 86399  # 2026-10-05 00:00:00


def db(periods, spans):
    c = sqlite3.connect(":memory:")
    c.execute("create table h (code text, valid_from_t integer, valid_to_t integer)")
    c.execute("create table s (code text, severity text, flag text, first_seen_t integer, vanished_at_t integer)")
    c.executemany("insert into h values (?,?,?)", periods)
    c.executemany("insert into s values (?,?,?,?,?)", spans)
    return c


def held(c):
    return sorted(r[0] for r in c.execute(rp.state_as_of_sql(T, "h").replace("select *", "select code")))


def test_end_of_day_is_the_last_second_of_the_utc_day():
    assert rp.end_of_day_t("1970-01-01") == 86399
    assert dt.datetime.fromtimestamp(T, dt.timezone.utc) == dt.datetime(2026, 10, 5, 23, 59, 59, tzinfo=dt.timezone.utc)


@pytest.mark.parametrize("valid_from,valid_to,expected", [
    (T, None, True),                 # opened in the very last second of the day
    (T + 1, None, False),            # opened at midnight after: the future
    (START, T + 1, True),            # still open, the next period starts at the next midnight
    (START - 100, T, False),         # closed in the last second of the day: not open at T
    (START - 100, T - 1, False),
    (START - 100, T + 1, True),
    (START - 100, None, True),
])
def test_a_period_is_open_exactly_when_it_started_by_T_and_ends_after_T(valid_from, valid_to, expected):
    c = db([("p", valid_from, valid_to)], [])
    assert (held(c) == ["p"]) is expected


@pytest.mark.parametrize("first_seen,vanished,expected", [
    (T, None, True),
    (T + 1, None, False),
    (START - 5, T, False),
    (START - 5, T + 1, True),
    (START - 5, None, True),
])
def test_a_flag_is_open_exactly_when_first_seen_by_T_and_not_vanished_by_T(first_seen, vanished, expected):
    c = db([], [("p", "error", "en:x", first_seen, vanished)])
    assert (len(c.execute(rp.open_flags_as_of_sql(T, "s")).fetchall()) == 1) is expected


def test_a_product_with_no_version_by_T_is_absent_and_a_later_period_never_leaks():
    c = db([("early", START - 9, START - 1), ("early", START - 1, None), ("late", T + 5, None)], [])
    assert held(c) == ["early"]  # one open period per product, and 'late' is invisible


def test_counts_split_by_severity_and_count_each_product_once():
    c = db([("a", 0, None), ("b", 0, None)], [("a", "error", "f1", 1, None), ("a", "error", "f2", 1, None), ("b", "warning", "f3", 1, T), ("b", "info", "f4", 1, T + 1)])
    row = c.execute(rp.counts_as_of_sql(T, "h", "s")).fetchone()
    assert row == (2, 2, 0, 1, 0)


def test_leakage_guard_accepts_the_past_and_refuses_the_future():
    rp.assert_no_future([{"valid_from_t": T}, {"first_seen_t": 5}, {"valid_from_t": None}], T)
    with pytest.raises(AssertionError):
        rp.assert_no_future([{"valid_from_t": T + 1}], T)


def test_names_and_times_are_checked_before_they_reach_the_sql():
    with pytest.raises(ValueError):
        rp.state_as_of_sql(T, "h; drop table h")
    with pytest.raises(TypeError):
        rp.history_open("1 or 1=1")


def test_the_dbt_macros_use_the_same_rule():
    text = (ROOT / "p4_modelling" / "macros" / "replay.sql").read_text(encoding="utf-8")
    assert "valid_from_t') }} <= {{ d }}" in text and "valid_to_t is null" in text and "valid_to_t') }} > {{ d }}" in text
    assert "first_seen_t') }} <= {{ d }}" in text and "vanished_at_t is null" in text and "vanished_at_t') }} > {{ d }}" in text


@pytest.mark.parametrize("stamp", [START - 1, START, T - 1, T, T + 1])
def test_the_day_form_of_the_macros_equals_the_seconds_form(stamp):
    # the macros compare epoch_date(x) with the day d; the library compares x with T: the same decision for every stamp
    day = lambda x: x // 86400  # noqa: E731  (epoch_date: floor of x / 86400)
    d = day(T)
    assert (day(stamp) <= d) == (stamp <= T)
    assert (day(stamp) > d) == (stamp > T)
