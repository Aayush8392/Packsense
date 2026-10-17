"""Landing retention rule, on the 15 real delta file names the capture landed (30 Sep to 16 Oct 2026 edits, OFF file-name format) and on
real archive-manifest key shapes. The sha256 values are opaque labels derived from the names: the rule only compares them for equality.
"""
import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bootstrap"))

import retention_lib as lib  # noqa: E402

NAMES = [f"openfoodfacts_products_{a}_{b}.json.gz" for a, b in [
    (1790749069, 1790836258), (1790836258, 1790922999), (1790922999, 1791008573), (1791008573, 1791094877), (1791094877, 1791181482),
    (1791181482, 1791268364), (1791268364, 1791354008), (1791354008, 1791440891), (1791440891, 1791527472), (1791527472, 1791613749),
    (1791613749, 1791700013), (1791700013, 1791786521), (1791786521, 1791872470), (1791872470, 1791958972), (1791958972, 1792045568)]]
SHA = {n: hashlib.sha256(n.encode()).hexdigest() for n in NAMES}
NEWEST_END = lib.end_time(NAMES[-1])


def at(days_after_newest):
    return NEWEST_END + timedelta(days=days_after_newest)


def test_end_time_and_age_come_from_the_name_not_from_file_dates():
    assert lib.end_time(NAMES[0]) == datetime.fromtimestamp(1790836258, tz=timezone.utc)
    assert round(lib.age_days(NAMES[-1], NEWEST_END + timedelta(days=2)), 6) == 2.0
    for not_delta in ("20261014T075312Z.json", "openfoodfacts_products_1_2.json", "data_quality", "x.json.gz"):
        assert lib.end_time(not_delta) is None and lib.age_days(not_delta, NEWEST_END) is None


def test_the_real_files_are_all_inside_the_window_today_so_nothing_is_deletable_yet():
    p = lib.plan(NAMES, SHA, SHA, at(0.5))
    assert p.delete == [] and set(p.kept.values()) == {lib.YOUNG}


def test_a_file_is_deleted_only_after_the_retention_period_and_oldest_first():
    now = at(30 - 3.5)          # the oldest files are now past 30 days, the newer ones are not
    p = lib.plan(NAMES, SHA, SHA, now)
    assert p.delete and p.delete == sorted(p.delete, key=lib.end_time)
    assert all(lib.age_days(n, now) > lib.RETENTION_DAYS for n in p.delete)
    assert all(lib.age_days(n, now) <= lib.RETENTION_DAYS for n in NAMES if n not in p.delete)
    assert p.delete == NAMES[:len(p.delete)]            # exactly the oldest ones


def test_a_file_off_still_listed_by_off_is_never_eligible_whatever_else_is_true():
    # OFF keeps about 14 days; with the default 30 the newest 14 days of files can never be deleted
    now = at(40)
    p = lib.plan(NAMES, SHA, SHA, now)
    for n in NAMES:
        if lib.age_days(n, now) <= 14:
            assert n not in p.delete
    assert lib.RETENTION_DAYS > 14


def test_not_loaded_in_bronze_blocks_the_delete():
    p = lib.plan(NAMES, {k: v for k, v in SHA.items() if k != NAMES[0]}, SHA, at(60))
    assert NAMES[0] not in p.delete and p.kept[NAMES[0]] == lib.NOT_IN_BRONZE


def test_not_in_the_archive_blocks_the_delete():
    p = lib.plan(NAMES, SHA, {k: v for k, v in SHA.items() if k != NAMES[1]}, at(60))
    assert NAMES[1] not in p.delete and p.kept[NAMES[1]] == lib.NOT_ARCHIVED


def test_bronze_and_archive_that_disagree_on_the_sha256_block_the_delete():
    other = dict(SHA)
    other[NAMES[2]] = "0" * 64
    p = lib.plan(NAMES, SHA, other, at(60))
    assert NAMES[2] not in p.delete and p.kept[NAMES[2]] == lib.DISAGREE
    assert NAMES[0] in p.delete


def test_empty_manifests_delete_nothing():
    assert lib.plan(NAMES, {}, SHA, at(60)).delete == []
    assert lib.plan(NAMES, SHA, {}, at(60)).delete == []


def test_the_per_run_cap_defers_the_rest_oldest_first():
    p = lib.plan(NAMES, SHA, SHA, at(60), max_deletions=3)
    assert p.delete == NAMES[:3] and p.deferred == NAMES[3:] and all(p.kept[n] == "over_the_per_run_cap" for n in p.deferred)
    assert lib.MAX_DELETIONS == 20


def test_names_that_are_not_delta_files_are_never_planned():
    stray = ["20261014T075312Z.json", "data_quality", "openfoodfacts_products_1_2.json", "notes.txt"]
    p = lib.plan(NAMES + stray, SHA | {s: "a" * 64 for s in stray}, SHA | {s: "a" * 64 for s in stray}, at(400))
    assert not set(stray) & set(p.delete) and all(p.kept[s] == lib.NOT_A_DELTA for s in stray)


def test_archive_shas_reads_only_the_delta_entries_of_the_real_manifest_key_shapes():
    files = {f"raw/deltas/{NAMES[0]}": {"bytes": 1, "sha256": SHA[NAMES[0]]},
             "raw/manifests/20261014T075312Z.json": {"bytes": 1, "sha256": "b" * 64},
             "taxonomies/data_quality/2026-10-09_abcdef123456.json.gz": {"bytes": 1, "sha256": "c" * 64},
             f"raw/deltas/{NAMES[1]}": {"bytes": 1}}
    assert lib.archive_shas(files) == {NAMES[0]: SHA[NAMES[0]]}


# ---- the job definition ----------------------------------------------------------------------------------------------------

def test_the_archive_job_runs_retention_second_and_only_if_the_archive_succeeded():
    import yaml
    resources = Path(__file__).resolve().parents[2] / "p3_delivery" / "resources"
    job = yaml.safe_load((resources / "archive_job.yml").read_text(encoding="utf-8"))["resources"]["jobs"]["archive"]
    tasks = {t["task_key"]: t for t in job["tasks"]}
    assert list(tasks) == ["archive", "retention", "reconcile"] and "depends_on" not in tasks["archive"]
    assert [d["task_key"] for d in tasks["retention"]["depends_on"]] == ["archive"]
    assert tasks["retention"]["run_if"] == "ALL_SUCCESS"
    assert tasks["retention"]["notebook_task"]["notebook_path"].endswith("p1_intake/notebooks/landing_retention.py")
    for name in tasks["retention"]["notebook_task"]["base_parameters"]:                 # no secret value is a parameter
        assert not any(w in name.lower() for w in ("token", "password", "key", "hmac")), name
    assert job["schedule"]["quartz_cron_expression"] == "0 0 16 * * ?" and job["max_concurrent_runs"] == 1
    assert (resources / tasks["retention"]["notebook_task"]["notebook_path"]).resolve().exists()
