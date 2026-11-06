import copy
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import compute_tripwire_lib as ct  # noqa: E402

FIX = json.loads((Path(__file__).parent / "fixtures" / "compute_usage_hourly.json").read_text(encoding="utf-8"))["hours"]    # real hourly billing, measured 2026-11-06


def test_the_series_has_no_gaps_and_ignores_non_compute():
    s = ct.hourly_compute(FIX)
    assert all(b[0] - a[0] == dt.timedelta(hours=1) for a, b in zip(s, s[1:]))
    row = FIX["2026-10-23 00"]
    assert row["other"] > 0 and row["jobs"] == 0 and row["sql"] == 0
    assert dict(s)[dt.datetime(2026, 10, 23, 0)] == 0.0          # network usage in that hour is not compute


def test_the_peak_is_the_recorded_lock_mark_and_the_highest_unlocked_value_is_in_the_data():
    r = ct.evaluate(FIX)
    assert r["peak_dbu"] == 68.2 and r["peak_ending"] == "2026-10-28 06"        # the buildlog's lock mark, measured by an earlier query
    by_end = dict(ct.rolling_totals(ct.hourly_compute(FIX)))
    assert abs(by_end[dt.datetime(2026, 11, 3, 20)] - 64.3) < 0.06             # the highest value without a lock (session 40)


def test_the_latest_day_is_quiet_and_passes():
    r = ct.evaluate(FIX)
    assert r["ok"] and r["latest_dbu"] < 20 and r["latest_ending"] == "2026-11-06 11"


def test_the_line_catches_the_unlocked_peak_but_not_a_production_day():
    by_end = dict(ct.rolling_totals(ct.hourly_compute(FIX)))
    assert by_end[dt.datetime(2026, 11, 3, 20)] > ct.WARN_DBU                   # the heavy backfill day would have warned
    assert by_end[dt.datetime(2026, 11, 1, 23)] < ct.WARN_DBU                   # a quiet Sunday would not
    assert ct.evaluate(FIX)["over_line_hours"] > 0


def test_one_field_variant_turns_the_latest_value_red():
    bumped = copy.deepcopy(FIX)
    bumped["2026-11-06 11"]["jobs"] += 45.0
    r = ct.evaluate(bumped)
    assert not r["ok"] and r["latest_dbu"] > ct.WARN_DBU


def test_less_than_a_day_of_data_is_not_ok_and_says_why():
    short = {k: FIX[k] for k in sorted(FIX)[:5]}
    r = ct.evaluate(short)
    assert not r["ok"] and "24 hours" in r["reason"]
    assert ct.evaluate({})["ok"] is False
