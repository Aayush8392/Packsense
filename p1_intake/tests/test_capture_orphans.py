"""Orphan detection in the capture: a landed delta file that no manifest records.

The names below are real OFF delta file names (the 13-day window the project captured), not invented ones.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capture_deltas import find_orphans, split_orphans  # noqa: E402

A = "openfoodfacts_products_1791094877_1791181482.json.gz"
B = "openfoodfacts_products_1791613749_1791700013.json.gz"
C = "openfoodfacts_products_1791700013_1791786521.json.gz"
D = "openfoodfacts_products_1791786521_1791872470.json.gz"
E = "openfoodfacts_products_1791872470_1791958972.json.gz"


def test_no_orphans_when_every_landed_file_is_recorded():
    assert find_orphans({A, B, C}, {A, B, C}) == []


def test_a_landed_file_missing_from_the_manifests_is_an_orphan():
    assert find_orphans({A, B, E}, {A, B}) == [E]


def test_orphans_come_back_in_time_order():
    assert find_orphans({E, A, C}, set()) == [A, C, E]


def test_a_recorded_file_that_is_not_in_landing_is_not_an_orphan():
    assert find_orphans({A}, {A, B}) == []


def test_files_that_are_not_delta_files_are_ignored():
    assert find_orphans({A, "notes.txt", "openfoodfacts_products_1_2.json"}, {A}) == []


def test_orphans_still_listed_by_off_are_captured_again():
    refetch, from_landing = split_orphans([D, E], [C, D, E])
    assert refetch == [D, E] and from_landing == []


def test_orphans_off_no_longer_lists_are_recorded_from_landing():
    refetch, from_landing = split_orphans([A, E], [C, D, E])
    assert refetch == [E] and from_landing == [A]


def test_no_orphans_means_nothing_to_split():
    assert split_orphans([], [A, B]) == ([], [])
