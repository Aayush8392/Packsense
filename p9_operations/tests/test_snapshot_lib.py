"""p9_operations/snapshot_lib.py. The commit list in fixtures/ is OFF's real Hugging Face history (150 commits, 2026-08-06 to 2026-10-19); the
tag list and the product slice come from two real snapshots (1 and 19 Oct 2026), exported through the repo's exit function."""
import datetime as dt
import json
import sys
import threading
import time
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import snapshot_lib as lib  # noqa: E402

COMMITS = json.loads((HERE / "fixtures" / "hf_commits.json").read_text(encoding="utf-8"))
UTC = dt.timezone.utc


# --- which snapshots ----------------------------------------------------------------------------------------------------------------------

def test_weekly_targets_are_mondays_at_midnight_utc_oldest_first_and_stable_through_the_week():
    for now in (dt.datetime(2026, 10, 20, 9, 0, tzinfo=UTC), dt.datetime(2026, 10, 25, 23, 59, tzinfo=UTC), dt.datetime(2026, 10, 19, 0, 0, tzinfo=UTC)):
        t = lib.weekly_targets(now, 12)
        assert len(t) == 13 and t == sorted(t)
        assert all(x.weekday() == 0 and (x.hour, x.minute, x.second) == (0, 0, 0) for x in t)
        assert t[-1] == dt.datetime(2026, 10, 19, tzinfo=UTC)          # the same Monday for every day of that week
        assert all((b - a) == dt.timedelta(weeks=1) for a, b in zip(t, t[1:]))


def test_weekly_targets_follow_the_calendar_across_a_new_week():
    assert lib.weekly_targets(dt.datetime(2026, 10, 26, 0, 0, tzinfo=UTC), 0) == [dt.datetime(2026, 10, 26, tzinfo=UTC)]


def test_every_picked_snapshot_is_the_newest_commit_at_or_before_its_target():
    targets = lib.weekly_targets(dt.datetime(2026, 10, 20, 9, 0, tzinfo=UTC), 9)   # the fixture starts 2026-08-06: nine weeks back are all covered
    snaps = lib.pick_snapshots(COMMITS, targets)
    assert len(snaps) == 10
    dates = sorted(lib.parse_commit_date(c["date"]) for c in COMMITS)
    for target, snap in zip(targets, snaps):
        assert snap.date <= target
        assert not [d for d in dates if snap.date < d <= target]           # nothing newer fits under the target
    assert [s.date for s in snaps] == sorted(s.date for s in snaps)


def test_targets_older_than_the_commit_list_are_skipped_not_invented():
    snaps = lib.pick_snapshots(COMMITS, lib.weekly_targets(dt.datetime(2026, 10, 20, 9, 0, tzinfo=UTC), 12))
    assert len(snaps) == 11 and all(s.date >= lib.parse_commit_date("2026-08-06T00:00:00Z") for s in snaps)


def test_a_target_older_than_every_commit_is_skipped_and_the_same_commit_is_kept_once():
    old = dt.datetime(2020, 1, 6, tzinfo=UTC)
    assert lib.pick_snapshots(COMMITS, [old]) == []
    newest = lib.parse_commit_date(COMMITS[0]["date"])
    a, b = newest + dt.timedelta(days=1), newest + dt.timedelta(days=8)
    picked = lib.pick_snapshots(COMMITS, [a, b])
    assert len(picked) == 1 and picked[0].sha == COMMITS[0]["id"]


def test_pairs_to_do_skips_finished_pairs_goes_oldest_first_and_honours_the_cap():
    snaps = lib.pick_snapshots(COMMITS, lib.weekly_targets(dt.datetime(2026, 10, 20, tzinfo=UTC), 5))
    all_pairs = lib.pairs_to_do(snaps, set(), 99)
    assert len(all_pairs) == len(snaps) - 1
    assert [lib.pair_id(a, b) for a, b in all_pairs] == [lib.pair_id(a, b) for a, b in zip(snaps, snaps[1:])]
    done = {lib.pair_id(*all_pairs[0]), lib.pair_id(*all_pairs[1])}
    rest = lib.pairs_to_do(snaps, done, 2)
    assert rest == all_pairs[2:4]
    assert lib.pairs_to_do(snaps, {lib.pair_id(a, b) for a, b in all_pairs}, 5) == []


def test_pair_ids_are_short_stable_and_distinct():
    snaps = lib.pick_snapshots(COMMITS, lib.weekly_targets(dt.datetime(2026, 10, 20, tzinfo=UTC), 12))
    ids = [lib.pair_id(a, b) for a, b in zip(snaps, snaps[1:])]
    assert len(set(ids)) == len(ids) and all(len(i) == 25 for i in ids)


def test_retention_cutoff_counts_calendar_months_and_clips_the_day():
    assert lib.retention_cutoff(dt.datetime(2026, 10, 20, tzinfo=UTC), 13) == dt.date(2025, 9, 20)
    assert lib.retention_cutoff(dt.datetime(2026, 3, 31, tzinfo=UTC), 1) == dt.date(2026, 2, 28)
    assert lib.retention_cutoff(dt.datetime(2026, 1, 15, tzinfo=UTC), 3) == dt.date(2025, 10, 15)
    assert lib.retention_cutoff(dt.datetime(2026, 12, 1, tzinfo=UTC), 12) == dt.date(2025, 12, 1)


# --- the byte guard -----------------------------------------------------------------------------------------------------------------------

def test_the_byte_guard_interrupts_once_the_limit_is_passed():
    counter = {"n": 0}
    fired = threading.Event()
    with lib.ByteGuard(lambda: counter["n"], 1000, fired.set, poll=0.01) as g:
        counter["n"] += 500
        time.sleep(0.05)
        assert not fired.is_set()
        counter["n"] += 700
        assert fired.wait(2)
    assert g.tripped and g.received() == 1200


def test_the_byte_guard_stays_quiet_below_the_limit():
    counter = {"n": 10}
    fired = threading.Event()
    with lib.ByteGuard(lambda: counter["n"], 1000, fired.set, poll=0.01) as g:
        counter["n"] += 900
        time.sleep(0.05)
    assert not g.tripped and not fired.is_set() and g.received() == 900


def test_read_rx_bytes_sums_every_interface_except_loopback(tmp_path):
    f = tmp_path / "dev"
    f.write_text("Inter-|   Receive\n face |bytes packets\n    lo: 999 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n  eth0: 100 2 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n  eth1: 25 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n",
                 encoding="utf-8")
    assert lib.read_rx_bytes(str(f)) == 125


# --- tables and the job -------------------------------------------------------------------------------------------------------------------

def test_every_table_has_a_definition_in_the_snapshots_schema_and_the_columns_read_back():
    d = lib.ddl("workspace.packsense_snapshots")
    assert set(d) == set(lib.TABLES)
    for name, sql in d.items():
        assert f"workspace.packsense_snapshots.{name} (" in sql and "USING DELTA" in sql
    assert lib.ddl_columns(d["snapshot_open_counts"]) == ["snapshot_sha", "snapshot_date", "severity", "flag", "family", "open_pairs"]
    assert "pair_id" in lib.ddl_columns(d["snapshot_manifest"]) and "family_remains" in lib.ddl_columns(d["snapshot_flag_events"])


def test_the_job_runs_weekly_without_retry_and_passes_no_secret_as_a_parameter():
    res = Path(__file__).resolve().parents[2] / "p3_delivery" / "resources" / "snapshots_job.yml"
    job = yaml.safe_load(res.read_text(encoding="utf-8"))["resources"]["jobs"]["snapshots"]
    assert job["name"] == "packsense-snapshots" and job["max_concurrent_runs"] == 1
    assert job["schedule"]["quartz_cron_expression"] == "0 0 12 ? * MON"
    (task,) = job["tasks"]
    assert task["disable_auto_optimization"] is True
    assert task["notebook_task"]["notebook_path"].endswith("p9_operations/notebooks/snapshot_events.py")
    for name in task["notebook_task"]["base_parameters"]:
        assert not any(w in name.lower() for w in ("token", "password", "key", "hmac")), name
    assert Path(res.parent / task["notebook_task"]["notebook_path"]).resolve().is_file()


def test_the_notebook_only_reads_columns_the_library_names_and_never_a_contributor_field():
    text = (HERE.parent / "notebooks" / "snapshot_events.py").read_text(encoding="utf-8")
    assert "editors" not in text and "creator" not in text and "last_editor" not in text and "informers" not in text
    cols = lib.load_sql("x", "http://example")
    for needed in ("code", "last_modified_t", "data_quality_errors_tags", "data_quality_warnings_tags", "data_quality_info_tags"):
        assert needed in cols
    assert "countries_tags" not in cols and "editors" not in cols
    assert "qualify row_number()" in cols                      # one row per barcode
    assert "byte guard" in text.lower() or "ByteGuard" in text


def test_the_url_is_resolved_once_and_the_signed_address_comes_back(monkeypatch):
    class Err(lib.urllib.error.HTTPError):
        pass

    class Opener:
        def __init__(self):
            self.calls = []
        def open(self, req):
            self.calls.append(req.full_url)
            raise lib.urllib.error.HTTPError(req.full_url, 302, "Found", {"location": "https://cdn.example/signed?a=b*c"}, None)

    op = Opener()
    assert lib.resolve_cdn("abc123", build_opener=lambda *h: op) == "https://cdn.example/signed?a=b*c"
    assert op.calls == [f"https://huggingface.co/datasets/{lib.REPO}/resolve/abc123/food.parquet"]
    with pytest.raises(lib.urllib.error.HTTPError):
        class Bad:
            def open(self, req):
                raise lib.urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, None)
        lib.resolve_cdn("abc123", build_opener=lambda *h: Bad())


# --- the flag family on the real tags -------------------------------------------------------------------------------------------------------

TAGS = json.loads((HERE / "fixtures" / "flag_tags.json").read_text(encoding="utf-8"))["tags"]


def test_real_tag_list_has_the_expected_size_and_every_tag_has_a_known_family():
    tags = {t["tag"] for t in TAGS}
    assert len(tags) == 1538                              # distinct tags across the two real snapshots
    fams = {lib.family_key(t) for t in tags}
    assert all(f and ":" not in f for f in fams)
    assert len(fams) == 1243                              # per-source variants collapse into their plain family


def test_no_real_tag_still_carries_a_source_or_basis_marker_after_the_family_key():
    assert [t["tag"] for t in TAGS if lib.looks_unparsed(t["tag"])] == []


@pytest.mark.parametrize("tag,family", [
    ("en:nutrition-value-total-over-105", "value-total-over-105"),
    ("en:nutrition-packaging-as-sold-100g-value-total-over-105", "value-total-over-105"),
    ("en:energy-value-in-kcal-does-not-match-value-in-kj", "energy-value-in-kcal-does-not-match-value-in-kj"),
    ("en:nutrition-packaging-as-sold-serving-energy-value-in-kcal-does-not-match-value-in-kj", "energy-value-in-kcal-does-not-match-value-in-kj"),
    ("en:nutrition-manufacturer-as-sold-100ml-salt-does-not-match-sodium", "salt-does-not-match-sodium"),
    ("en:nutrition-packaging-as-sold-100--energy-value-in-kcal-does-not-match-value-computed-from-other-nutrients", "energy-value-in-kcal-does-not-match-value-computed-from-other-nutrients"),
    ("en:nutrition-packaging-as-sold-100mmol-l-energy-value-in-kcal-may-not-match-value-computed-from-other-nutrients", "energy-value-in-kcal-may-not-match-value-computed-from-other-nutrients"),
    ("en:nutrition-packaging-prepared-100ml-saturated-fat-greater-than-fat", "saturated-fat-greater-than-fat"),
])
def test_family_key_on_real_tag_shapes(tag, family):
    assert lib.family_key(tag) == family


def test_a_tag_and_its_per_source_variants_share_one_family_in_the_real_list():
    by = {}
    for t in TAGS:
        by.setdefault(lib.family_key(t["tag"]), set()).add(t["tag"])
    group = by["energy-value-in-kcal-does-not-match-value-in-kj"]
    assert "en:energy-value-in-kcal-does-not-match-value-in-kj" in group
    assert any("packaging-as-sold-100g" in t for t in group) and len(group) >= 4
    assert looks_unparsed_is_false_for_plain_tags()


def looks_unparsed_is_false_for_plain_tags():
    return not lib.looks_unparsed("en:energy-value-in-kcal-does-not-match-value-in-kj") and not lib.looks_unparsed("en:nutrition-value-negative-copper")


def test_a_source_marker_the_module_does_not_know_is_reported_not_swallowed():
    assert lib.looks_unparsed("en:nutrition-estimate-as-sold-per-bowl-energy-value-in-kcal-does-not-match-value-in-kj") is False   # not matched by the marker either
    assert lib.looks_unparsed("en:nutrition-newsource-as-sold-100g-future-check") is False                                       # known shape: stripped
    assert lib.looks_unparsed("en:x-sold-100g-y") is True                                                                       # a marker left in the family


# --- comparing two real snapshots (DuckDB) --------------------------------------------------------------------------------------------------

duckdb = pytest.importorskip("duckdb")
SLICE = json.loads((HERE / "fixtures" / "pair_slice.json").read_text(encoding="utf-8"))


def _con():
    con = duckdb.connect()
    for t in ("p", "n"):
        con.execute(f"create table {t} (code varchar, lm bigint, e varchar[], w varchar[], i varchar[])")
    for r in SLICE["pairs"]:
        con.execute("insert into p values (?,?,?,?,?)", [r["code"], r["lm_a"], r["e_a"], r["w_a"], r["i_a"]])
        con.execute("insert into n values (?,?,?,?,?)", [r["code"], r["lm_c"], r["e_c"], r["w_c"], r["i_c"]])
    for r in SLICE["only_a"]:
        con.execute("insert into p values (?,?,?,?,?)", [r["code"], r["lm"], r["e"], r["w"], r["i"]])
    for r in SLICE["only_c"]:
        con.execute("insert into n values (?,?,?,?,?)", [r["code"], r["lm"], r["e"], r["w"], r["i"]])
    return con


RESULT_CON = _con()


def _reference():
    """The same answer worked out directly from the fixture rows with plain sets (an independent formulation)."""
    events = set()
    for r in SLICE["pairs"]:
        edited = r["lm_a"] != r["lm_c"]
        for sev, a, c in (("error", "e_a", "e_c"), ("warning", "w_a", "w_c"), ("info", "i_a", "i_c")):
            old, new = set(r[a]), set(r[c])
            for t in old - new:
                events.add((r["code"], sev, t, "disappeared", any(lib.family_key(x) == lib.family_key(t) for x in new), edited))
            for t in new - old:
                events.add((r["code"], sev, t, "appeared", any(lib.family_key(x) == lib.family_key(t) for x in old), edited))
    return events


def test_the_pair_comparison_matches_an_independent_calculation_on_real_rows():
    res = lib.compute_pair(RESULT_CON)
    got = {(e["code"], e["severity"], e["flag"], e["event"], e["family_remains"], e["edited"]) for e in res["events"]}
    assert got == _reference()
    assert len(res["events"]) == len(got) == res["stats"]["flag_events"]
    assert all(e["family"] == lib.family_key(e["flag"]) for e in res["events"])


def test_the_pair_comparison_counts_products_that_stay_leave_and_enter():
    res = lib.compute_pair(RESULT_CON)
    s = res["stats"]
    assert s["in_both"] == len(SLICE["pairs"]) == 185
    assert s["left_count"] == len(SLICE["only_a"]) == 12 and s["entered_count"] == len(SLICE["only_c"]) == 12
    assert s["rows_from"] == 185 + 12 and s["rows_to"] == 185 + 12
    assert s["edited_count"] == sum(r["lm_a"] != r["lm_c"] for r in SLICE["pairs"])
    assert sorted(c for c, _ in res["left"]) == sorted(r["code"] for r in SLICE["only_a"])


def test_cases_behave_as_selected_edited_products_without_flag_change_have_no_events_and_unchanged_ones_neither():
    res = lib.compute_pair(RESULT_CON)
    by_code = {}
    for e in res["events"]:
        by_code.setdefault(e["code"], []).append(e)
    for r in SLICE["pairs"]:
        ev = by_code.get(r["code"], [])
        if r["case"] == "unchanged":
            assert not ev and r["lm_a"] == r["lm_c"]
        if r["case"] == "edited_no_flag_change":
            assert not ev and r["lm_a"] != r["lm_c"]
        if r["case"] == "error_gone":
            assert any(e["severity"] == "error" and e["event"] == "disappeared" for e in ev)
        if r["case"] == "flag_appeared":
            assert any(e["event"] == "appeared" for e in ev)


def test_a_disappeared_flag_almost_always_comes_with_an_edit_in_the_real_rows():
    # Measured on all 4.7 M products (1 to 19 Oct): 1,102 of 1,102 error products, 22,577 of 22,613 warning products and 34,615 of 34,616 info products
    # were edited. The few that were not are OFF recomputing a flag without a user edit, so a label must not assume the edit.
    res = lib.compute_pair(RESULT_CON)
    gone = [e for e in res["events"] if e["event"] == "disappeared"]
    assert gone and sum(e["edited"] for e in gone) / len(gone) >= 0.97


def test_the_real_rows_contain_renames_that_the_family_catches():
    res = lib.compute_pair(RESULT_CON)
    renames = [e for e in res["events"] if e["event"] == "disappeared" and e["family_remains"]]
    fixes = [e for e in res["events"] if e["event"] == "disappeared" and not e["family_remains"]]
    assert renames and fixes
    assert any(e["flag"] != "" and lib.family_key(e["flag"]) != e["flag"].split(":", 1)[1] for e in renames)    # a per-source tag that was moved, not fixed


def test_open_counts_add_up_to_the_flags_the_rows_carry():
    con = RESULT_CON
    for table, rows in (("p", [(r["e_a"], r["w_a"], r["i_a"]) for r in SLICE["pairs"]] + [(r["e"], r["w"], r["i"]) for r in SLICE["only_a"]]),):
        counts = lib.open_counts(con, table)
        for sev, idx in (("error", 0), ("warning", 1), ("info", 2)):
            assert sum(n for s, _, n in counts if s == sev) == sum(len(r[idx]) for r in rows)
