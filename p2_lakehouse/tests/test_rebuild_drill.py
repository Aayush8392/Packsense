"""The pure decisions inside the rebuild drill: which days exist only in the archive, and the three-way sha256 check."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bootstrap"))

import rebuild_drill as r  # noqa: E402

DAY = 86_400


def name(i):
    return f"openfoodfacts_products_{1_790_000_000 + i * DAY}_{1_790_000_000 + (i + 1) * DAY}.json.gz"


ALL = [name(i) for i in range(6)]


def test_archive_only_days_are_loaded_in_both_layers_and_missing_from_landing():
    landing = set(ALL[3:])                                          # retention removed the three oldest from landing
    assert r.archive_only(set(ALL), set(ALL), landing) == ALL[:3]


def test_a_day_not_finished_in_silver_is_not_in_the_set():
    assert r.archive_only(set(ALL), set(ALL) - {ALL[1]}, set(ALL[3:])) == [ALL[0], ALL[2]]


def test_non_delta_names_are_ignored():
    assert r.archive_only(set(ALL) | {"manifests"}, set(ALL) | {"manifests"}, set()) == ALL


def test_set_is_oldest_first():
    assert r.archive_only(set(ALL), set(ALL), set()) == sorted(ALL, key=r.end_time)


def test_three_way_sha_agreement_gives_no_problem():
    sha = {n: f"{i:064x}" for i, n in enumerate(ALL[:2])}
    assert r.sha_problems(ALL[:2], sha, dict(sha), dict(sha)) == []


def test_a_restored_copy_that_differs_from_the_capture_record_is_a_problem():
    sha = {n: f"{i:064x}" for i, n in enumerate(ALL[:2])}
    bad = dict(sha, **{ALL[1]: "f" * 64})
    got = r.sha_problems(ALL[:2], bad, dict(sha), dict(sha))
    assert len(got) == 2 and all(ALL[1] in g for g in got)                       # it disagrees with BOTH records
    assert any("archive manifest" in g for g in got) and any("capture" in g for g in got)
    # when only the capture's record disagrees, only that is reported
    only_capture = r.sha_problems(ALL[:2], dict(sha), dict(sha), dict(sha, **{ALL[1]: "f" * 64}))
    assert len(only_capture) == 1 and "capture" in only_capture[0]


def test_a_file_missing_from_the_archive_manifest_is_a_problem():
    sha = {ALL[0]: "a" * 64}
    got = r.sha_problems(ALL[:1], sha, {}, sha)
    assert len(got) == 1 and "archive manifest" in got[0]


def test_a_file_that_was_not_restored_at_all_is_a_problem():
    sha = {ALL[0]: "a" * 64}
    got = r.sha_problems(ALL[:1], {}, sha, sha)
    assert len(got) == 1 and "not restored" in got[0]


def test_an_empty_set_is_refused():
    with pytest.raises(ValueError, match="nothing"):
        r.require_files([])
    assert r.require_files(ALL[:1]) == ALL[:1]
