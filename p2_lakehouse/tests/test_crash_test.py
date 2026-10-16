"""The pure decisions inside the kill-test driver: which files, when to kill, where a killed run stopped."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bootstrap"))

import crash_test as c  # noqa: E402

# real delta file names from the landing volume (sizes made up only to order them)
SIZES = {"openfoodfacts_products_delta_20261001.json.gz": 30, "openfoodfacts_products_delta_20261002.json.gz": 20,
         "openfoodfacts_products_delta_20261003.json.gz": 25, "openfoodfacts_products_delta_20261004.json.gz": 35,
         "openfoodfacts_products_delta_20261005.json.gz": 22, "manifests": 1}


def test_pick_files_takes_the_middle_by_size_and_ignores_non_deltas():
    got = c.pick_files(SIZES, 3)
    assert got == sorted(["openfoodfacts_products_delta_20261005.json.gz", "openfoodfacts_products_delta_20261003.json.gz",
                          "openfoodfacts_products_delta_20261001.json.gz"])


def test_pick_files_always_includes_the_required_files_and_fills_around_them():
    must = "openfoodfacts_products_delta_20261004.json.gz"      # the biggest: the plain middle pick would not choose it
    got = c.pick_files(SIZES, 3, [must])
    assert must in got and len(got) == 3 and got == sorted(got)
    assert c.pick_files(SIZES, 3, ["not_a_landed_file.json.gz"]) == c.pick_files(SIZES, 3)      # a file that is not in landing is ignored
    assert c.pick_files(SIZES, 3, []) == c.pick_files(SIZES, 3)
    with pytest.raises(ValueError):
        c.pick_files(SIZES, 2, [k for k in SIZES if k.endswith(".json.gz")][:3])


def test_pick_files_needs_enough_files():
    with pytest.raises(ValueError):
        c.pick_files({"a.json.gz": 1})


def test_kill_rules():
    assert not c.should_kill("first_write", 0, 0, 3)
    assert c.should_kill("first_write", 1, 0, 3)
    assert not c.should_kill("first_write", 3, 3, 3)       # everything recorded: nothing left to kill
    assert not c.should_kill("later_file", 5, 0, 3)
    assert c.should_kill("later_file", 5, 1, 3)
    assert not c.should_kill("midway", 5, 2, 6)
    assert c.should_kill("midway", 5, 3, 6)
    assert not c.should_kill("midway", 5, 6, 6)
    with pytest.raises(ValueError):
        c.should_kill("nope", 0, 0, 3)


def test_bronze_window_names_the_risky_state():
    assert c.bronze_window(0, 0, 0, 3).startswith("before")
    assert "risky" in c.bronze_window(7000, 0, 0, 3)             # rows merged, no manifest row
    assert "risky" in c.bronze_window(14000, 7000, 1, 3)
    assert c.bronze_window(7000, 7000, 1, 3) == "between files"
    assert c.bronze_window(21000, 21000, 3, 3).startswith("after the last")


def test_silver_window_names_the_risky_state():
    assert c.silver_window(set(), set(), 3).startswith("before")
    assert "risky" in c.silver_window({"a"}, set(), 3)
    assert "risky" in c.silver_window({"a", "b"}, {"a"}, 3)
    assert c.silver_window({"a"}, {"a"}, 3) == "between files"
    assert c.silver_window({"a", "b", "c"}, {"a", "b", "c"}, 3).startswith("after the last")


def test_inlist_strips_quotes():
    assert c.inlist(["a'b", "c"]) == "'ab','c'"
