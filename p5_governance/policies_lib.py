"""Pure logic of the policies file (row filters and masks): load and validate it, render the SQL that creates the access table and the three
functions and attaches them, and parse what Unity Catalog reports for a table so live state can be compared with the file. No Databricks
calls here (see policies_live.py), so everything is testable offline."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).resolve().parent / "policies.yml"
TABLE_RE = re.compile(r"^[A-Za-z0-9_]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+$")
NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
MARKET_RE = re.compile(r"^(\*|[a-z]{2,3}:[a-z0-9-]+)$")
MASK_TYPES = {"string": "STRING", "array": "ARRAY<STRING>"}


class SpecError(ValueError):
    pass


def load_spec(path: str | Path = DEFAULT_PATH) -> dict:
    spec = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate(spec)
    return spec


def validate(spec: dict, roles: set[str] | None = None) -> None:
    if not isinstance(spec, dict) or spec.get("version") != 1:
        raise SpecError("policies file: version must be 1")
    schema = spec.get("policy_schema", "")
    if schema.count(".") != 1 or not all(NAME_RE.match(p) for p in schema.split(".")) or not schema.startswith(spec.get("catalog", "?") + "."):
        raise SpecError("policy_schema must be catalog.schema inside the catalog")
    for key in ("access_table", "row_filter_function"):
        if not NAME_RE.match(spec.get(key, "")):
            raise SpecError(f"{key} must be a plain name")
    if set(spec.get("mask_functions", {})) != set(MASK_TYPES) or not all(NAME_RE.match(v) for v in spec["mask_functions"].values()):
        raise SpecError(f"mask_functions needs exactly the types {sorted(MASK_TYPES)} with plain names")
    for role, markets in (spec.get("access") or {}).items():
        if roles is not None and role not in roles:
            raise SpecError(f"access: unknown role {role}")
        if not isinstance(markets, list) or not markets or not all(isinstance(m, str) and MARKET_RE.match(m) for m in markets):
            raise SpecError(f"access {role}: a non-empty list of market tags (or '*')")
    for f in spec.get("row_filters") or []:
        if not TABLE_RE.match(f.get("table", "")) or not NAME_RE.match(f.get("column", "")):
            raise SpecError(f"row filter {f}: needs a full table name and a plain column name")
    tables = spec.get("mask_tables") or []
    if not all(TABLE_RE.match(t) for t in tables):
        raise SpecError("mask_tables must be full table names")
    for col, kind in (spec.get("mask_columns") or {}).items():
        if not NAME_RE.match(col) or kind not in MASK_TYPES:
            raise SpecError(f"mask column {col}: type must be one of {sorted(MASK_TYPES)}")


def fq(spec: dict, name: str) -> str:
    return f"{spec['policy_schema']}.{name}"


def expected_access(spec: dict, ids: dict[str, str | None]) -> tuple[set[tuple[str, str]], list[str]]:
    """The (principal id, market) rows the access table must hold, and the roles skipped because they could not be resolved."""
    out, skipped = set(), []
    for role, markets in (spec.get("access") or {}).items():
        pid = ids.get(role)
        if pid is None:
            skipped.append(role)
            continue
        out.update((pid, m) for m in markets)
    return out, skipped


def _lit(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def sql_objects(spec: dict, rows: set[tuple[str, str]]) -> list[str]:
    """The statements that create the schema, the access table (contents replaced in ONE atomic overwrite, so a reader never sees it empty)
    and the three functions. Safe to run again."""
    t, rf = fq(spec, spec["access_table"]), fq(spec, spec["row_filter_function"])
    values = ", ".join(f"({_lit(p)}, {_lit(m)})" for p, m in sorted(rows))
    full = f"EXISTS (SELECT 1 FROM {t} a WHERE a.principal = current_user() AND a.market = '*')"
    stmts = [
        f"CREATE SCHEMA IF NOT EXISTS {spec['policy_schema']}",
        f"CREATE TABLE IF NOT EXISTS {t} (principal STRING, market STRING)",
        f"INSERT OVERWRITE TABLE {t} VALUES {values}",
        f"CREATE OR REPLACE FUNCTION {rf}(m STRING) RETURNS BOOLEAN RETURN "
        f"EXISTS (SELECT 1 FROM {t} a WHERE a.principal = current_user() AND (a.market = '*' OR a.market = m))",
    ]
    for kind, fn in spec["mask_functions"].items():
        typ = MASK_TYPES[kind]
        stmts.append(f"CREATE OR REPLACE FUNCTION {fq(spec, fn)}(v {typ}) RETURNS {typ} RETURN CASE WHEN {full} THEN v ELSE NULL END")
    return stmts


def sql_attach(spec: dict) -> list[str]:
    """ALTER statements that attach the filters and masks (the same statements the dbt post-hook runs for the filters)."""
    rf = fq(spec, spec["row_filter_function"])
    stmts = [f"ALTER TABLE {f['table']} SET ROW FILTER {rf} ON ({f['column']})" for f in spec.get("row_filters") or []]
    for table in spec.get("mask_tables") or []:
        for col, kind in spec["mask_columns"].items():
            stmts.append(f"ALTER TABLE {table} ALTER COLUMN {col} SET MASK {fq(spec, spec['mask_functions'][kind])}")
    return stmts


def attach_plan(spec: dict, live: dict[str, dict | None]) -> list[str]:
    """Only the ALTER statements still needed, given what is live. Measured on dev: setting a filter or mask on a table that ALREADY has one
    fails for the admin ('does not have MODIFY') while dropping it first works, so a different one is dropped, then set; one that already
    matches is left alone (so a rerun changes nothing). A table that does not exist is skipped (the compare reports it)."""
    rf = fq(spec, spec["row_filter_function"])
    out = []
    for table, want in expected_attachments(spec).items():
        got = live.get(table)
        if got is None:
            continue
        if want["filter"] is not None and got["filter"] != want["filter"]:
            if got["filter"] is not None:
                out.append(f"ALTER TABLE {table} DROP ROW FILTER")
            col = want["filter"].rsplit("(", 1)[1].rstrip(")")
            out.append(f"ALTER TABLE {table} SET ROW FILTER {rf} ON ({col})")
        for col, fn in want["masks"].items():
            have = got["masks"].get(col)
            if have != fn:
                if have is not None:
                    out.append(f"ALTER TABLE {table} ALTER COLUMN {col} DROP MASK")
                out.append(f"ALTER TABLE {table} ALTER COLUMN {col} SET MASK {fn}")
    return out


def expected_attachments(spec: dict) -> dict[str, dict]:
    """table -> {'filter': 'fn ON (col)' or None, 'masks': {column: function}} exactly as DESCRIBE EXTENDED reports them (names only)."""
    out: dict[str, dict] = {}
    rf = fq(spec, spec["row_filter_function"])
    for f in spec.get("row_filters") or []:
        out.setdefault(f["table"], {"filter": None, "masks": {}})["filter"] = f"{rf} ON ({f['column']})"
    for table in spec.get("mask_tables") or []:
        e = out.setdefault(table, {"filter": None, "masks": {}})
        for col, kind in spec["mask_columns"].items():
            e["masks"][col] = fq(spec, spec["mask_functions"][kind])
    return out


def parse_describe(rows: list[list[str]]) -> dict:
    """Read the row filter and the column masks out of the rows of DESCRIBE EXTENDED (name, type, comment). Unity Catalog prints the filter as
    '`cat`.`sch`.`fn` ON (col)' and each mask as a (column, '`cat`.`sch`.`fn`') pair under the heading '# Column Masks'."""
    flt, masks, in_masks = None, {}, False
    for r in rows:
        key = (r[0] or "").strip()
        val = (r[1] or "").strip() if len(r) > 1 else ""
        if key == "Row Filter":
            flt = val.replace("`", "")
        elif key == "# Column Masks":
            in_masks = True
        elif in_masks:
            if key.startswith("#"):
                in_masks = False
            elif key and val:
                masks[key] = val.replace("`", "")
    return {"filter": flt, "masks": masks}


def compare_attachments(spec: dict, live: dict[str, dict | None]) -> list[str]:
    """Findings (empty = clean). live maps a table to parse_describe(...) or None when the table does not exist."""
    findings = []
    for table, want in sorted(expected_attachments(spec).items()):
        got = live.get(table)
        if got is None:
            findings.append(f"TABLE MISSING {table}")
            continue
        if want["filter"] != got["filter"]:
            findings.append(f"ROW FILTER {table}: expected {want['filter']!r}, live {got['filter']!r}")
        for col, fn in sorted(want["masks"].items()):
            if got["masks"].get(col) != fn:
                findings.append(f"MASK {table}.{col}: expected {fn!r}, live {got['masks'].get(col)!r}")
        for col in sorted(set(got["masks"]) - set(want["masks"])):
            findings.append(f"EXTRA MASK {table}.{col} (not in the file; left alone)")
    return findings


def compare_access(want: set, have: set) -> tuple[list, list]:
    return sorted(want - have), sorted(have - want)
