"""The pipeline-health collector (roadmap Phase B item 9: the capacity panel and dependency health).

Once a day a small job owned by the admin (`packsense-health`; no service principal, see below) writes operating facts about the pipeline itself into one long table,
`workspace.packsense_health.health_metric_daily` (one row per UTC day, subject and metric), from two sources that need no access to any product data:

  * job runs   Databricks' system tables `system.lakeflow.jobs` and `job_run_timeline` (runs, failed runs, longest run, hours since the last success, per production job);
  * services   one light request to every outside service the pipeline needs (the same list as the monthly egress check, `egress_lib`).

Why the admin and not a dedicated principal: Databricks Free Edition lets nobody grant the system tables to another identity (`GRANT` on the `system` catalog needs
MANAGE, which not even the admin holds; measured 2026-10-21), so a narrow principal cannot read them. The job is therefore admin-owned like `packsense-policy`, and reaches
production only when the admin deploys it from the laptop.

Storage size is NOT collected: `system.storage.table_metrics_history` is empty on Free Edition (measured 2026-10-21, 0 rows for the whole metastore) and `DESCRIBE DETAIL`
needs SELECT on the table, which this job should not need on bronze or silver. A size line needs another source and a decision (the billing storage unit is a candidate).

Why a long table: new metrics need no schema change, and the public export (p6_serving/export_spec.yml) picks the rows it may show.
Nothing here is personal; billing figures are deliberately NOT collected (a decision of 2026-10-21: raw quota and spend stay off the public site).
Pure Python and SQL text: the notebook runs the SQL and passes the rows in, so every rule is testable without Databricks.
"""
from __future__ import annotations

import datetime as dt

SCHEMA = "workspace.packsense_health"
TABLE = "health_metric_daily"
FULL_TABLE = f"{SCHEMA}.{TABLE}"
COLUMNS = ("metric_date", "subject", "metric", "value", "unit", "detail", "collected_at", "job_run_id")

# The production jobs the panel reports (names as in the Jobs list). A dev copy is named "[dev ...] packsense-..." and never matches.
JOB_NAMES = (
    "packsense-bronze-load", "packsense-gold-build", "packsense-publish", "packsense-archive", "packsense-policy",
    "packsense-snapshots", "packsense-reconcile-candidates", "packsense-reconcile-load", "packsense-reconcile-lookup",
    "packsense-egress-check", "packsense-health", "packsense-release",
)
# Jobs the bundles define that the panel deliberately leaves out (the per-principal policy sub-jobs run inside packsense-policy).
JOB_NAMES_NOT_REPORTED = (
    "packsense-policy-gold", "packsense-policy-gold-dev", "packsense-policy-deployer", "packsense-policy-deployer-dev", "packsense-policy-publish",
)
LOOKBACK_DAYS = 3          # each run refreshes the last three UTC days of job rows (system tables lag by hours)
SUCCESS_WINDOW_DAYS = 30   # "hours since the last success" looks this far back


def ddl() -> str:
    return f"""CREATE TABLE IF NOT EXISTS {FULL_TABLE} (
  metric_date DATE,
  subject STRING,
  metric STRING,
  value DOUBLE,
  unit STRING,
  detail STRING,
  collected_at TIMESTAMP,
  job_run_id STRING
) USING DELTA"""


def ddl_columns(sql: str) -> list[str]:
    body = sql[sql.index("(") + 1: sql.rindex(")")]
    return [p.split()[0] for p in body.split(",") if p.strip()]


def _names_sql() -> str:
    return ", ".join("'" + n.replace("'", "''") + "'" for n in JOB_NAMES)


def job_runs_sql(today: dt.date) -> str:
    """One row per (UTC start day, job name): runs finished, runs not SUCCEEDED, longest run in seconds.

    A run is one `run_id`; its start is the earliest period start and its end the latest period end (the table holds time slices of a run, and its
    `run_duration_seconds` is empty for these rows, measured 2026-10-21). A run with no final `result_state` yet is still running and is not counted.
    """
    first = today - dt.timedelta(days=LOOKBACK_DAYS - 1)
    return f"""
with j as (select job_id, max_by(name, change_time) as name from system.lakeflow.jobs group by job_id),
r as (
  select job_id, run_id, min(period_start_time) as s, max(period_end_time) as e, max(result_state) as state
  from system.lakeflow.job_run_timeline
  where period_start_time >= timestamp'{first.isoformat()}' and run_type in ('JOB_RUN', 'WORKFLOW_RUN')
  group by job_id, run_id
)
select cast(r.s as date) as metric_date, j.name as subject,
       count(*) as runs,
       sum(case when r.state = 'SUCCEEDED' then 0 else 1 end) as failed_runs,
       max(unix_timestamp(r.e) - unix_timestamp(r.s)) as max_duration_seconds
from r join j on r.job_id = j.job_id
where r.state is not null and j.name in ({_names_sql()})
group by 1, 2
""".strip()


def last_success_sql(today: dt.date) -> str:
    """Per job: the end of its newest SUCCEEDED run in the last SUCCESS_WINDOW_DAYS days."""
    first = today - dt.timedelta(days=SUCCESS_WINDOW_DAYS)
    return f"""
with j as (select job_id, max_by(name, change_time) as name from system.lakeflow.jobs group by job_id),
r as (
  select job_id, run_id, max(period_end_time) as e, max(result_state) as state
  from system.lakeflow.job_run_timeline
  where period_start_time >= timestamp'{first.isoformat()}' and run_type in ('JOB_RUN', 'WORKFLOW_RUN')
  group by job_id, run_id
)
select j.name as subject, max(r.e) as last_success
from r join j on r.job_id = j.job_id
where r.state = 'SUCCEEDED' and j.name in ({_names_sql()})
group by 1
""".strip()


def _num(v) -> float | None:
    return None if v is None else float(v)


def job_rows(rows, collected_at, run_id) -> list[dict]:
    """From the job_runs_sql result: rows of (metric_date, subject, runs, failed_runs, max_duration_seconds)."""
    out = []
    for metric_date, subject, runs, failed, longest in rows:
        for metric, value, unit in (("runs", runs, "runs"), ("failed_runs", failed, "runs"), ("max_duration_seconds", longest, "seconds")):
            out.append({"metric_date": metric_date, "subject": subject, "metric": metric, "value": _num(value), "unit": unit, "detail": None,
                        "collected_at": collected_at, "job_run_id": run_id})
    return out


def success_age_rows(rows, today: dt.date, now: dt.datetime, collected_at, run_id) -> list[dict]:
    """Hours since each job's last success; a job with none in the window gets no row (the page shows it as missing)."""
    out = []
    for subject, last in rows:
        if last is None:
            continue
        hours = (now - last.replace(tzinfo=None)).total_seconds() / 3600 if getattr(last, "tzinfo", None) else (now - last).total_seconds() / 3600
        out.append({"metric_date": today, "subject": subject, "metric": "hours_since_last_success", "value": round(max(hours, 0.0), 2), "unit": "hours",
                    "detail": None, "collected_at": collected_at, "job_run_id": run_id})
    return out


def service_rows(results, today: dt.date, collected_at, run_id) -> list[dict]:
    """From egress_lib.check_all(): one `reachable` row per service (1 or 0) and its response time; the detail is the short reason."""
    out = []
    for r in results:
        out.append({"metric_date": today, "subject": r["service"], "metric": "reachable", "value": 1.0 if r["ok"] else 0.0, "unit": "flag",
                    "detail": str(r["detail"])[:120], "collected_at": collected_at, "job_run_id": run_id})
        out.append({"metric_date": today, "subject": r["service"], "metric": "response_seconds", "value": _num(r["seconds"]), "unit": "seconds",
                    "detail": None, "collected_at": collected_at, "job_run_id": run_id})
    return out


def merge_sql(view: str) -> str:
    """Replace the day's rows for a (day, subject, metric) key and add new ones: a rerun never duplicates."""
    return f"""MERGE INTO {FULL_TABLE} t USING {view} s
ON t.metric_date = s.metric_date AND t.subject = s.subject AND t.metric = s.metric
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *"""


def failures(service_results) -> list[str]:
    """Names of the services that were not reachable (the job pings /fail with these)."""
    return [r["service"] for r in service_results if not r["ok"]]
