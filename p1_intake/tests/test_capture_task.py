"""The Databricks capture task: the landing volume as a folder, the wait for OFF's publication, the lateness field and the notebook's order.

File names, end times and the Last-Modified value are real ones from OFF's index (13 files measured on 2026-10-18; the 18 Oct file ended
06:22:01 UTC and OFF stamped it Last-Modified 06:22:14 UTC). The file bytes are the real sanitised bronze records gzipped like a delta file.
The end-to-end proof is the real runs (a scratch run that uploads one file to B2 under tmp/, the failure drill, the first scheduled run).
"""
import datetime as dt
import gzip
import io
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import capture_deltas as cd  # noqa: E402

UTC = dt.timezone.utc
D16 = "openfoodfacts_products_1792045568_1792132384.json.gz"
D17 = "openfoodfacts_products_1792132384_1792217949.json.gz"
D18 = "openfoodfacts_products_1792217949_1792304521.json.gz"
FIXTURE = Path(__file__).resolve().parents[2] / "p2_lakehouse" / "tests" / "fixtures" / "bronze_records.jsonl"
NOTEBOOK = (Path(__file__).resolve().parent.parent / "notebooks" / "capture_task.py").read_text(encoding="utf-8")


def delta_bytes() -> bytes:
    lines = [json.loads(x)["raw_json"] for x in FIXTURE.read_text(encoding="utf-8").splitlines() if x.strip()]
    return gzip.compress("\n".join(lines).encode("utf-8"))


# ---- the landing volume as a folder -------------------------------------------------------------------------------------------

def test_a_file_written_to_the_local_landing_is_listed_sized_and_read_back(tmp_path):
    landing = cd.LocalLanding(str(tmp_path))
    data = delta_bytes()
    landing.put(f"deltas/{D18}", io.BytesIO(data))
    assert landing.names("deltas") == {D18}
    assert landing.size(f"deltas/{D18}") == len(data) and landing.get(f"deltas/{D18}") == data


def test_bytes_and_streams_both_work_and_a_rewrite_replaces_the_file(tmp_path):
    landing = cd.LocalLanding(str(tmp_path))
    landing.put("manifests/a.json", b"one")
    landing.put("manifests/a.json", io.BytesIO(b"two"))
    assert landing.get("manifests/a.json") == b"two"


def test_a_half_written_temp_file_is_never_listed_and_a_missing_folder_is_empty(tmp_path):
    landing = cd.LocalLanding(str(tmp_path))
    assert landing.names("deltas") == set()
    (tmp_path / "deltas").mkdir()
    (tmp_path / "deltas" / (".tmp-" + D18)).write_bytes(b"partial")
    landing.put(f"deltas/{D17}", b"whole")
    assert landing.names("deltas") == {D17}


def test_recorded_names_reads_every_capture_manifest_in_the_folder(tmp_path):
    landing = cd.LocalLanding(str(tmp_path))
    landing.put("manifests/20261017T114120Z.json", json.dumps({"files": [{"name": D17}]}).encode())
    landing.put("manifests/20261018T120733Z.json", json.dumps({"files": [{"name": D18}]}).encode())
    assert landing.recorded_names() == {D17, D18}


def test_the_factory_chooses_the_volume_folder_only_when_landing_root_is_set(monkeypatch, tmp_path):
    monkeypatch.setenv("LANDING_ROOT", str(tmp_path))
    assert isinstance(cd.make_landing(), cd.LocalLanding)
    monkeypatch.delenv("LANDING_ROOT")
    monkeypatch.setenv("DATABRICKS_HOST", "example.cloud.databricks.com")
    monkeypatch.setenv("DATABRICKS_PIPELINE_TOKEN", "t")
    assert isinstance(cd.make_landing(), cd.Landing)


# ---- waiting for OFF -------------------------------------------------------------------------------------------------------------

def at(epoch: int, minutes: int = 0) -> dt.datetime:
    return dt.datetime.fromtimestamp(epoch, UTC) + dt.timedelta(minutes=minutes)


def test_todays_file_counts_as_published_only_when_the_newest_file_ended_today():
    ended_18 = 1792304521
    assert cd.newest_published_today([D17, D18], at(ended_18, 23))        # 06:45 on 18 Oct: the 18 Oct file is listed
    assert not cd.newest_published_today([D16, D17], at(ended_18, 23))    # same time, file not out yet: the newest ended on 17 Oct
    assert cd.newest_published_today([D17, D18], at(ended_18, 60 * 14))   # a manual run at 20:00 UTC, file listed
    assert not cd.newest_published_today([], at(ended_18))


def test_wait_polls_every_interval_and_returns_as_soon_as_the_file_is_listed():
    ended_18 = 1792304521
    clock = {"now": at(ended_18, 23) - dt.timedelta(minutes=40)}      # 06:05 UTC: before OFF published
    reads = [[D16, D17], [D16, D17], [D17, D18]]
    slept = []

    def fetch():
        return reads.pop(0)

    def sleep(s):
        slept.append(s)
        clock["now"] += dt.timedelta(seconds=s)

    deadline = clock["now"].replace(hour=7, minute=45, second=0)
    published, polls, names = cd.wait_for_publication(fetch, lambda: clock["now"], sleep, deadline, 300)
    assert published and polls == 3 and slept == [300, 300] and names[-1] == D18


def test_wait_gives_up_at_the_deadline_and_never_sleeps_past_it():
    clock = {"now": dt.datetime(2026, 10, 18, 7, 30, tzinfo=UTC)}
    slept = []

    def sleep(s):
        slept.append(s)
        clock["now"] += dt.timedelta(seconds=s)

    deadline = dt.datetime(2026, 10, 18, 7, 45, tzinfo=UTC)
    published, polls, _ = cd.wait_for_publication(lambda: [D16, D17], lambda: clock["now"], sleep, deadline, 300)
    assert not published and slept == [300, 300, 300] and clock["now"] <= deadline


def test_wait_returns_at_once_when_the_deadline_has_already_passed():
    clock = {"now": dt.datetime(2026, 10, 18, 20, 0, tzinfo=UTC)}
    published, polls, _ = cd.wait_for_publication(lambda: [D16, D17], lambda: clock["now"], lambda s: None,
                                                  dt.datetime(2026, 10, 18, 7, 45, tzinfo=UTC), 300)
    assert not published and polls == 1


# ---- lateness and the B2 prefix --------------------------------------------------------------------------------------------------

def test_lateness_is_the_capture_time_minus_oFF_publication_of_the_newest_file():
    manifest = {"captured_at": "2026-10-18T06:47:14+00:00", "files": [
        {"name": D17, "off_last_modified": "Sat, 17 Oct 2026 06:19:23 GMT"},
        {"name": D18, "off_last_modified": "Sun, 18 Oct 2026 06:22:14 GMT"}]}
    assert cd.lateness_minutes(manifest) == 25.0


def test_lateness_is_none_when_nothing_new_was_captured_or_the_file_was_recovered():
    assert cd.lateness_minutes({"captured_at": "2026-10-18T06:47:14+00:00", "files": []}) is None
    assert cd.lateness_minutes({"captured_at": "2026-10-18T06:47:14+00:00", "files": [{"name": D18, "recovered": True}]}) is None


def test_b2_keys_use_raw_unless_a_scratch_prefix_is_set(monkeypatch):
    monkeypatch.delenv("B2_PREFIX", raising=False)
    assert cd.b2_prefix() == "raw"
    monkeypatch.setenv("B2_PREFIX", "tmp/a2-test/")
    assert cd.b2_prefix() == "tmp/a2-test"


# ---- the notebook's structure (it cannot run in a unit test) ---------------------------------------------------------------------

def test_the_success_ping_comes_after_the_capture_and_the_freshness_assertion_and_exit_is_outside_the_try_block():
    assert NOTEBOOK.index("freshness assertion failed") < NOTEBOOK.index('ping("", json.dumps(summary))')
    assert NOTEBOOK.index("code = cd.main(") < NOTEBOOK.index("freshness assertion failed")
    assert NOTEBOOK.index("except (Exception, SystemExit)") < NOTEBOOK.index("dbutils.notebook.exit(")
    assert 'ping("/fail"' in NOTEBOOK and "raise\n" in NOTEBOOK


def test_the_notebook_never_prints_or_pings_a_secret_value():
    for line in NOTEBOOK.splitlines():
        if line.lstrip().startswith("#"):
            continue
        if "print(" in line or "ping(" in line:
            assert not re.search(r"secrets\.get|B2_UPLOAD|ping_url\b.*(print|body)", line), line
    assert NOTEBOOK.count("dbutils.secrets.get") == 3   # the ping URL and the two B2 key halves, each read once


def test_the_failure_drill_stops_the_capture_before_anything_is_written():
    drill = NOTEBOOK.index("if DRILL_FAIL:")
    assert drill < NOTEBOOK.index("os.environ[\"LANDING_ROOT\"]") < NOTEBOOK.index("cd.main(")
