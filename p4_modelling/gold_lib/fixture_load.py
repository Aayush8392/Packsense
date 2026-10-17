"""Loads the committed fixture (p4_modelling/fixtures) into DuckDB with the exact column types the manifest records.

The manifest holds Spark type strings (what Databricks knows the staging view's columns as); DuckDB gets the same types, so the
portable models see the same data on both engines. The fixture table is named `fixture_stg_silver_versions` and lives in the target
schema, where the staging models read it through the `fixture` source.
"""
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
TABLE = "fixture_stg_silver_versions"

SCALARS = {
    "string": "VARCHAR", "double": "DOUBLE", "bigint": "BIGINT", "int": "INTEGER", "boolean": "BOOLEAN", "timestamp": "TIMESTAMP",
}


def _split_top_level(text: str) -> list[str]:
    """Split on commas that are not inside angle brackets."""
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return parts


def duckdb_type(spark_type: str) -> str:
    """A Spark simpleString type (string, array<...>, map<k,v>, struct<a:t,...>) as a DuckDB type."""
    t = spark_type.strip()
    if t in SCALARS:
        return SCALARS[t]
    if t.startswith("array<") and t.endswith(">"):
        return duckdb_type(t[6:-1]) + "[]"
    if t.startswith("map<") and t.endswith(">"):
        k, v = _split_top_level(t[4:-1])
        return f"MAP({duckdb_type(k)}, {duckdb_type(v)})"
    if t.startswith("struct<") and t.endswith(">"):
        fields = []
        for f in _split_top_level(t[7:-1]):
            name, ftype = f.split(":", 1)
            fields.append(f'"{name.strip()}" {duckdb_type(ftype)}')
        return "STRUCT(" + ", ".join(fields) + ")"
    raise ValueError(f"no DuckDB mapping for the Spark type {spark_type!r}")


def load(con, schema: str = "main", fixtures: Path = FIXTURES, reverse: bool = False) -> int:
    """(Re)create the fixture table in `schema` from the committed JSONL and manifest. Returns the row count.
    reverse=True stores the rows in the opposite physical order (the idempotence check: gold must not depend on arrival order)."""
    manifest = json.loads((fixtures / "manifest.json").read_text(encoding="utf-8"))
    columns = manifest["columns"]
    types = {name: duckdb_type(t) for name, t in columns.items()}
    col_ddl = ", ".join(f'"{n}" {t}' for n, t in types.items())
    reader_cols = ", ".join(f"'{n}': '{t}'" for n, t in types.items())
    path = (fixtures / "stg_silver_versions.jsonl").as_posix().replace("'", "''")
    con.execute(f'create schema if not exists "{schema}"')
    con.execute(f'drop table if exists "{schema}"."{TABLE}"')
    con.execute(f'create table "{schema}"."{TABLE}" ({col_ddl})')
    order = ' order by "code" desc, "last_modified_t" desc' if reverse else ""
    con.execute(f"insert into \"{schema}\".\"{TABLE}\" select * from read_json('{path}', format='newline_delimited', columns={{{reader_cols}}}){order}")
    n = con.execute(f'select count(*) from "{schema}"."{TABLE}"').fetchone()[0]
    if n != manifest["version_rows"]:
        raise RuntimeError(f"loaded {n} rows, the manifest says {manifest['version_rows']}")
    return n


if __name__ == "__main__":
    # python -m gold_lib.fixture_load [--db target/fixture.duckdb]   (run from p4_modelling/)
    import argparse

    import duckdb

    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="target/fixture.duckdb")
    ap.add_argument("--reverse", action="store_true")
    args = ap.parse_args()
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(args.db)
    print(f"loaded {load(con, reverse=args.reverse)} fixture rows into {args.db}")
    con.close()
