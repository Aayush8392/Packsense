"""The pure decisions inside the archive kill drill: which files, when to cancel, where the kill landed, and whether the state is sound."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bootstrap"))

import archive_kill_drill as d  # noqa: E402

KEYS = [f"raw/deltas/openfoodfacts_products_{1790000000 + i * 86400}_{1790000000 + (i + 1) * 86400}.json.gz" for i in range(6)]
SHA = {k: f"{i:064x}" for i, k in enumerate(KEYS)}


def test_pick_takes_the_smallest_delta_files_and_returns_their_b2_keys():
    sizes = {"openfoodfacts_products_1790000000_1790086400.json.gz": 30, "openfoodfacts_products_1790086400_1790172800.json.gz": 10,
             "openfoodfacts_products_1790172800_1790259200.json.gz": 20, "manifests": 1, "notes.txt": 2}
    assert d.pick_smallest(sizes, 2) == ["raw/deltas/openfoodfacts_products_1790086400_1790172800.json.gz",
                                         "raw/deltas/openfoodfacts_products_1790172800_1790259200.json.gz"]


def test_pick_refuses_when_there_are_too_few_files():
    with pytest.raises(ValueError, match="need 4"):
        d.pick_smallest({"openfoodfacts_products_1_2.json.gz": 1}, 4)


def test_cancel_time_is_a_fraction_of_the_measured_full_run():
    assert d.cancel_after(200.0, 0.75) == pytest.approx(150.0)
    with pytest.raises(ValueError):
        d.cancel_after(0, 0.5)
    with pytest.raises(ValueError):
        d.cancel_after(100, 1.2)


def test_window_before_anything_was_stored():
    assert d.window(set(), set(), set(KEYS)) == "before the first batch"


def test_window_between_batches_when_manifest_and_repo_agree():
    assert d.window(set(KEYS[:2]), set(KEYS[:2]), set(KEYS)) == "between batches"


def test_window_after_an_upload_before_its_manifest_write_is_the_risky_one():
    assert d.window(set(KEYS[:2]), set(KEYS[:3]), set(KEYS)) == "after an upload, before its manifest write (the risky window)"


def test_window_complete_when_every_file_is_recorded():
    assert d.window(set(KEYS), set(KEYS), set(KEYS)) == "after the last manifest write (nothing left to do)"


def test_a_sound_state_after_a_kill_has_every_recorded_file_stored_with_the_right_hash():
    assert d.state_problems({k: SHA[k] for k in KEYS[:2]}, {k: SHA[k] for k in KEYS[:3]}, SHA) == []


def test_a_recorded_file_missing_from_the_repo_is_a_problem():
    got = d.state_problems({k: SHA[k] for k in KEYS[:2]}, {KEYS[0]: SHA[KEYS[0]]}, SHA)
    assert len(got) == 1 and KEYS[1] in got[0] and "recorded but not stored" in got[0]


def test_a_recorded_file_with_the_wrong_bytes_is_a_problem():
    stored = {KEYS[0]: "e" * 64}
    got = d.state_problems({KEYS[0]: SHA[KEYS[0]]}, stored, SHA)
    assert len(got) == 1 and "different bytes" in got[0]


def test_a_manifest_that_records_a_wrong_hash_is_a_problem():
    got = d.state_problems({KEYS[0]: "e" * 64}, {KEYS[0]: SHA[KEYS[0]]}, SHA)
    assert len(got) == 1 and "manifest" in got[0]


def test_after_recovery_everything_must_be_recorded_and_stored_once():
    assert d.final_problems(KEYS, dict(SHA), dict(SHA), SHA) == []
    short = {k: SHA[k] for k in KEYS[:5]}
    got = d.final_problems(KEYS, short, dict(SHA), SHA)
    assert len(got) == 1 and KEYS[5] in got[0] and "not recorded" in got[0]


def test_files_outside_the_chosen_set_are_a_problem():
    extra = dict(SHA, **{"raw/deltas/other.json.gz": "a" * 64})
    got = d.final_problems(KEYS, dict(SHA), extra, SHA)
    assert len(got) == 1 and "other.json.gz" in got[0] and "outside the chosen set" in got[0]


def test_only_a_kill_between_batches_or_in_the_risky_window_counts():
    assert d.counts_as_kill("between batches")
    assert d.counts_as_kill("after an upload, before its manifest write (the risky window)")
    assert not d.counts_as_kill("before the first batch")
    assert not d.counts_as_kill("after the last manifest write (nothing left to do)")


def _trial(win, problems=()):
    return {"trial": 1, "window": win, "state_problems": list(problems), "final_problems": []}


def test_verdict_is_inconclusive_when_no_kill_landed_mid_run():
    base = {"trial": "baseline", "problems": []}
    late = _trial("after the last manifest write (nothing left to do)")
    assert d.overall_verdict([base, late, late]).startswith("INCONCLUSIVE")


def test_verdict_is_pass_with_one_real_kill_and_no_problems():
    base = {"trial": "baseline", "problems": []}
    assert d.overall_verdict([base, _trial("between batches")]).startswith("PASS (1 of 1")


def test_verdict_is_fail_when_any_run_has_a_problem_even_if_the_kill_was_late():
    base = {"trial": "baseline", "problems": []}
    bad = _trial("after the last manifest write (nothing left to do)", ["x: recorded but not stored in the repo"])
    assert d.overall_verdict([base, bad]).startswith("FAIL")
    assert d.overall_verdict([{"trial": "baseline", "problems": ["boom"]}]).startswith("FAIL")
    assert d.overall_verdict([]).startswith("FAIL")
