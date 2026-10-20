"""Deletion reconciliation (P9, roadmap Phase A item 3): does a product we hold still exist in OFF's food database?

How it works. Silver holds every product we ever saw. The newest weekly snapshot of OFF's dataset (see snapshot_lib.py) says which products OFF's food
database holds NOW, for the price of one column read. A silver product that is missing from it, and whose newest version we hold is not newer than the
snapshot (so the snapshot should have it), is a CANDIDATE. Only candidates are looked up in OFF's API (one slow request each, on Airflow), and the answer
is recorded in `silver_existence_check`. `product_status` (gold) reads the latest row per product.

What the real API answers (measured 2026-10-20, fixtures/off_api_responses.json): a product OFF has is HTTP 200 with status 1; one it does not have is
HTTP 404 with status 0 and `product not found`; and, unexpectedly often (4 of 6 products that had left a weekly snapshot), HTTP 404 with status 0 and
`product found with a different product type: beauty` (or `product`): OFF moved it to a sister database. That is not a deletion and not 'still in our
catalogue', so it has its own status. Nothing is guessed: an answer this module does not recognise is `unconfirmed`.
"""
from __future__ import annotations

import datetime as dt

# --- what a product's existence check can say ---------------------------------------------------------------------------------------------
STATUS_PRESENT = "present_in_snapshot"           # the newest snapshot holds it (no API call was needed)
STATUS_EXISTS = "confirmed_exists"               # not in the snapshot, but OFF's API has it (a lag or a gap in the snapshot)
STATUS_NOT_FOUND = "confirmed_not_found"         # OFF's API says it does not exist (deleted, or a merged barcode)
STATUS_MOVED = "moved_other_type"                # OFF's API has it as another product type (beauty, general product): not in the FOOD database any more
STATUS_INVALID = "invalid_code"                  # OFF says the barcode is not a valid code
STATUS_UNCONFIRMED = "unconfirmed"               # the API could not give a clear answer (rate limit, server error, timeout, an answer not recognised)
STATUS_UNVERIFIED = "unverified"                 # never checked
STATUSES = (STATUS_PRESENT, STATUS_EXISTS, STATUS_NOT_FOUND, STATUS_MOVED, STATUS_INVALID, STATUS_UNCONFIRMED, STATUS_UNVERIFIED)
TERMINAL = (STATUS_NOT_FOUND, STATUS_MOVED, STATUS_INVALID)   # not asked again until the product changes in our feed again

EVIDENCE_SNAPSHOT = "snapshot"
EVIDENCE_API = "off_api_v2"
RETRYABLE_HTTP = (429, 500, 502, 503, 504)
API_FIELDS = "code,status,status_verbose,last_modified_t"
API_PAUSE_SECONDS = 3.0                          # OFF answers HTTP 429 to rapid sequential lookups (measured in the verification phase)

TABLE = "silver_existence_check"
DEFAULT_SCHEMA = "workspace.packsense_silver"


def api_url(code: str) -> str:
    return f"https://world.openfoodfacts.org/api/v2/product/{code}.json?fields={API_FIELDS}"


def classify_response(http_status: int | None, body: dict | None, error: str | None = None) -> dict:
    """The final answer for one lookup: {'status', 'detail'}. `http_status` None with an `error` means the request itself failed (timeout, network).
    A rate limit or server error is `unconfirmed` here; retrying is the caller's job and only the LAST answer is classified."""
    if error is not None or http_status is None:
        return {"status": STATUS_UNCONFIRMED, "detail": f"request failed: {(error or 'no response')[:120]}"}
    if http_status in RETRYABLE_HTTP:
        return {"status": STATUS_UNCONFIRMED, "detail": f"http {http_status}"}
    if not isinstance(body, dict) or "status" not in body:
        return {"status": STATUS_UNCONFIRMED, "detail": f"unrecognised answer, http {http_status}"}
    verbose = str(body.get("status_verbose") or "")
    if body["status"] == 1 and http_status == 200:
        return {"status": STATUS_EXISTS, "detail": ""}
    if body["status"] == 0:
        low = verbose.lower()
        if low.startswith("product found with a different product type"):
            return {"status": STATUS_MOVED, "detail": verbose.split(":", 1)[1].strip() if ":" in verbose else ""}
        if low == "product not found":
            return {"status": STATUS_NOT_FOUND, "detail": ""}
        if "no code or invalid code" in low:
            return {"status": STATUS_INVALID, "detail": ""}
    return {"status": STATUS_UNCONFIRMED, "detail": f"unrecognised answer: status {body.get('status')}, '{verbose[:80]}', http {http_status}"}


# --- which products to ask about ----------------------------------------------------------------------------------------------------------

def candidates_sql(snapshot_max_lm: int, now_epoch: int, recheck_days: int = 14) -> str:
    """SQL over three tables: silver(code, lm), snap(code) and checked(code, status, checked_at) where `checked` holds the LATEST check per code
    (epoch seconds). A candidate is a silver product that is missing from the snapshot, whose newest version is not newer than the snapshot's newest
    edit (a newer one may simply not be in the snapshot yet), and that is not already settled: not a terminal answer given after the product's last
    change, and not any answer given in the last `recheck_days` days."""
    terminal = ", ".join(f"'{s}'" for s in TERMINAL)
    return (f"select s.code, s.lm from silver s where s.code not in (select code from snap) and s.lm <= {int(snapshot_max_lm)} "
            f"and not exists (select 1 from checked c where c.code = s.code and ((c.status in ({terminal}) and c.checked_at > s.lm) "
            f"or c.checked_at > {int(now_epoch)} - {int(recheck_days)} * 86400)) order by s.code")


# --- the table ---------------------------------------------------------------------------------------------------------------------------

def ddl(schema: str = DEFAULT_SCHEMA) -> str:
    return (f"CREATE TABLE IF NOT EXISTS {schema}.{TABLE} (code STRING, checked_at TIMESTAMP, status STRING, detail STRING, "
            f"evidence_source STRING, snapshot_sha STRING, job_run_id STRING) USING DELTA")


def ddl_columns(sql: str) -> list[str]:
    body = sql[sql.index("(") + 1: sql.rindex(")")]
    return [p.split()[0] for p in body.split(",") if p.strip()]


def latest_status_sql(table: str) -> str:
    """One row per code: its most recent check (ties broken by the more informative evidence: an API answer over the snapshot)."""
    return (f"select code, status, detail, evidence_source, checked_at, snapshot_sha from (select *, row_number() over (partition by code "
            f"order by checked_at desc, case evidence_source when '{EVIDENCE_API}' then 0 else 1 end) as rn from {table}) where rn = 1")


# --- the files that travel between Databricks and Airflow ---------------------------------------------------------------------------------

def candidates_path(snapshot_date: dt.date | str) -> str:
    return f"reconcile/candidates/{snapshot_date}.json"


def results_path(snapshot_date: dt.date | str) -> str:
    return f"reconcile/results/{snapshot_date}.jsonl"


def result_line(code: str, outcome: dict, http_status: int | None, checked_at: dt.datetime) -> dict:
    """One line of the results file (JSON lines): the answer for one code."""
    return {"code": code, "status": outcome["status"], "detail": outcome["detail"], "http": http_status,
            "checked_at": checked_at.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def parse_results(text: str) -> list[dict]:
    """Read a results file. A line that is not valid JSON, lacks a field or names an unknown status is refused (the whole file), not skipped."""
    import json
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"results line {n} is not JSON: {e}") from e
        for field in ("code", "status", "checked_at"):
            if not row.get(field):
                raise ValueError(f"results line {n} has no {field}")
        if row["status"] not in STATUSES:
            raise ValueError(f"results line {n}: unknown status {row['status']!r}")
        out.append(row)
    return out
