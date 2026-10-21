"""p9_operations/health_lib.py on REAL output of the collector's queries (tests/fixtures/health_real.json, taken 2026-10-21 from the system tables and the live
service checks): the row shapes, the merge key, the hours-since-success arithmetic, and the wiring of the health bundle."""
import datetime as dt
import json
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "p9_operations"))
import health_lib as lib  # noqa: E402

REAL = json.loads((HERE / "fixtures" / "health_real.json").read_text(encoding="utf-8"))
NOW = dt.datetime.fromisoformat(REAL["now"])
TODAY = NOW.date()
STAMP = NOW.replace(microsecond=0)
JOBS = [(dt.date.fromisoformat(d), s, r, f, m) for d, s, r, f, m in REAL["queries"]["jobs"]]
LAST = [(s, dt.datetime.fromisoformat(t)) for s, t in REAL["queries"]["last"]]

BUNDLE = yaml.safe_load((ROOT / "p9_operations" / "health" / "databricks.yml").read_text(encoding="utf-8"))
JOB = yaml.safe_load((ROOT / "p9_operations" / "health" / "resources" / "health_job.yml").read_text(encoding="utf-8"))["resources"]["jobs"]["health_collect"]
GRANTS = yaml.safe_load((ROOT / "p5_governance" / "grants.yml").read_text(encoding="utf-8"))
NOTEBOOK = ROOT / "p9_operations" / "notebooks" / "health_collect.py"


def build():
    return (lib.job_rows(JOBS, STAMP, "fixture") + lib.success_age_rows(LAST, TODAY, NOW, STAMP, "fixture")
            + lib.service_rows(REAL["services"], TODAY, STAMP, "fixture"))


def test_the_real_rows_build_exactly_the_rows_the_fixture_holds():
    got = [{k: (v.isoformat() if isinstance(v, (dt.date, dt.datetime)) else v) for k, v in r.items()} for r in build()]
    assert got == REAL["rows"]


def test_every_row_has_exactly_the_table_columns_and_a_unique_merge_key():
    rows = build()
    assert all(tuple(r) == lib.COLUMNS for r in rows)
    keys = [(r["metric_date"], r["subject"], r["metric"]) for r in rows]
    assert len(keys) == len(set(keys)), "the MERGE key (day, subject, metric) must be unique, or MERGE refuses the batch"


def test_only_production_jobs_are_reported_and_the_dev_copies_never_match():
    assert {r["subject"] for r in lib.job_rows(JOBS, STAMP, "x")} <= set(lib.JOB_NAMES)
    assert not [n for n in lib.JOB_NAMES if n.startswith("[")]
    assert "[dev" not in lib._names_sql()


def test_the_hours_since_last_success_is_plain_arithmetic():
    last = dt.datetime(2026, 10, 21, 6, 30)
    (row,) = lib.success_age_rows([("packsense-gold-build", last)], TODAY, dt.datetime(2026, 10, 21, 9, 0), STAMP, "x")
    assert row["value"] == 2.5 and row["unit"] == "hours" and row["metric"] == "hours_since_last_success"
    assert lib.success_age_rows([("packsense-publish", None)], TODAY, NOW, STAMP, "x") == []     # no success in the window: no row, not a made-up number
    (neg,) = lib.success_age_rows([("j", dt.datetime(2026, 10, 21, 10, 0))], TODAY, dt.datetime(2026, 10, 21, 9, 0), STAMP, "x")
    assert neg["value"] == 0.0                                                                         # a clock skew never gives a negative age


def test_a_service_that_did_not_answer_is_a_zero_and_is_named_for_the_alert():
    results = [{"service": "A (x)", "ok": True, "detail": "HTTP 200", "seconds": 0.4}, {"service": "B (y)", "ok": False, "detail": "not reachable: timeout", "seconds": 20.0}]
    rows = lib.service_rows(results, TODAY, STAMP, "x")
    assert [(r["subject"], r["metric"], r["value"]) for r in rows] == [("A (x)", "reachable", 1.0), ("A (x)", "response_seconds", 0.4),
                                                                       ("B (y)", "reachable", 0.0), ("B (y)", "response_seconds", 20.0)]
    assert lib.failures(results) == ["B (y)"]


def test_the_sql_reads_only_the_two_system_tables_it_needs_and_never_billing_or_product_data():
    text = lib.job_runs_sql(TODAY) + lib.last_success_sql(TODAY)
    assert set(re.findall(r"system\.[a-z_]+\.[a-z_]+", text)) == {"system.lakeflow.jobs", "system.lakeflow.job_run_timeline"}
    assert "billing" not in text and "workspace." not in text


def test_the_lookback_window_is_in_the_job_query():
    assert f"timestamp'{(TODAY - dt.timedelta(days=lib.LOOKBACK_DAYS - 1)).isoformat()}'" in lib.job_runs_sql(TODAY)


def test_the_ddl_matches_the_column_list_and_the_merge_uses_the_key():
    assert tuple(lib.ddl_columns(lib.ddl())) == lib.COLUMNS
    sql = lib.merge_sql("v")
    assert "t.metric_date = s.metric_date AND t.subject = s.subject AND t.metric = s.metric" in sql and "UPDATE SET *" in sql


# --- the wiring of the bundle --------------------------------------------------------------------------------------------------

def test_every_production_job_of_the_repo_is_reported_or_deliberately_left_out():
    names = set()
    for path in [*ROOT.glob("p[0-9]_*/resources/*.yml"), *ROOT.glob("p[0-9]_*/*/resources/*.yml")]:      # the bundles' job files (not build output or dependencies)
        names |= set(re.findall(r"^\s+name:\s+(packsense-[a-z-]+)\s*$", path.read_text(encoding="utf-8"), re.M))
    names -= {"packsense-policy-probe"}
    assert names - set(lib.JOB_NAMES) - set(lib.JOB_NAMES_NOT_REPORTED) - {"packsense-health"} == set(), "a job exists that the panel neither reports nor excludes"
    assert set(lib.JOB_NAMES) - names == set(), "the panel reports a job no bundle defines"


def test_the_job_is_admin_owned_so_it_has_no_run_as_and_no_principal_in_the_bundle():
    assert "run_as" not in JOB and "permissions" not in BUNDLE
    text = (ROOT / "p9_operations" / "health" / "databricks.yml").read_text(encoding="utf-8") + (ROOT / "p9_operations" / "health" / "resources" / "health_job.yml").read_text(encoding="utf-8")
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text), "no client id may remain in the health bundle"


def test_the_notebook_exists_is_not_retried_and_takes_no_secret_as_a_parameter():
    task = JOB["tasks"][0]
    assert (ROOT / "p9_operations" / "health" / "resources" / task["notebook_task"]["notebook_path"]).resolve() == NOTEBOOK.resolve()
    assert task["disable_auto_optimization"] is True
    assert not [k for k in task["notebook_task"]["base_parameters"] if re.search(r"token|secret|key|password", k, re.I)]
    assert 'dbutils.secrets.get(SCOPE, "healthchecks_health_ping_url")' in NOTEBOOK.read_text(encoding="utf-8")


def test_the_job_runs_after_the_gold_build_and_before_the_publish():
    def minutes(cron):
        sec, minute, hour = cron.split()[:3]
        return int(hour) * 60 + int(minute)
    publish = yaml.safe_load((ROOT / "p6_serving" / "databricks.yml").read_text(encoding="utf-8"))["variables"]["publish_cron"]["default"]
    assert 8 * 60 + 30 <= minutes(BUNDLE["variables"]["health_cron"]["default"]) < minutes(publish)


def test_the_notebook_does_not_create_tables_and_exit_is_outside_the_try():
    text = NOTEBOOK.read_text(encoding="utf-8")
    assert "CREATE TABLE" not in text and "create table" not in text.lower().replace("cannot create tables", "")
    tail = text[text.index("except Exception as e:"):]
    assert "dbutils.notebook.exit(summary)" in tail.split("# COMMAND ----------", 1)[1]


def test_the_setup_script_has_no_principal_or_system_grant_commands_except_the_cleanup():
    text = (ROOT / "p9_operations" / "bootstrap" / "setup_health.py").read_text(encoding="utf-8")
    assert "grant-system" not in text and "create-principal" not in text and "w.grants.update" not in text
    assert "remove-principal" in text and "delete_acl" in text      # the leftover principal and its scope ACL are cleaned up, not left to show as an extra grant


def test_grants_file_gives_the_health_job_nothing_and_the_publish_job_one_table():
    assert "packsense-health" not in GRANTS["principals"] and "system_grants" not in GRANTS
    health = {s["name"]: s["grants"] for s in GRANTS["securables"] if s["name"].startswith("workspace.packsense_health")}
    assert health == {"workspace.packsense_health": {"packsense-publish": ["USE_SCHEMA"]},
                      "workspace.packsense_health.health_metric_daily": {"packsense-publish": ["SELECT"]}}
    assert GRANTS["secret_scopes"]["packsense_health"] == {"admin": "MANAGE"}
