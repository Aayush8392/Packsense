"""B2 reconciliation rule, on real key shapes: the real delta file names the capture landed, the capture manifest entry fields the capture
writes (name, bytes, sha256, lines, b2_key, landing, b2_etag_matched), taxonomy log entries (name, sha256, bytes, snapshot ...) and archive
manifest entries (bytes, sha256, archived_at). Sizes and hashes are opaque numbers; the rule only compares them. Each failure case changes
one thing in an otherwise consistent whole.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bootstrap"))

import reconcile_lib as lib  # noqa: E402

NOW = datetime(2026, 10, 17, 16, 30, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=3)
NAMES = ["openfoodfacts_products_1791094877_1791181482.json.gz", "openfoodfacts_products_1791613749_1791700013.json.gz"]
SIZES = {NAMES[0]: 24_000_001, NAMES[1]: 19_300_002}
STAMP, TSTAMP = "20261014T125700Z", "20261014T130100Z"
SNAP = "data_quality/2026-10-09T08:00:00_ab12cd34ef56.json.gz"


def world():
    """A consistent bucket: two deltas, one capture manifest, one taxonomy log with one snapshot; everything archived."""
    manifest = {"files": [{"name": n, "bytes": SIZES[n], "sha256": "a" * 64, "lines": 5000, "b2_key": f"raw/deltas/{n}",
                           "landing": f"deltas/{n}", "b2_etag_matched": True} for n in NAMES]}
    log = {"log_version": 1, "entries": [{"name": "data_quality", "sha256": "b" * 64, "bytes": 4_000_000, "changed": True, "snapshot": SNAP}]}
    b2 = {f"raw/deltas/{n}": {"size": SIZES[n], "modified": OLD} for n in NAMES}
    b2[f"raw/manifests/{STAMP}.json"] = {"size": 1200, "modified": OLD}
    b2[f"taxonomies/_log/{TSTAMP}.json"] = {"size": 900, "modified": OLD}
    b2[f"taxonomies/{SNAP}"] = {"size": 300_000, "modified": OLD}
    archive = {k: {"bytes": v["size"], "sha256": "c" * 64, "archived_at": OLD.isoformat()} for k, v in b2.items()}
    return dict(b2=b2, capture_manifests={STAMP: manifest}, manifest_sizes={STAMP: 1200}, tax_logs={TSTAMP: log}, log_sizes={TSTAMP: 900},
                snapshot_sizes={SNAP: 300_000}, landing_deltas=dict(SIZES), archive_files=archive, now=NOW)


def run(w):
    return lib.reconcile(**w)


def codes(findings):
    return sorted((f.code, f.key) for f in findings)


def test_a_consistent_bucket_has_no_findings():
    assert run(world()) == []


def test_a_recorded_delta_file_missing_from_b2():
    w = world()
    del w["b2"][f"raw/deltas/{NAMES[0]}"]
    assert ("B2_MISSING", f"raw/deltas/{NAMES[0]}") in codes(run(w))


def test_a_delta_file_whose_size_in_b2_differs_from_the_record_and_from_landing():
    w = world()
    w["b2"][f"raw/deltas/{NAMES[1]}"]["size"] += 5
    got = codes(run(w))
    assert got.count(("SIZE_MISMATCH", f"raw/deltas/{NAMES[1]}")) == 2            # against the manifest and against landing
    assert ("ARCHIVE_SIZE_MISMATCH", f"raw/deltas/{NAMES[1]}") in got


def test_an_object_nobody_recorded_is_unexpected_but_folder_placeholders_are_not():
    w = world()
    w["b2"]["raw/deltas/openfoodfacts_products_1_2.json.gz"] = {"size": 10, "modified": OLD}
    w["b2"]["raw/"] = {"size": 0, "modified": OLD}
    w["archive_files"]["raw/deltas/openfoodfacts_products_1_2.json.gz"] = {"bytes": 10, "sha256": "d" * 64, "archived_at": OLD.isoformat()}
    assert codes(run(w)) == [("UNEXPECTED_OBJECT", "raw/deltas/openfoodfacts_products_1_2.json.gz")]


def test_a_manifest_or_log_that_differs_from_its_landing_copy_or_is_missing():
    w = world()
    w["b2"][f"raw/manifests/{STAMP}.json"]["size"] = 1
    w["archive_files"][f"raw/manifests/{STAMP}.json"]["bytes"] = 1
    del w["b2"][f"taxonomies/_log/{TSTAMP}.json"]
    w["archive_files"].pop(f"taxonomies/_log/{TSTAMP}.json")
    got = codes(run(w))
    assert ("SIZE_MISMATCH", f"raw/manifests/{STAMP}.json") in got and ("B2_MISSING", f"taxonomies/_log/{TSTAMP}.json") in got


def test_a_taxonomy_snapshot_is_checked_against_its_landing_copy_and_for_existence():
    w = world()
    w["b2"][f"taxonomies/{SNAP}"]["size"] = 7
    w["archive_files"][f"taxonomies/{SNAP}"]["bytes"] = 7
    assert ("SIZE_MISMATCH", f"taxonomies/{SNAP}") in codes(run(w))
    w = world()
    del w["b2"][f"taxonomies/{SNAP}"]
    w["archive_files"].pop(f"taxonomies/{SNAP}")
    assert ("B2_MISSING", f"taxonomies/{SNAP}") in codes(run(w))
    w = world()
    w["snapshot_sizes"] = {}                       # not in landing: existence only, no size comparison, no finding
    assert run(w) == []


def test_a_delta_in_landing_with_no_object_in_b2():
    w = world()
    w["landing_deltas"]["openfoodfacts_products_9_10.json.gz"] = 5
    assert codes(run(w)) == [("LANDING_NOT_IN_B2", "raw/deltas/openfoodfacts_products_9_10.json.gz")]


def test_an_old_object_missing_from_the_archive_is_a_finding_but_a_fresh_one_is_not():
    w = world()
    del w["archive_files"][f"raw/deltas/{NAMES[0]}"]
    assert codes(run(w)) == [("NOT_ARCHIVED", f"raw/deltas/{NAMES[0]}")]
    w["b2"][f"raw/deltas/{NAMES[0]}"]["modified"] = NOW - timedelta(hours=lib.ARCHIVE_GRACE_HOURS - 1)
    assert run(w) == []


def test_an_archived_key_gone_from_b2_is_fine_only_after_the_lifecycle_window():
    w = world()
    key = f"raw/deltas/{NAMES[0]}"
    del w["b2"][key]
    w["landing_deltas"].pop(NAMES[0])
    w["capture_manifests"][STAMP]["files"] = [e for e in w["capture_manifests"][STAMP]["files"] if e["b2_key"] != key]
    assert codes(run(w)) == [("ARCHIVE_ONLY_TOO_SOON", key)]
    w["archive_files"][key]["archived_at"] = (NOW - timedelta(days=lib.RAW_HIDE_AFTER_DAYS + 1)).isoformat()
    assert run(w) == []


def test_the_summary_names_the_codes_and_stays_short():
    w = world()
    w["b2"].pop(f"raw/deltas/{NAMES[0]}")
    s = lib.summary(run(w))
    assert s.startswith("b2 reconcile: ") and "B2_MISSING" in s and len(s) <= 1000
    assert lib.summary([]) == "b2 reconcile: no findings"


def test_the_archive_job_runs_the_audit_after_the_archive_and_even_if_it_failed():
    pytest.importorskip("databricks.sdk")
    import create_archive_job as job
    tasks = {t.task_key: t for t in job.settings(True)["tasks"]}
    assert [d.task_key for d in tasks["reconcile"].depends_on] == ["archive"] and tasks["reconcile"].run_if.value == "ALL_DONE"
    assert tasks["reconcile"].notebook_task.notebook_path == "p1_intake/notebooks/b2_reconcile"
    assert set(tasks["reconcile"].notebook_task.base_parameters) == {"run_id"}
    root = Path(__file__).resolve().parents[2]
    assert (root / (job.RECONCILE_NOTEBOOK + ".py")).exists()

