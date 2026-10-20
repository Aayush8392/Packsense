"""Export the existence-check part of the DuckDB comparison fixture: the rows of silver_existence_check for the products of the committed product fixture.

  .venv\\Scripts\\python.exe p4_modelling/bootstrap/export_existence_fixture.py --env-file .env     (from the repo root; admin token; read-only on Databricks)

The product fixture (fixtures/stg_silver_versions.jsonl) names the products; this reads every existence check of those products (a snapshot row, or an answer from OFF's
API) through the admin's SQL warehouse and writes fixtures/existence_check.jsonl and existence_manifest.json. The data is OFF's public product codes and a status.
The exit function runs over every text field except the barcode (a barcode is the key, exactly as in the product exit) BEFORE anything is written, and the export
is refused if a scrub pattern is still found. Nothing is written to Databricks. The result is committed by the user (production-derived files are never staged by the assistant).
"""
import argparse
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

P4 = Path(__file__).resolve().parents[1]
ROOT = P4.parent
FIXTURES = P4 / "fixtures"
sys.path.insert(0, str(P4 / "bootstrap"))
sys.path.insert(0, str(ROOT / "p2_lakehouse"))

COLUMNS = {"code": "string", "checked_at": "timestamp", "status": "string", "detail": "string", "evidence_source": "string"}


def fixture_codes(path: Path = FIXTURES / "stg_silver_versions.jsonl") -> list[str]:
    return sorted({json.loads(line)["code"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()})


def to_utc_text(value: str) -> str:
    """The warehouse returns '2026-10-19T18:03:47Z' or '2026-10-19 18:03:47.000'; the fixture holds 'YYYY-MM-DD HH:MM:SS' (UTC) like every other fixture timestamp."""
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")


def build_rows(raw: list[list]) -> list[dict]:
    """raw: [code, checked_at, status, detail, evidence_source] as the warehouse returns them. Sorted for a stable file. `detail` is kept exactly as silver holds it:
    an empty string where OFF said nothing more (production has '' there, and the model turns it into NULL; a fixture with NULL would hide that)."""
    rows = [{"code": r[0], "checked_at": to_utc_text(r[1]), "status": r[2], "detail": r[3], "evidence_source": r[4]} for r in raw]
    return sorted(rows, key=lambda r: (r["code"], r["checked_at"], r["evidence_source"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", required=True)
    ap.add_argument("--table", default="workspace.packsense_silver.silver_existence_check")
    args = ap.parse_args()
    from fixture_databricks import client, load_env_file, run_sql
    from silver_lib import contract, egress
    load_env_file(args.env_file)
    codes = fixture_codes()
    in_list = ", ".join("'" + c.replace("'", "''") + "'" for c in codes)
    w = client()
    res = run_sql(w, f"select code, cast(checked_at as string), status, detail, evidence_source from {args.table} where code in ({in_list})")
    rows = build_rows(res.result.data_array or [])
    # THE EXIT, before anything is written: every text field except the barcode (the key) goes through the scrub and the residue scan
    text_fields = [{k: v for k, v in r.items() if k not in ("code", "checked_at")} for r in rows]
    clean, report = egress.prepare_vocabulary_for_export(text_fields, contract.load())
    out = [{"code": r["code"], "checked_at": r["checked_at"], **c} for r, c in zip(rows, clean)]
    missing = sorted(set(codes) - {r["code"] for r in out})
    FIXTURES.mkdir(exist_ok=True)
    with open(FIXTURES / "existence_check.jsonl", "w", encoding="utf-8", newline="\n") as fh:
        for r in out:
            fh.write(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n")
    manifest = {
        "what": "rows of silver_existence_check (the weekly snapshot comparison and OFF's API answers) for the products of the committed product fixture, after the exit function",
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "products_in_fixture": len(codes),
        "products_with_a_check": len({r["code"] for r in out}),
        "products_without_any_check": missing,
        "version_rows": len(out),
        "rows_by_status": dict(sorted(Counter(r["status"] for r in out).items())),
        "columns": COLUMNS,
        "exit_report": dict(report),
    }
    with open(FIXTURES / "existence_manifest.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True, ensure_ascii=False)
    print(f"wrote {len(out)} rows for {manifest['products_with_a_check']} of {len(codes)} fixture products; by status: {manifest['rows_by_status']}; exit report: {dict(report)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
