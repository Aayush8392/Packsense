"""Archive job logic.

Real material only: the keys are real OFF delta file names and a real taxonomy snapshot path from this project, and the
file bytes are the real sanitised bronze records in p2_lakehouse/tests/fixtures (gzipped the way a delta file is).
"""
import gzip
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import archive_lib as a  # noqa: E402

FIXTURE = Path(__file__).resolve().parents[2] / "p2_lakehouse" / "tests" / "fixtures" / "bronze_records.jsonl"
DELTA = "raw/deltas/openfoodfacts_products_1791094877_1791181482.json.gz"
DELTA2 = "raw/deltas/openfoodfacts_products_1791613749_1791700013.json.gz"
CAPTURE_MANIFEST = "raw/manifests/20261013T211908Z.json"
TAXONOMY = "taxonomies/data_quality/1760000000_0123456789ab.json.gz"
SCRATCH = "tmp/marker-test.txt"


@pytest.fixture(scope="module")
def delta_bytes():
    lines = [json.loads(x)["raw_json"] for x in FIXTURE.read_text(encoding="utf-8").splitlines() if x.strip()]
    return gzip.compress("\n".join(lines).encode("utf-8"))


def test_only_raw_and_taxonomies_are_archivable():
    assert a.is_archivable(DELTA) and a.is_archivable(CAPTURE_MANIFEST) and a.is_archivable(TAXONOMY)
    assert not a.is_archivable(SCRATCH)
    assert not a.is_archivable("raw/")  # a folder placeholder
    assert not a.is_archivable("archive/manifest.json")


def test_capture_manifest_names_are_recognised():
    assert a.is_capture_manifest(CAPTURE_MANIFEST)
    assert not a.is_capture_manifest(DELTA)
    assert not a.is_capture_manifest("raw/manifests/notes.txt")


def test_plan_lists_only_keys_not_yet_archived_in_order():
    m = a.new_manifest()
    a.record(m, DELTA, {"bytes": 10, "sha256": "x", "checked_against": []}, "r1", "t")
    todo, changed = a.plan({DELTA2: 5, DELTA: 10, SCRATCH: 1, TAXONOMY: 7}, m)
    assert todo == sorted([DELTA2, TAXONOMY]) and changed == []


def test_plan_reports_a_size_change_and_never_re_archives_it():
    m = a.new_manifest()
    a.record(m, DELTA, {"bytes": 10, "sha256": "x", "checked_against": []}, "r1", "t")
    todo, changed = a.plan({DELTA: 11}, m)
    assert todo == [] and changed == [DELTA]


def test_a_key_b2_no_longer_lists_is_left_alone():
    m = a.new_manifest()
    a.record(m, DELTA, {"bytes": 10, "sha256": "x", "checked_against": []}, "r1", "t")
    assert a.plan({}, m) == ([], [])


def test_manifest_round_trip_and_missing_manifest():
    assert a.load_manifest(None) == a.new_manifest()
    m = a.new_manifest()
    a.record(m, DELTA, {"bytes": 3, "sha256": "abc", "checked_against": ["gzip_complete"]}, "run-9", "2026-10-15T16:00:00Z")
    assert a.load_manifest(a.dump_manifest(m)) == m


def test_unknown_manifest_format_is_refused():
    with pytest.raises(ValueError):
        a.load_manifest(json.dumps({"manifest_version": 99, "files": {}}).encode())


def test_expected_sha256_comes_from_capture_manifest_entries():
    manifests = [{"files": [{"b2_key": DELTA, "sha256": "aa"}]}, {"files": [{"b2_key": DELTA2, "sha256": "bb"}]}]
    assert a.expected_sha256(manifests) == {DELTA: "aa", DELTA2: "bb"}


def test_good_delta_passes_and_records_how_it_was_checked(delta_bytes):
    sha = hashlib.sha256(delta_bytes).hexdigest()
    etag = '"' + hashlib.md5(delta_bytes).hexdigest() + '"'
    problem, facts = a.check_download(DELTA, delta_bytes, len(delta_bytes), etag, {DELTA: sha})
    assert problem is None
    assert facts["sha256"] == sha
    assert facts["checked_against"] == ["b2_etag_md5", "gzip_complete", "capture_manifest_sha256"]


def test_sha_that_differs_from_the_capture_record_is_refused(delta_bytes):
    problem, _ = a.check_download(DELTA, delta_bytes, len(delta_bytes), "multipart-2", {DELTA: "0" * 64})
    assert problem and "differs from the one the capture recorded" in problem


def test_truncated_download_is_refused(delta_bytes):
    cut = delta_bytes[: len(delta_bytes) // 2]
    problem, _ = a.check_download(DELTA, cut, len(cut), "multipart-2", {})
    assert problem and "truncated" in problem


def test_download_shorter_than_b2_lists_is_refused(delta_bytes):
    problem, _ = a.check_download(DELTA, delta_bytes, len(delta_bytes) + 1, "multipart-2", {})
    assert problem and "B2 lists" in problem


def test_etag_mismatch_is_refused(delta_bytes):
    problem, _ = a.check_download(DELTA, delta_bytes, len(delta_bytes), "0" * 32, {})
    assert problem and "ETag" in problem


def test_multipart_style_etag_is_not_compared(delta_bytes):
    assert not a.etag_is_md5("d41d8cd98f00b204e9800998ecf8427e-3")
    problem, facts = a.check_download(DELTA, delta_bytes, len(delta_bytes), "d41d8cd98f00b204e9800998ecf8427e-3", {})
    assert problem is None and "b2_etag_md5" not in facts["checked_against"]


def test_delta_without_a_capture_entry_is_archived_but_flagged(delta_bytes):
    problem, facts = a.check_download(DELTA, delta_bytes, len(delta_bytes), "multipart-2", {})
    assert problem is None and facts["checked_against"] == ["gzip_complete", "none_no_capture_manifest_entry"]


def test_non_gzip_file_is_checked_only_by_size(delta_bytes):
    body = json.dumps({"files": [], "failed": False}).encode()
    problem, facts = a.check_download(CAPTURE_MANIFEST, body, len(body), "multipart-2", {})
    assert problem is None and facts["checked_against"] == []


def test_hf_lfs_file_is_matched_on_sha256(delta_bytes):
    facts = {"sha256": hashlib.sha256(delta_bytes).hexdigest()}
    assert a.hf_matches(facts, delta_bytes, facts["sha256"], None)
    assert not a.hf_matches(facts, delta_bytes, "0" * 64, None)


def test_hf_plain_file_is_matched_on_the_git_blob_id():
    body = json.dumps({"files": [], "failed": False}).encode()
    facts = {"sha256": hashlib.sha256(body).hexdigest()}
    assert a.git_blob_sha1(body) == hashlib.sha1(b"blob %d\0" % len(body) + body).hexdigest()
    assert a.hf_matches(facts, body, None, a.git_blob_sha1(body))
    assert not a.hf_matches(facts, body, None, "0" * 40)
    assert not a.hf_matches(facts, body, None, None)


def test_git_blob_id_of_the_empty_file_is_gits_well_known_value():
    assert a.git_blob_sha1(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"


SHA_A, SHA_B = "a" * 64, "b" * 64


def test_a_lost_manifest_is_refilled_from_hf_for_files_that_match_without_any_download():
    m = a.new_manifest()
    b2 = {DELTA: 100, DELTA2: 200}
    hf = {DELTA: {"size": 100, "sha256": SHA_A}, DELTA2: {"size": 200, "sha256": SHA_B}}
    rebuilt, redo = a.rebuild_from_listing(m, b2, hf, {DELTA: SHA_A, DELTA2: SHA_B}, "run-1", "t")
    assert rebuilt == sorted([DELTA, DELTA2]) and redo == []
    assert m["files"][DELTA]["checked_against"] == ["hf_lfs_sha256", "capture_manifest_sha256"]
    assert m["files"][DELTA]["rebuilt_from_hf_listing"] is True
    assert a.plan(b2, m) == ([], [])   # nothing left to download


def test_a_size_difference_or_a_missing_path_means_archive_again():
    m = a.new_manifest()
    b2 = {DELTA: 100, DELTA2: 200}
    hf = {DELTA: {"size": 99, "sha256": SHA_A}}
    rebuilt, redo = a.rebuild_from_listing(m, b2, hf, {DELTA: SHA_A, DELTA2: SHA_B}, "run-1", "t")
    assert rebuilt == [] and redo == sorted([DELTA, DELTA2]) and m["files"] == {}


def test_a_sha_that_differs_from_the_capture_record_is_never_rebuilt():
    m = a.new_manifest()
    rebuilt, redo = a.rebuild_from_listing(m, {DELTA: 100}, {DELTA: {"size": 100, "sha256": SHA_B}}, {DELTA: SHA_A}, "r", "t")
    assert rebuilt == [] and redo == [DELTA]


def test_a_small_hf_file_without_lfs_sha256_is_archived_again():
    m = a.new_manifest()
    rebuilt, redo = a.rebuild_from_listing(m, {CAPTURE_MANIFEST: 40}, {CAPTURE_MANIFEST: {"size": 40, "sha256": None}}, {}, "r", "t")
    assert rebuilt == [] and redo == [CAPTURE_MANIFEST]


def test_a_delta_without_a_capture_entry_is_archived_again_but_a_taxonomy_snapshot_is_rebuilt():
    m = a.new_manifest()
    b2 = {DELTA: 100, TAXONOMY: 7}
    hf = {DELTA: {"size": 100, "sha256": SHA_A}, TAXONOMY: {"size": 7, "sha256": SHA_B}}
    rebuilt, redo = a.rebuild_from_listing(m, b2, hf, {}, "r", "t")
    assert rebuilt == [TAXONOMY] and redo == [DELTA]
    assert m["files"][TAXONOMY]["checked_against"] == ["hf_lfs_sha256"]


def test_scratch_keys_are_ignored_and_a_rebuilt_manifest_round_trips():
    m = a.new_manifest()
    rebuilt, redo = a.rebuild_from_listing(m, {SCRATCH: 1, DELTA: 100}, {DELTA: {"size": 100, "sha256": SHA_A}}, {DELTA: SHA_A}, "r", "t")
    assert rebuilt == [DELTA] and redo == [] and SCRATCH not in m["files"]
    assert a.load_manifest(a.dump_manifest(m)) == m


def test_batches_split_in_order():
    assert a.batches([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
    assert a.batches([], 3) == []
