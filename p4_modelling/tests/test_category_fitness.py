"""mart_category_fitness against a pure-Python count on the REAL fixture build, per scope and category.

The SQL tests in data_tests/ check the product, nutrient, ingredients and quantity totals; the date windows (changed in the last 28 days, last edit over
365 days ago) are recomputed here in Python from the fixture's own rows, so a slip in the shifted-seconds arithmetic of the model shows up. The test needs
the fixture build (target/fixture.duckdb, written by `dbt build --target duckdb`); without it the test is skipped (the CI job `engines` builds it first).
"""
import datetime as dt
from collections import Counter
from pathlib import Path

import duckdb
import pytest

P4 = Path(__file__).resolve().parents[1]
DB = P4 / "target" / "fixture.duckdb"
pytestmark = pytest.mark.skipif(not DB.exists(), reason="the DuckDB fixture build is not available")

DAY = 86400


def day(t: int) -> int:
    return t // DAY


def test_window_counts_match_python():
    c = duckdb.connect(str(DB), read_only=True)
    try:
        windows = c.execute("select min(delta_start_t), max(delta_end_t) from stg_silver_versions where not is_seed").fetchone()
        history = c.execute(
            "select code, valid_from_t, valid_to_t, opened_by_seed, last_version_t, coalesce(list_extract(categories_tags, 1), '(no category)') "
            "from product_history").fetchall()
        india = {r[0] for r in c.execute(
            "select distinct m.code from bridge_product_market m join dim_market d on d.market_code = m.market_code where d.is_target_market = 1").fetchall()}
        got = {(r[0], r[1]): r[2:] for r in c.execute(
            "select scope, category, n_changed_28d, n_stale_365d, as_of_date from mart_category_fitness").fetchall()}
    finally:
        c.close()

    first_t, last_t = windows
    last_day = (last_t // DAY) - 1                      # the day before the last midnight at or before the newest window end
    as_of = dt.date(1970, 1, 1) + dt.timedelta(days=last_day)

    alive = {}
    for code, from_t, to_t, _seed, last_version_t, category in history:
        if day(from_t) <= last_day and (to_t is None or day(to_t) > last_day):
            alive[code] = (category, last_version_t)
    changed = {code for code, from_t, _to, seed, _lv, _cat in history
               if not seed and day(from_t) <= last_day and last_day - day(from_t) < 28}

    want_changed, want_stale = Counter(), Counter()
    for code, (category, last_version_t) in alive.items():
        for scope in ("all",) + (("india",) if code in india else ()):
            want_changed[(scope, category)] += code in changed
            want_stale[(scope, category)] += last_day - day(last_version_t) > 365
            want_changed[(scope, category)] += 0
    assert set(got) == set(want_changed) and got
    for key, (n_changed, n_stale, as_of_date) in got.items():
        assert as_of_date == as_of, key
        assert n_changed == want_changed[key], ("changed", key)
        assert n_stale == want_stale[key], ("stale", key)
