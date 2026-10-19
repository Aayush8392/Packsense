"""The Databricks side of the policies file: run SQL on the SQL warehouse as the admin, read what is attached to each table, create the
objects and attach the filters and masks. `run` is injected (a function sql -> rows), so the comparison logic is tested with fakes."""
from __future__ import annotations

import os
import time

import grants_lib as gl
import grants_live as glive
import policies_lib as pol

DEFAULT_WAREHOUSE = "c9e35ecf0a03295d"      # the Serverless Starter 2X-Small: an address, not a secret


def make_runner(w, warehouse: str | None = None):
    wh = warehouse or os.environ.get("DBT_HTTP_PATH", DEFAULT_WAREHOUSE).rstrip("/").split("/")[-1]

    def run(statement: str) -> list[list[str]]:
        r = w.statement_execution.execute_statement(warehouse_id=wh, statement=statement, wait_timeout="50s")
        while r.status.state.value in ("PENDING", "RUNNING"):
            time.sleep(2)
            r = w.statement_execution.get_statement(r.statement_id)
        if r.status.state.value != "SUCCEEDED":
            raise RuntimeError(f"{r.status.state.value}: {r.status.error}")
        return (r.result.data_array if r.result and r.result.data_array else [])

    return run


def read_attachments(run, spec: dict) -> dict[str, dict | None]:
    live: dict[str, dict | None] = {}
    for table in sorted(pol.expected_attachments(spec)):
        try:
            live[table] = pol.parse_describe(run(f"DESCRIBE EXTENDED {table}"))
        except RuntimeError as e:
            if "TABLE_OR_VIEW_NOT_FOUND" in str(e) or "cannot be found" in str(e):
                live[table] = None
            else:
                raise
    return live


def read_access(run, spec: dict) -> set[tuple[str, str]]:
    try:
        return {(r[0], r[1]) for r in run(f"SELECT principal, market FROM {pol.fq(spec, spec['access_table'])}")}
    except RuntimeError as e:
        if "TABLE_OR_VIEW_NOT_FOUND" in str(e) or "cannot be found" in str(e):
            return set()
        raise


def compare(w, spec: dict, grants_spec: dict, environ=os.environ, run=None) -> dict:
    """Resolve the roles exactly as the grants file does, read the access table and what is attached to every listed table."""
    run = run or make_runner(w)
    ids, names = glive.resolve_principals(w, grants_spec, environ)
    unresolved = sorted(r for r in (spec.get("access") or {}) if ids.get(r) is None)
    want, _ = pol.expected_access(spec, ids)
    have = read_access(run, spec)
    missing, extra = pol.compare_access(want, have)
    findings = pol.compare_attachments(spec, read_attachments(run, spec))
    return {"names": names, "unresolved": unresolved, "missing_access": missing, "extra_access": extra, "findings": findings,
            "n_want": len(want), "n_have": len(have),
            "clean": not (unresolved or missing or extra or findings)}


def describe(r: dict) -> str:
    n = r["names"]
    lines = [f"access table: expected {r['n_want']} rows, live {r['n_have']}"]
    lines += [f"SKIPPED role {x}: could not be resolved (dead token or missing service principal)" for x in r["unresolved"]]
    lines += ["MISSING ACCESS " + gl_pretty(m, n) for m in r["missing_access"]]
    lines += ["EXTRA ACCESS   " + gl_pretty(e, n) + " (not in the file; left alone)" for e in r["extra_access"]]
    lines += r["findings"]
    if r["clean"]:
        lines.append("live row filters, masks and access table equal the policies file")
    return "\n".join(lines)


def gl_pretty(item: tuple, names: dict[str, str]) -> str:
    return glive.pretty(item, names)


def apply(w, spec: dict, grants_spec: dict, environ=os.environ, run=None, only: str = "all", masks: bool = True) -> list[str]:
    """Create or refresh the access table and the functions, then attach filters and masks. `only` = dev | prod | all limits the ATTACH step
    to the tables of that environment (a table of the dev gold and silver schemas contains 'dev'). Returns the statements run (for printing).
    ORDER MATTERS: the access rows exist before any mask is attached, otherwise the pipeline itself would read masked columns."""
    run = run or make_runner(w)
    ids, _ = glive.resolve_principals(w, grants_spec, environ)
    want, skipped = pol.expected_access(spec, ids)
    if skipped:
        raise RuntimeError(f"cannot apply: these roles could not be resolved: {skipped}")
    done = []
    for s in pol.sql_objects(spec, want):
        run(s)
        done.append(s)
    for s in pol.attach_plan(spec, read_attachments(run, spec)):
        if not masks and "MASK" in s:
            continue
        is_dev = "_dev_" in s
        if only == "all" or (only == "dev") == is_dev:
            run(s)
            done.append(s)
    return done


__all__ = ["compare", "describe", "apply", "make_runner", "gl", "gl_pretty"]
