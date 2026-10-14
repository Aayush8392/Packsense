"""Taxonomy snapshot naming and change detection in the capture.

The taxonomy names, Last-Modified value and shas below are real (OFF's data_quality taxonomy as published on 2026-10-09).
"""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capture_taxonomies import TAXONOMIES, last_known, snapshot_key  # noqa: E402

MODIFIED = "Fri, 09 Oct 2026 14:01:54 GMT"
NOW = dt.datetime(2026, 10, 14, 12, 0, 0, tzinfo=dt.timezone.utc)
SHA_OLD = "6ac8f3d2" + "0" * 56
SHA_NEW = "1322ac00" + "f" * 56


def test_the_list_holds_34_unique_names():
    assert len(TAXONOMIES) == 34 and len(set(TAXONOMIES)) == 34


def test_the_core_taxonomies_are_included():
    assert {"data_quality", "categories", "allergens", "countries", "nutrients"} <= set(TAXONOMIES)


def test_snapshot_key_uses_the_off_last_modified_time():
    assert snapshot_key("data_quality", MODIFIED, SHA_OLD, NOW) == "data_quality/20261009T140154Z_6ac8f3d20000.json.gz"


def test_snapshot_key_falls_back_to_the_capture_time_without_last_modified():
    assert snapshot_key("allergens", None, SHA_OLD, NOW) == "allergens/20261014T120000Z_6ac8f3d20000.json.gz"


def test_a_changed_content_gets_a_different_key():
    assert snapshot_key("data_quality", MODIFIED, SHA_OLD, NOW) != snapshot_key("data_quality", MODIFIED, SHA_NEW, NOW)


def _entry(name, sha, snapshot):
    return {"name": name, "sha256": sha, "snapshot": snapshot}


def test_last_known_is_empty_without_logs():
    assert last_known([]) == {}


def test_last_known_takes_the_newest_entry_per_taxonomy():
    day1 = {"entries": [_entry("data_quality", SHA_OLD, "data_quality/a.json.gz"), _entry("allergens", SHA_OLD, "allergens/a.json.gz")]}
    day2 = {"entries": [_entry("data_quality", SHA_NEW, "data_quality/b.json.gz")]}
    known = last_known([day1, day2])
    assert known["data_quality"] == {"sha256": SHA_NEW, "snapshot": "data_quality/b.json.gz"}
    assert known["allergens"] == {"sha256": SHA_OLD, "snapshot": "allergens/a.json.gz"}


def test_a_log_with_no_entries_changes_nothing():
    assert last_known([{"entries": []}, {}]) == {}
