"""Pure logic of the data classification (P5 step 5): load and validate classification.yml, read the real column lists of every table from the
project's own definitions (the silver and taxonomy contracts, the DDL in silver_lib and the bronze notebook, gold_columns.json), classify every
column and render DATA_CLASSIFICATION.md. No Databricks calls, so everything is testable offline and the document can be checked in CI."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "p2_lakehouse"))
sys.path.insert(0, str(ROOT / "p9_operations"))
import existence_lib  # noqa: E402
import snapshot_lib  # noqa: E402
from silver_lib import contract as silver_contract  # noqa: E402
from silver_lib import schema as silver_schema  # noqa: E402
from silver_lib import taxonomy as taxonomy_lib  # noqa: E402

DEFAULT_PATH = HERE / "classification.yml"
GOLD_COLUMNS = HERE / "gold_columns.json"
DOC_PATH = ROOT / "DATA_CLASSIFICATION.md"
CLASSES = ("public", "personal", "internal")
NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


class SpecError(ValueError):
    pass


def load_spec(path: str | Path = DEFAULT_PATH) -> dict:
    spec = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate(spec)
    return spec


def validate(spec: dict) -> None:
    if not isinstance(spec, dict) or spec.get("version") != 1:
        raise SpecError("classification file: version must be 1")
    mapping = spec.get("silver_mapping") or {}
    if set(mapping) != {"key", "public", "hashed", "derived", "lineage"} or not set(mapping.values()) <= set(CLASSES):
        raise SpecError("silver_mapping must map exactly key, public, hashed, derived and lineage to public, personal or internal")
    if mapping["hashed"] != "personal":
        raise SpecError("hashed contributor codes are personal data (pseudonymised data stays personal)")
    if spec.get("gold_default") not in CLASSES:
        raise SpecError("gold_default must be a class")
    seen = set()
    for t in spec.get("tables") or []:
        if t.get("class") not in CLASSES or t["name"].count(".") != 2 or not t.get("why"):
            raise SpecError(f"table {t.get('name')}: needs a full name, a class and a reason")
        if t["name"] in seen:
            raise SpecError(f"table {t['name']} is listed twice")
        seen.add(t["name"])
        for col, c in (t.get("columns") or {}).items():
            if not NAME_RE.match(col) or c.get("class") not in CLASSES:
                raise SpecError(f"table {t['name']}, column {col}: needs a plain name and a class")
    for key, c in {**(spec.get("gold_overrides") or {}), **(spec.get("silver_overrides") or {})}.items():
        if c.get("class") not in CLASSES:
            raise SpecError(f"override {key}: class must be one of {CLASSES}")
    for key in spec.get("gold_overrides") or {}:
        if key.count(".") != 1:
            raise SpecError(f"gold override {key}: write it as model.column")


# --- the real column lists ----------------------------------------------------------------------------------------------------------

def ddl_columns(sql: str) -> list[str]:
    """Column names from a CREATE TABLE statement ('(' ... ')' with types such as MAP<STRING,BIGINT> that contain commas)."""
    body = sql[sql.index("(") + 1: sql.rindex(")")]
    parts, depth, cur = [], 0, ""
    for ch in body:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [p.split()[0] for p in parts if p.strip()]


def _bronze_ddls() -> dict[str, str]:
    text = (ROOT / "p2_lakehouse" / "notebooks" / "bronze_load.py").read_text(encoding="utf-8")
    out = {}
    for name, key in (("bronze_delta_raw", "RAW"), ("bronze_manifest", "MANIFEST")):
        m = re.search(r"CREATE TABLE IF NOT EXISTS \{" + key + r"\} \((.*?)\) USING DELTA", text, re.S)
        if not m:
            raise SpecError(f"cannot find the {name} definition in bronze_load.py")
        out[name] = "(" + m.group(1) + ")"
    return out


def table_columns() -> dict[str, list[str]]:
    """full table name -> its columns, for every table of classification.yml's `tables` (and silver_product_versions)."""
    sc = silver_contract.load()
    tc = taxonomy_lib.load() if hasattr(taxonomy_lib, "load") else yaml.safe_load((ROOT / "p2_lakehouse" / "contracts" / "taxonomy.yml").read_text(encoding="utf-8"))
    bronze = _bronze_ddls()
    schema_of_bronze = sc["source_table"].rsplit(".", 1)[0]
    pol_schema = yaml.safe_load((HERE / "policies.yml").read_text(encoding="utf-8"))
    pol_table = f"{pol_schema['policy_schema']}.{pol_schema['access_table']}"
    return {
        sc["table"]: [c["name"] for c in sc["columns"]],
        sc["quarantine_table"]: ddl_columns(silver_schema.quarantine_table_sql(sc)),
        sc["manifest_table"]: ddl_columns(silver_schema.manifest_table_sql(sc)),
        sc["stats_table"]: ddl_columns(silver_schema.stats_table_sql(sc)),
        sc["field_log_table"]: ddl_columns(silver_schema.field_log_table_sql(sc)),
        silver_schema.drift_report_table(sc): ddl_columns(silver_schema.drift_report_table_sql(sc)),
        silver_schema.drift_metrics_table(sc): ddl_columns(silver_schema.drift_metrics_table_sql(sc)),
        f"{schema_of_bronze}.bronze_delta_raw": ddl_columns(bronze["bronze_delta_raw"]),
        f"{schema_of_bronze}.bronze_manifest": ddl_columns(bronze["bronze_manifest"]),
        tc["table"]: [c["name"] for c in tc["columns"]],
        tc["manifest_table"]: ddl_columns(taxonomy_lib.manifest_sql(tc)),
        pol_table: ["principal", "market"],
        f"{existence_lib.DEFAULT_SCHEMA}.{existence_lib.TABLE}": existence_lib.ddl_columns(existence_lib.ddl()),
        **{f"{snapshot_lib.DEFAULT_SCHEMA}.{name}": snapshot_lib.ddl_columns(sql) for name, sql in snapshot_lib.ddl(snapshot_lib.DEFAULT_SCHEMA).items()},
    }


def gold_columns(path: str | Path = GOLD_COLUMNS) -> dict[str, list[str]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["models"]


# --- classifying --------------------------------------------------------------------------------------------------------------------

def silver_rows(spec: dict) -> list[dict]:
    """One row per silver_product_versions column: the design class, the contract class, whether it never leaves silver, the note."""
    sc = silver_contract.load()
    out = []
    for c in sc["columns"]:
        cls = spec["silver_mapping"][c["class"]]
        if c.get("egress") == "never" and c["class"] != "hashed":
            cls = "internal"          # never leaves silver and is not a hashed identity: operating data (the key version)
        override = (spec.get("silver_overrides") or {}).get(c["name"])
        if override:
            cls = override["class"]
        out.append({"column": c["name"], "type": c["type"], "class": cls, "contract_class": c["class"],
                    "never_leaves_silver": c.get("egress") == "never", "note": c.get("note", "")})
    return out


def table_rows(spec: dict, table: dict, columns: list[str]) -> list[dict]:
    over = table.get("columns") or {}
    return [{"column": col, "class": over.get(col, {}).get("class", table["class"]), "note": over.get(col, {}).get("note", "")} for col in columns]


def gold_rows(spec: dict, model: str, columns: list[str]) -> list[dict]:
    over = spec.get("gold_overrides") or {}
    rows = []
    for col in columns:
        o = over.get(f"{model}.{col}", {})
        rows.append({"column": col, "class": o.get("class", spec["gold_default"]), "note": o.get("note", "")})
    return rows


def problems(spec: dict, tables: dict[str, list[str]] | None = None, gold: dict[str, list[str]] | None = None) -> list[str]:
    """Everything that makes the classification unsound (empty = fine): a table of the project missing from the file, a table in the file that
    does not exist, an override naming a column that does not exist, a personal or never-leaves column classified as public."""
    tables = tables if tables is not None else table_columns()
    gold = gold if gold is not None else gold_columns()
    out = []
    listed = {t["name"] for t in spec.get("tables") or []}
    product = silver_contract.load()["table"]
    for name in sorted(set(tables) - listed - {product}):
        out.append(f"table {name} exists in the project but is not classified")
    for name in sorted(listed - set(tables)):
        out.append(f"table {name} is classified but has no known definition")
    for t in spec.get("tables") or []:
        for col in (t.get("columns") or {}):
            if t["name"] in tables and col not in tables[t["name"]]:
                out.append(f"{t['name']}.{col}: override names a column that does not exist")
    sc_cols = set(tables.get(product, []))
    for col in spec.get("silver_overrides") or {}:
        if col not in sc_cols:
            out.append(f"silver override {col} does not exist")
    for key in spec.get("gold_overrides") or {}:
        model, col = key.split(".")
        if col not in gold.get(model, []):
            out.append(f"gold override {key} does not exist")
    for r in silver_rows(spec):
        if r["contract_class"] == "hashed" and r["class"] != "personal":
            out.append(f"silver {r['column']} is hashed but not classified personal")
        if r["never_leaves_silver"] and r["class"] == "public":
            out.append(f"silver {r['column']} never leaves silver but is classified public")
    for model, cols in gold.items():
        for r in gold_rows(spec, model, cols):
            if r["class"] == "personal":
                out.append(f"gold {model}.{r['column']} is personal: gold holds no personal column")
    return out


# --- rendering ----------------------------------------------------------------------------------------------------------------------

HEADER = """# Data classification

*Generated by `p5_governance/bootstrap/render_classification.py` from `p5_governance/classification.yml`, the silver contract and
`p5_governance/gold_columns.json`. Do not edit by hand: a test fails when this file is stale. Classes are as the design says (6.7).*

| Class | Meaning | May leave the project? |
|---|---|---|
| **public** | OFF's own public content, or an aggregate of it | Yes, but only through the exit function (`silver_lib/egress.py`), with the OFF attribution and ODbL notice |
| **personal** | identifies a person, or could once a reader joins it with OFF's public data; pseudonymised data is still personal data | No |
| **internal** | operating data: lineage and run bookkeeping | Not published |

## What this does and does not say
- It is a **label on every column**, not a guarantee. OFF itself publishes contributor usernames, so the hashed codes protect only against
  our own readers, and the scrub of free text is a **measured bound, not a guarantee** (`product_name` and `brands` are public; the measured
  residue of contact-shaped text and long digit runs is in the privacy audit, step 6).
- `personal` columns are also protected by code: `egress: never` in the silver contract, a column mask in Unity Catalog (`policies.yml`),
  and a test that no gold column is personal. The classes `public` and `internal` are policy; the exit function drops only `egress: never` columns today.
- Pseudonymised data stays personal data. Nothing here claims anonymisation or compliance with any law.
"""


def _cell(s: str) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ")


def _table(rows: list[dict], extra: tuple[str, ...] = ()) -> str:
    head = "| Column | Class |" + "".join(f" {e} |" for e in extra) + " Note |"
    sep = "|---|---|" + "---|" * len(extra) + "---|"
    lines = [head, sep]
    for r in rows:
        cells = "".join(f" {_cell(str(r.get(k, '')))} |" for k in extra)
        lines.append(f"| `{r['column']}` | {r['class']} |{cells} {_cell(r.get('note', ''))} |")
    return "\n".join(lines)


def counts(rows: list[dict]) -> str:
    n = {c: sum(1 for r in rows if r["class"] == c) for c in CLASSES}
    return f"{len(rows)} columns: {n['public']} public, {n['personal']} personal, {n['internal']} internal"


def render(spec: dict, tables: dict[str, list[str]] | None = None, gold: dict[str, list[str]] | None = None) -> str:
    tables = tables if tables is not None else table_columns()
    gold = gold if gold is not None else gold_columns()
    out = [HEADER]
    s = silver_rows(spec)
    out.append(f"## Silver: `{silver_contract.load()['table']}`\n\n{counts(s)}. The class comes from the `class` column of "
               "`p2_lakehouse/contracts/silver.yml` (key and public to public, hashed to **personal**, lineage to internal, derived to public), "
               "except that a column that never leaves silver and is not a hashed identity is internal.\n")
    out.append(_table([{**r, "never": "yes" if r["never_leaves_silver"] else ""} for r in s], extra=("never",)).replace("| never |", "| Never leaves silver |"))
    out.append("\n## Other tables\n")
    for t in spec["tables"]:
        rows = table_rows(spec, t, tables[t["name"]])
        out.append(f"### `{t['name']}`: {t['class']}\n\n{t['why']}. {counts(rows)}.\n")
        notable = [r for r in rows if r["class"] != t["class"] or r["note"]]
        if notable:
            out.append(_table(notable))
            out.append("")
    out.append("## Gold (the 20 portable models)\n")
    all_gold = [r for m, cols in sorted(gold.items()) for r in gold_rows(spec, m, cols)]
    out.append(f"Every column is **{spec['gold_default']}** unless listed below. {counts(all_gold)}. Gold holds no personal column (a test enforces it): "
               "contributor codes stay in silver and gold gets only counts derived from them.\n")
    out.append("| Model | Columns |\n|---|---|")
    for m, cols in sorted(gold.items()):
        out.append(f"| `{m}` | {len(cols)} |")
    listed = [(m, r) for m, cols in sorted(gold.items()) for r in gold_rows(spec, m, cols) if r["class"] != spec["gold_default"] or r["note"]]
    if listed:
        out.append("\nColumns with a note or a different class:\n")
        out.append(_table([{**r, "column": f"{m}.{r['column']}"} for m, r in listed]))
    return "\n".join(out).rstrip() + "\n"
