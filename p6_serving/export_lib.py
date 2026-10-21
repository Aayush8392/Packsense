"""p6_serving/export_lib.py: turns gold rows into the files of the public site, behind the exit function and the licence gate.

Pure Python (rows in, files out); the Databricks notebook only reads the tables listed in export_spec.yml and calls build_release().
What it guarantees, each with a test:
  * only the columns named in export_spec.yml leave (a missing or extra column is an error), and none is classified personal or internal;
  * text columns go through the project's exit function (silver_lib.egress.prepare_for_export: scrub patterns, residue scan, refusal);
  * a count of 1 to 4 in a listed count column is blanked and counted (small-number suppression);
  * every file is rendered deterministically (sorted rows, LF, UTF-8) with its sha256 in release_manifest.json;
  * the licence gate (p5_governance/licence_gate.py) runs on the RENDERED folder as the last step, and a violation raises: nothing is published.

Why the exit function sees no contributor-name list here: the only names it could replace are contributor names of 8+ characters that are not
ordinary words (a word in the text of 10+ products). Every exported brand is a brand with at least `ordinary_word_min_products` products, so every
word of its name is in the text of that many products and is ordinary by the exit function's own definition; the list could change nothing. A test
keeps that premise true (the ranking floor stays at or above the contract's threshold). What the exit does here is the pattern scrub and the scan.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "p2_lakehouse"))
sys.path.insert(0, str(ROOT / "p5_governance"))
from silver_lib import contract as silver_contract  # noqa: E402
from silver_lib import egress  # noqa: E402

import classification_lib as cl  # noqa: E402
import licence_gate  # noqa: E402

SPEC_PATH = HERE / "export_spec.yml"
MANIFEST = licence_gate.MANIFEST_NAME


class ExportRefused(Exception):
    """The export must not be published (a column outside the spec, a gate violation, ...)."""


def load_spec(path: Path = SPEC_PATH) -> dict:
    spec = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if spec.get("suppress_below", 0) < 2:
        raise ValueError("suppress_below must be at least 2")
    for name, d in spec["datasets"].items():
        for key in ("table", "columns", "text_columns", "count_columns", "order_by"):
            if key not in d:
                raise ValueError(f"dataset {name}: missing {key}")
        for key in ("text_columns", "count_columns", "order_by"):
            if not set(d[key]) <= set(d["columns"]):
                raise ValueError(f"dataset {name}: {key} names a column that is not exported")
    return spec


def select_sql(name: str, spec: dict, schema: str) -> str:
    """The one SELECT the notebook runs for a dataset: only the listed columns, only the listed filter."""
    d = spec["datasets"][name]
    where = f" where {d['where']}" if d.get("where") else ""
    return f"select {', '.join(d['columns'])} from {schema}.{d['table']}{where}"


def classification_problems(spec: dict) -> list[str]:
    """Columns the spec exports that the classification marks personal or internal (should be none)."""
    cls = cl.load_spec()
    gold = cl.gold_columns()
    out = []
    for name, d in spec["datasets"].items():
        table = d["table"]
        if table not in gold:
            out.append(f"{name}: {table} is not a known gold model")
            continue
        rows = {r["column"]: r["class"] for r in cl.gold_rows(cls, table, gold[table])}
        for c in d["columns"]:
            if c not in rows:
                out.append(f"{name}: column {c} is not in {table}")
            elif rows[c] != "public":
                out.append(f"{name}: column {c} is classified {rows[c]}")
    return out


def _clean(v):
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return v


def build_dataset(name: str, rows: list[dict], spec: dict, c: dict | None = None) -> tuple[list[dict], dict]:
    """Rows of one dataset after the column check, the exit function and small-number suppression. Returns (rows, report)."""
    d = spec["datasets"][name]
    c = c or silver_contract.load()
    cols = d["columns"]
    for r in rows:
        if set(r) != set(cols):
            raise ExportRefused(f"{name}: a row has columns {sorted(set(r) ^ set(cols))} that differ from the spec")
    work = [{k: _clean(r[k]) for k in cols} for r in rows]
    report = {"rows_in": len(work), "patterns_removed": 0, "suppressed_cells": 0}
    # the exit function works on rows with the silver names of the text columns; map each exported text column to `brands`, one at a time
    for col in d["text_columns"]:
        shaped = [{"code": str(i), "last_modified_t": 0, "brands": r[col]} for i, r in enumerate(work)]
        clean, rep = egress.prepare_for_export(shaped, c, set())
        for r, s in zip(work, clean):
            r[col] = s["brands"]
        report["patterns_removed"] += int(rep.get("patterns_removed", 0))
    low = spec["suppress_below"]
    for r in work:
        for col in d["count_columns"]:
            v = r[col]
            if v is not None and 0 < v < low:
                r[col] = None
                report["suppressed_cells"] += 1
    work.sort(key=lambda r: tuple("" if r[k] is None else str(r[k]) for k in d["order_by"]))
    return work, report


def render_csv(rows: list[dict], columns: list[str]) -> bytes:
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(columns)
    for r in rows:
        w.writerow(["" if r[c] is None else r[c] for c in columns])
    return buf.getvalue().encode("utf-8")


def attribution_page(spec: dict, status: dict) -> bytes:
    text = (
        "# About this data\n\n"
        f"{' '.join(spec['attribution'].split())}\n\n"
        f"Built at {status['built_at_utc']} UTC. Daily figures cover the complete days {status['first_complete_day']} to "
        f"{status['last_complete_day']}; the newest day is left out until the next capture completes it.\n"
    )
    return text.encode("utf-8")


def build_release(folder: str | Path, datasets: dict[str, list[dict]], status: dict, spec: dict | None = None,
                  today: dt.date | None = None, c: dict | None = None) -> dict:
    """Write the release folder (data files, ATTRIBUTION.md, release_manifest.json), then run the licence gate on it.

    datasets: {name: rows read from gold}. status: built_at_utc, first_complete_day, last_complete_day (ISO strings) and one row
    of counts (`site_status`, written as its own file). Raises ExportRefused when the gate reports anything; the folder is then left for
    inspection and must not be published. Returns the manifest.
    """
    spec = spec or load_spec()
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    problems = classification_problems(spec)
    if problems:
        raise ExportRefused("; ".join(problems))
    files, reports = [], {}
    for name in spec["datasets"]:
        if name not in datasets:
            raise ExportRefused(f"dataset {name} was not provided")
        rows, rep = build_dataset(name, datasets[name], spec, c)
        data = render_csv(rows, spec["datasets"][name]["columns"])
        (folder / f"{name}.csv").write_bytes(data)
        files.append({"path": f"{name}.csv", "kind": "data", "rows": len(rows), "sha256": hashlib.sha256(data).hexdigest()})
        reports[name] = rep
    status_cols = list(status)
    data = render_csv([status], status_cols)
    (folder / "site_status.csv").write_bytes(data)
    files.append({"path": "site_status.csv", "kind": "data", "rows": 1, "sha256": hashlib.sha256(data).hexdigest()})
    page = attribution_page(spec, status)
    (folder / "ATTRIBUTION.md").write_bytes(page)
    files.append({"path": "ATTRIBUTION.md", "kind": "page", "sha256": hashlib.sha256(page).hexdigest()})
    manifest = {
        "source": spec["source_name"],
        "source_dump_date": status["last_complete_day"],
        "licence": spec["licence"],
        "attribution": " ".join(spec["attribution"].split()),
        "built_at_utc": status["built_at_utc"],
        "exit_function": {"called": True, "module": "silver_lib.egress.prepare_for_export", "residue_scan": "passed"},
        "suppress_below": spec["suppress_below"],
        "reports": reports,
        "files": files,
    }
    (folder / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    violations = licence_gate.check_release(folder, today)
    if violations:
        raise ExportRefused("licence gate: " + "; ".join(violations))
    return manifest
