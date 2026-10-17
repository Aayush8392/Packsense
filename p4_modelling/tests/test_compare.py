"""The engine comparison itself: canonical values, hashing and the difference report."""
import datetime as dt
import decimal
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gold_lib import compare  # noqa: E402


def test_integers_of_any_width_are_the_same_value():
    assert compare.norm(5) == compare.norm(decimal.Decimal("5")) == 5
    assert compare.norm(decimal.Decimal("2.5")) == 2.5


def test_timestamps_become_whole_second_utc_text():
    naive = dt.datetime(2026, 10, 14, 12, 30, 5, 999)
    aware = dt.datetime(2026, 10, 14, 14, 30, 5, tzinfo=dt.timezone(dt.timedelta(hours=2)))
    assert compare.norm(naive) == compare.norm(aware) == "2026-10-14 12:30:05"
    assert compare.from_databricks("2026-10-14T12:30:05.000Z", "TIMESTAMP") == "2026-10-14 12:30:05"
    assert compare.from_databricks("2026-10-14 12:30:05", "TIMESTAMP") == "2026-10-14 12:30:05"


def test_databricks_cells_are_read_by_their_declared_type():
    assert compare.from_databricks("42", "LONG") == 42
    assert compare.from_databricks("2082.7586206896553", "DOUBLE") == 2082.7586206896553
    assert compare.from_databricks("true", "BOOLEAN") is True
    assert compare.from_databricks(None, "STRING") is None
    assert compare.from_databricks('["en:india","en:france"]', "ARRAY") == ["en:india", "en:france"]
    assert compare.from_databricks("2026-10-14", "DATE") == "2026-10-14"
    assert compare.from_databricks("true", "STRING") == "true"          # a string that looks like a boolean stays text


def test_map_key_order_does_not_matter_but_array_order_does():
    a = {"row": 1, "nutrients": {"fat": 1.0, "salt": 2.0}, "tags": ["a", "b"]}
    b = {"row": 1, "nutrients": {"salt": 2.0, "fat": 1.0}, "tags": ["a", "b"]}
    c = {"row": 1, "nutrients": {"fat": 1.0, "salt": 2.0}, "tags": ["b", "a"]}
    assert compare.row_hash(a) == compare.row_hash(b)
    assert compare.row_hash(a) != compare.row_hash(c)


def test_null_is_not_the_empty_string_or_empty_array():
    assert len({compare.row_hash({"x": None}), compare.row_hash({"x": ""}), compare.row_hash({"x": []})}) == 3


def test_a_duplicate_key_is_refused():
    with pytest.raises(ValueError):
        compare.summarise("dim_market", ["market_code"], [{"market_code": "en:india"}, {"market_code": "en:india"}])


def summary(rows):
    return {m: compare.summarise(m, list(rows[m][0]), rows[m]) if rows[m] else {"columns": [], "rows": 0, "hashes": {}} for m in compare.MODELS}


def everything(extra=None):
    rows = {m: [] for m in compare.MODELS}
    rows["dim_market"] = [{"market_code": "en:india", "is_target_market": 1}, {"market_code": "en:france", "is_target_market": 0}]
    if extra:
        rows["dim_market"] = extra
    return summary(rows)


def test_identical_summaries_have_no_differences():
    assert compare.diff(everything(), everything()) == []


def test_a_changed_value_a_missing_row_and_a_new_column_are_all_reported():
    golden = everything()
    changed = everything([{"market_code": "en:india", "is_target_market": 0}, {"market_code": "en:france", "is_target_market": 0}])
    assert any("1 rows differ" in p for p in compare.diff(golden, changed))
    fewer = everything([{"market_code": "en:india", "is_target_market": 1}])
    out = compare.diff(golden, fewer)
    assert any("row count 2" in p for p in out) and any("only in golden" in p for p in out)
    wider = everything([{"market_code": "en:india", "is_target_market": 1, "extra": 1}, {"market_code": "en:france", "is_target_market": 0, "extra": 1}])
    assert any("columns differ" in p for p in compare.diff(golden, wider))


def test_column_diff_names_the_differing_columns():
    assert compare.column_diff({"a": 1, "b": 2.0}, {"a": 1, "b": 3.0}) == ["b"]
