"""p9_operations/existence_lib.py on real data: the API answers in fixtures/off_api_responses.json were fetched from OFF on 2026-10-20 for real products
(some had left a weekly snapshot, some are still in it, three are odd barcodes); the products and their edit times are the real slice of two snapshots."""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import existence_lib as rl  # noqa: E402

API = {r["code"]: r for r in json.loads((HERE / "fixtures" / "off_api_responses.json").read_text(encoding="utf-8"))["responses"]}
SLICE = json.loads((HERE / "fixtures" / "pair_slice.json").read_text(encoding="utf-8"))
UTC = dt.timezone.utc


def _classify(code):
    r = API[code]
    return rl.classify_response(r["http"], {"status": r["status"], "status_verbose": r["status_verbose"]})


# --- the answer of one lookup --------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("code,status,detail", [
    ("3614790000309", rl.STATUS_MOVED, "beauty"),             # left a weekly snapshot: OFF moved it to Open Beauty Facts
    ("8909106057647", rl.STATUS_MOVED, "beauty"),
    ("9788831013185", rl.STATUS_MOVED, "product"),            # moved to the general products database
    ("4006508176571", rl.STATUS_MOVED, "product"),
    ("9781338214611", rl.STATUS_NOT_FOUND, ""),               # really gone
    ("9040732330977", rl.STATUS_NOT_FOUND, ""),
    ("5411883501440", rl.STATUS_EXISTS, ""),                  # still in the snapshot and on OFF
    ("76139321", rl.STATUS_EXISTS, ""),
    ("4088600237008060399", rl.STATUS_NOT_FOUND, ""),         # a 19-digit code
    ("0000000000000", rl.STATUS_INVALID, ""),                 # HTTP 200 with status 0 'no code or invalid code'
    ("00078067", rl.STATUS_MOVED, "beauty"),                  # an EAN-8 style code that is a beauty product
])
def test_real_api_answers_map_to_the_expected_status(code, status, detail):
    assert _classify(code) == {"status": status, "detail": detail}


def test_every_real_answer_is_recognised_none_falls_to_unconfirmed():
    assert all(_classify(c)["status"] != rl.STATUS_UNCONFIRMED for c in API)


def test_the_real_products_that_left_a_snapshot_are_mostly_not_deleted_but_moved_or_not_found():
    left = [_classify(c)["status"] for c, r in API.items() if r["kind"] == "left_snapshot"]
    assert sorted(left) == sorted([rl.STATUS_MOVED] * 4 + [rl.STATUS_NOT_FOUND] * 2)


@pytest.mark.parametrize("http,body,error", [
    (429, None, None), (500, {}, None), (503, {"status": 0}, None),                     # rate limit and server errors: the caller retries, the last one is unconfirmed
    (None, None, "timed out"), (200, None, None), (200, {"unexpected": 1}, None),       # no answer, no body, a body without `status`
    (404, {"status": 0, "status_verbose": "something new OFF may add"}, None),          # an answer we do not know: never guessed
    (200, {"status": 1, "status_verbose": "product found"}, "boom"),                    # an error wins over a body
])
def test_anything_not_clearly_answered_is_unconfirmed(http, body, error):
    assert rl.classify_response(http, body, error)["status"] == rl.STATUS_UNCONFIRMED


def test_status_one_needs_http_200_to_count_as_existing():
    assert rl.classify_response(404, {"status": 1, "status_verbose": "product found"})["status"] == rl.STATUS_UNCONFIRMED


def test_the_url_asks_only_for_the_fields_the_check_needs():
    assert rl.api_url("0000000000000") == "https://world.openfoodfacts.org/api/v2/product/0000000000000.json?fields=code,status,status_verbose,last_modified_t"
    assert "product_name" not in rl.api_url("1") and "ingredients" not in rl.api_url("1")


# --- which products to ask about (DuckDB, real products) -------------------------------------------------------------------------------------

duckdb = pytest.importorskip("duckdb")
NOW = int(dt.datetime(2026, 10, 20, 12, 0, tzinfo=UTC).timestamp())
MAX_LM = max(r["lm_c"] for r in SLICE["pairs"])
LEFT = [r["code"] for r in SLICE["only_a"]]


def _con(checks=(), lm_override=None):
    con = duckdb.connect()
    con.execute("create table silver (code varchar, lm bigint)")
    con.execute("create table snap (code varchar)")
    con.execute("create table checked (code varchar, status varchar, checked_at bigint)")
    for r in SLICE["pairs"]:
        con.execute("insert into silver values (?, ?)", [r["code"], r["lm_c"]])
        con.execute("insert into snap values (?)", [r["code"]])
    for r in SLICE["only_a"]:
        con.execute("insert into silver values (?, ?)", [r["code"], (lm_override or {}).get(r["code"], r["lm"])])
    for r in SLICE["only_c"]:
        con.execute("insert into snap values (?)", [r["code"]])
    for c in checks:
        con.execute("insert into checked values (?, ?, ?)", list(c))
    return con


def _candidates(con):
    return [c for c, _ in con.execute(rl.candidates_sql(MAX_LM, NOW)).fetchall()]


def test_products_missing_from_the_snapshot_are_candidates_and_products_in_it_are_not():
    got = _candidates(_con())
    assert sorted(got) == sorted(LEFT) and len(got) == 12


def test_a_product_edited_after_the_snapshots_newest_edit_is_not_a_candidate_yet():
    code = LEFT[0]
    assert code not in _candidates(_con(lm_override={code: MAX_LM + 3600}))
    assert code in _candidates(_con(lm_override={code: MAX_LM}))                        # exactly at the cut: the snapshot should hold it


def test_an_answer_from_the_last_two_weeks_is_not_asked_again_and_an_older_one_is():
    code = LEFT[1]
    assert code not in _candidates(_con([(code, rl.STATUS_EXISTS, NOW - 3 * 86400)]))
    assert code not in _candidates(_con([(code, rl.STATUS_UNCONFIRMED, NOW - 3 * 86400)]))
    assert code in _candidates(_con([(code, rl.STATUS_EXISTS, NOW - 30 * 86400)]))


def test_a_terminal_answer_stands_until_the_product_changes_again():
    code = LEFT[2]
    lm = next(r["lm"] for r in SLICE["only_a"] if r["code"] == code)
    for terminal in rl.TERMINAL:
        assert code not in _candidates(_con([(code, terminal, lm + 1)]))                 # answered after the product's newest version we hold: settled
        assert code in _candidates(_con([(code, terminal, lm - 1)]))                     # answered BEFORE it: the product changed since, ask again


def test_the_candidates_query_is_stable_in_order():
    con = _con()
    assert _candidates(con) == sorted(_candidates(con))


# --- the table and its latest-status view -----------------------------------------------------------------------------------------------------

def test_the_table_definition_reads_back_and_matches_the_latest_status_view_columns():
    sql = rl.ddl()
    assert "workspace.packsense_silver.silver_existence_check" in sql and "USING DELTA" in sql
    assert rl.ddl_columns(sql) == ["code", "checked_at", "status", "detail", "evidence_source", "snapshot_sha", "job_run_id"]


def test_the_latest_row_per_code_wins_and_an_api_answer_beats_a_snapshot_row_at_the_same_time():
    con = duckdb.connect()
    con.execute("create table t (code varchar, checked_at timestamp, status varchar, detail varchar, evidence_source varchar, snapshot_sha varchar, job_run_id varchar)")
    rows = [("a", "2026-10-13 06:00:00", rl.STATUS_PRESENT, "", "snapshot"), ("a", "2026-10-20 06:00:00", rl.STATUS_NOT_FOUND, "", "off_api_v2"),
            ("b", "2026-10-20 06:00:00", rl.STATUS_PRESENT, "", "snapshot"), ("b", "2026-10-20 06:00:00", rl.STATUS_EXISTS, "", "off_api_v2"),
            ("c", "2026-10-20 06:00:00", rl.STATUS_PRESENT, "", "snapshot")]
    for code, ts, status, detail, ev in rows:
        con.execute("insert into t values (?, ?, ?, ?, ?, 'sha', 'run')", [code, ts, status, detail, ev])
    got = {r[0]: r[1] for r in con.execute(rl.latest_status_sql("t")).fetchall()}
    assert got == {"a": rl.STATUS_NOT_FOUND, "b": rl.STATUS_EXISTS, "c": rl.STATUS_PRESENT}


# --- the files between Databricks and Airflow -------------------------------------------------------------------------------------------------

def test_paths_and_result_lines():
    assert rl.candidates_path("2026-10-19") == "reconcile/candidates/2026-10-19.json"
    assert rl.results_path(dt.date(2026, 10, 19)) == "reconcile/results/2026-10-19.jsonl"
    line = rl.result_line("3614790000309", _classify("3614790000309"), 404, dt.datetime(2026, 10, 20, 17, 30, 5, tzinfo=UTC))
    assert line == {"code": "3614790000309", "status": "moved_other_type", "detail": "beauty", "http": 404, "checked_at": "2026-10-20T17:30:05Z"}


def test_a_results_file_round_trips_and_a_bad_line_refuses_the_whole_file():
    lines = [rl.result_line(c, _classify(c), API[c]["http"], dt.datetime(2026, 10, 20, 17, 0, tzinfo=UTC)) for c in list(API)[:5]]
    text = "\n".join(json.dumps(x) for x in lines) + "\n"
    assert rl.parse_results(text) == lines
    for bad in ("not json", json.dumps({"code": "1", "status": "gone", "checked_at": "x"}), json.dumps({"status": "unverified", "checked_at": "x"})):
        with pytest.raises(ValueError):
            rl.parse_results(text + bad + "\n")


# --- the jobs and notebooks ----------------------------------------------------------------------------------------------------------------------

def _jobs():
    import yaml
    res = HERE.parents[1] / "p3_delivery" / "resources" / "reconcile_job.yml"
    return res, yaml.safe_load(res.read_text(encoding="utf-8"))["resources"]["jobs"]


def test_the_two_jobs_run_weekly_on_different_days_without_retry_and_pass_no_secret_as_a_parameter():
    res, jobs = _jobs()
    assert set(jobs) == {"reconcile_candidates", "reconcile_load", "reconcile_lookup", "egress_check"}
    assert jobs["reconcile_candidates"]["schedule"]["quartz_cron_expression"] == "0 0 7 ? * TUE"      # the day after the Monday snapshot job
    assert jobs["reconcile_load"]["schedule"]["quartz_cron_expression"] == "0 0 7 ? * THU"            # two days for the laptop's DAG in between
    assert jobs["reconcile_lookup"]["schedule"]["quartz_cron_expression"] == "0 0 10 * * ?"           # daily, after the 06:45 to 08:45 UTC window
    assert jobs["egress_check"]["schedule"]["quartz_cron_expression"] == "0 0 5 1 * ?"                 # monthly
    for job in jobs.values():
        assert job["max_concurrent_runs"] == 1 and job["schedule"]["pause_status"] == "UNPAUSED"
        (task,) = job["tasks"]
        assert task["disable_auto_optimization"] is True
        assert (res.parent / task["notebook_task"]["notebook_path"]).resolve().is_file()
        for name in task["notebook_task"]["base_parameters"]:
            assert not any(w in name.lower() for w in ("token", "password", "key", "hmac")), name


def test_the_candidate_notebook_reads_only_two_snapshot_columns_and_bounds_the_read():
    text = (HERE.parent / "notebooks" / "reconcile_candidates.py").read_text(encoding="utf-8")
    assert "select code, max(last_modified_t) as lm from read_parquet" in text
    for forbidden in ("data_quality", "editors", "creator", "last_editor", "informers"):
        assert forbidden not in text
    assert "ByteGuard" in text and "BYTE_GUARD = 600_000_000" in text
    assert "candidates_sql" in text and "latest_status_sql" in text and "evidence_source = '{lib.EVIDENCE_API}'" in text   # API answers only decide what is settled
    assert "os.replace" in text                                                                                     # the candidate file appears whole or not at all


def test_the_loader_refuses_a_bad_file_whole_and_replaces_a_files_rows_instead_of_doubling_them():
    text = (HERE.parent / "notebooks" / "reconcile_load.py").read_text(encoding="utf-8")
    assert "lib.parse_results" in text and "delete from" in text and "results:{name}" in text
    assert "os.remove" not in text and "shutil.rmtree" not in text                  # nothing is deleted from the landing volume


def test_the_new_table_is_classified_and_has_a_definition():
    import yaml
    spec = yaml.safe_load((HERE.parents[1] / "p5_governance" / "classification.yml").read_text(encoding="utf-8"))
    names = {t["name"]: t for t in spec["tables"]}
    t = names["workspace.packsense_silver.silver_existence_check"]
    assert t["class"] == "public" and {"evidence_source", "snapshot_sha", "job_run_id"} <= set(t["columns"])
