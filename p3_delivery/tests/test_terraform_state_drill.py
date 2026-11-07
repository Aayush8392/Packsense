"""The decisions inside the Terraform state drill: reading a plan, judging the two recoveries, picking the earlier state version."""
import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bootstrap"))

import terraform_state_drill as t  # noqa: E402


def test_summary_with_imports_is_read():
    got = t.parse_plan("blah\nPlan: 3 to import, 0 to add, 0 to change, 0 to destroy.\nmore")
    assert got == {"import": 3, "add": 0, "change": 0, "destroy": 0, "no_changes": False}


def test_summary_without_the_import_part_is_read():
    assert t.parse_plan("Plan: 2 to add, 1 to change, 1 to destroy.") == {"import": 0, "add": 2, "change": 1, "destroy": 1, "no_changes": False}


def test_no_changes_is_read():
    assert t.parse_plan("No changes. Your infrastructure matches the configuration.") == {"import": 0, "add": 0, "change": 0, "destroy": 0, "no_changes": True}


def test_text_without_a_plan_is_refused():
    with pytest.raises(ValueError, match="no plan summary"):
        t.parse_plan("Error: Failed to load state")


def test_lost_state_passes_when_every_object_is_imported_and_nothing_else_happens():
    ok, why = t.judge_empty_state({"import": 3, "add": 0, "change": 0, "destroy": 0, "no_changes": False})
    assert ok, why


@pytest.mark.parametrize("summary", [
    {"import": 3, "add": 1, "change": 0, "destroy": 0},       # it would create something that already exists
    {"import": 3, "add": 0, "change": 1, "destroy": 0},
    {"import": 2, "add": 0, "change": 0, "destroy": 0},       # one object is not adopted
    {"import": 0, "add": 3, "change": 0, "destroy": 0},       # no import blocks: it would recreate everything
])
def test_lost_state_fails_on_any_other_plan(summary):
    ok, why = t.judge_empty_state({**summary, "no_changes": False})
    assert not ok and why


def test_restored_state_passes_with_no_changes():
    ok, _ = t.judge_restored_state({"import": 0, "add": 0, "change": 0, "destroy": 0, "no_changes": True})
    assert ok


def test_restored_state_may_still_import_but_must_not_add_change_or_destroy():
    assert t.judge_restored_state({"import": 1, "add": 0, "change": 0, "destroy": 0, "no_changes": False})[0]
    for bad in ({"add": 1}, {"change": 1}, {"destroy": 1}):
        ok, why = t.judge_restored_state({"import": 0, "add": 0, "change": 0, "destroy": 0, "no_changes": False, **bad})
        assert not ok and why


def v(vid, hour, latest=False):
    return {"VersionId": vid, "LastModified": dt.datetime(2026, 11, 1, hour, tzinfo=dt.timezone.utc), "IsLatest": latest}


def test_the_previous_version_is_the_newest_one_that_is_not_the_latest():
    versions = [v("c", 12, latest=True), v("a", 8), v("b", 10)]
    assert t.pick_previous_version(versions)["VersionId"] == "b"


def test_there_must_be_an_earlier_version():
    with pytest.raises(ValueError, match="no earlier version"):
        t.pick_previous_version([v("only", 8, latest=True)])


def test_the_scratch_key_can_never_be_the_production_key():
    assert t.scratch_key_ok("packsense/drill.tfstate", "packsense/github.tfstate")
    assert not t.scratch_key_ok("packsense/github.tfstate", "packsense/github.tfstate")
    assert not t.scratch_key_ok("packsense/terraform.tfstate", "packsense/github.tfstate")
    assert not t.scratch_key_ok("other/drill.tfstate", "packsense/github.tfstate")
