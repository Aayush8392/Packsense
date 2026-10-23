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
    cs = spec.get("card_shards")
    if cs is not None:
        if cs["columns"] != licence_gate.CARD_COLUMNS:
            raise ValueError("card_shards: the columns must equal the licence gate's CARD_COLUMNS, in the same order")
        if not 10_000 <= int(cs["split_above_bytes"]) < licence_gate.CARD_MAX_BYTES:
            raise ValueError("card_shards: split_above_bytes must be between 10,000 and the gate's hard cap")
    return spec


def select_sql(name: str, spec: dict, schema: str) -> str:
    """The one SELECT the notebook runs for a dataset: only the listed columns, only the listed filter."""
    d = spec["datasets"][name]
    where = f" where {d['where']}" if d.get("where") else ""
    return f"select {', '.join(d['columns'])} from {d.get('schema') or schema}.{d['table']}{where}"   # `schema` in the spec overrides the gold schema (the health table)


def classification_problems(spec: dict) -> list[str]:
    """Columns the spec exports that the classification marks personal or internal (should be none)."""
    cls = cl.load_spec()
    gold = cl.gold_columns()
    out = []
    tables = cl.table_columns()
    listed = {t["name"]: t for t in cls.get("tables") or []}
    for name, d in spec["datasets"].items():
        table = d["table"]
        if d.get("schema"):                 # a table outside gold: classified by classification.yml's `tables`
            full = f"{d['schema']}.{table}"
            if full not in listed or full not in tables:
                out.append(f"{name}: {full} is not a classified table")
                continue
            rows = {r["column"]: r["class"] for r in cl.table_rows(cls, listed[full], tables[full])}
        elif table not in gold:
            out.append(f"{name}: {table} is not a known gold model")
            continue
        else:
            rows = {r["column"]: r["class"] for r in cl.gold_rows(cls, table, gold[table])}
        for c in d["columns"]:
            if c not in rows:
                out.append(f"{name}: column {c} is not in {table}")
            elif rows[c] != "public":
                out.append(f"{name}: column {c} is classified {rows[c]}")
    cs = spec.get("card_shards")
    if cs:
        if cs["table"] not in gold:
            out.append(f"card_shards: {cs['table']} is not a known gold model")
        else:
            rows = {r["column"]: r["class"] for r in cl.gold_rows(cls, cs["table"], gold[cs["table"]])}
            for c in cs["columns"]:
                if c not in rows:
                    out.append(f"card_shards: column {c} is not in {cs['table']}")
                elif rows[c] != "public":
                    out.append(f"card_shards: column {c} is classified {rows[c]}")
    return out


def card_select_sql(spec: dict, schema: str) -> str:
    """The one SELECT for the cards: only the listed columns of the one table."""
    cs = spec["card_shards"]
    return f"select {', '.join(cs['columns'])} from {schema}.{cs['table']}"


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


def build_card_files(rows: list[dict], spec: dict) -> tuple[dict[str, bytes], dict]:
    """The card shards as {path: bytes} (cards/<prefix>.csv and cards/splits.json) plus a report. Deterministic: sorted rows, LF, UTF-8, no timestamps.

    Only barcodes of 8 to 14 digits are kept. The files are made by the lookup rule of licence_gate.shard_for: the first 3 digits name a file; a file larger than
    split_above_bytes is split by one more digit, repeatedly, up to CARD_MAX_DEPTH digits; a file that is still too large there is refused."""
    cs = spec["card_shards"]
    cols = cs["columns"]
    limit = int(cs["split_above_bytes"])
    for r in rows:
        if set(r) != set(cols):
            raise ExportRefused(f"card_shards: a row has columns {sorted(set(r) ^ set(cols))} that differ from the spec")
    kept = sorted(({k: _clean(r[k]) for k in cols} for r in rows if licence_gate.CARD_CODE.match(str(r["code"]))), key=lambda r: str(r["code"]))
    dropped = len(rows) - len(kept)
    files: dict[str, bytes] = {}
    splits: set[str] = set()

    def emit(prefix: str, group: list[dict]) -> None:
        data = render_csv(group, cols)
        if len(data) > limit and len(prefix) < licence_gate.CARD_MAX_DEPTH:
            splits.add(prefix)
            by_next: dict[str, list[dict]] = {}
            for r in group:
                by_next.setdefault(str(r["code"])[: len(prefix) + 1], []).append(r)
            for nxt in sorted(by_next):
                emit(nxt, by_next[nxt])
            return
        if len(data) > licence_gate.CARD_MAX_BYTES:
            raise ExportRefused(f"card_shards: the shard {prefix} is still {len(data)} bytes at {len(prefix)} digits")
        files[f"cards/{prefix}.csv"] = data

    base: dict[str, list[dict]] = {}
    for r in kept:
        base.setdefault(str(r["code"])[: licence_gate.CARD_BASE_DEPTH], []).append(r)
    for prefix in sorted(base):
        emit(prefix, base[prefix])
    files[licence_gate.CARD_INDEX_PATH] = (json.dumps({"version": 1, "splits": sorted(splits)}, sort_keys=True) + "\n").encode("utf-8")
    sizes = [len(v) for k, v in files.items() if k != licence_gate.CARD_INDEX_PATH]
    report = {"cards_in": len(rows), "cards_published": len(kept), "dropped_not_a_barcode": dropped, "shards": len(sizes), "splits": len(splits),
              "largest_shard_bytes": max(sizes) if sizes else 0, "total_bytes": sum(sizes)}
    return files, report


def attribution_page(spec: dict, status: dict) -> bytes:
    text = (
        "# About this data\n\n"
        f"{' '.join(spec['attribution'].split())}\n\n"
        f"Built at {status['built_at_utc']} UTC. Daily figures cover the complete days {status['first_complete_day']} to "
        f"{status['last_complete_day']}; the newest day is left out until the next capture completes it.\n"
    )
    return text.encode("utf-8")


def build_release(folder: str | Path, datasets: dict[str, list[dict]], status: dict, spec: dict | None = None,
                  today: dt.date | None = None, c: dict | None = None, cards: list[dict] | None = None) -> dict:
    """Write the release folder (data files, ATTRIBUTION.md, release_manifest.json), then run the licence gate on it.

    datasets: {name: rows read from gold}. status: built_at_utc, first_complete_day, last_complete_day (ISO strings) and one row
    of counts (`site_status`, written as its own file). Raises ExportRefused when the gate reports anything; the folder is then left for
    inspection and must not be published. Returns the manifest. `cards`: the rows of the card table (spec section card_shards); None leaves the cards out.
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
    if cards is not None:
        card_files, card_report = build_card_files(cards, spec)
        for path, data in sorted(card_files.items()):
            target = folder / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            is_index = path == licence_gate.CARD_INDEX_PATH
            entry = {"path": path, "kind": "card_index" if is_index else "card", "sha256": hashlib.sha256(data).hexdigest()}
            if not is_index:
                entry["rows"] = data.count(b"\n") - 1
            files.append(entry)
        reports["card_shards"] = card_report
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
