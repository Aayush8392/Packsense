"""Scratch rebuild of silver under contract v4 and its comparison with production. Run it from the repo root with the v4 branch pushed.

    python p2_lakehouse/bootstrap/silver_v4_check.py run --env-file .env [--write-metrics PATH] [--reuse]
    python p2_lakehouse/bootstrap/silver_v4_check.py cleanup --env-file .env

`run` reads ALL of production bronze (read only) and writes silver, quarantine and manifest into scratch schemas with the notebook from
git branch `silver-v4` and the real HMAC key, so every old column, hashed ones included, can be compared with production row for row.
Checks (any failure prints FAIL):
  1. balance: bronze rows = silver + quarantine, the notebook reports 0 problems, one balanced manifest row per bronze file;
  2. the same keys (code, last_modified_t) as production, quarantine matched by record hash;
  3. every old column identical to production on every row, except the rows the v4 rebuild is expected to change (the old-format
     delta rows v3 left as 'none'); every difference is listed per column;
  4. each new column counted against an independent count taken straight from bronze's raw JSON;
  5. residue in the new tag columns: contact-shaped and long-digit-run elements (the gate for origins_tags);
  6. lineage: every silver row joins to exactly one bronze row (file, checksum, key) and carries contract version 4.
With --write-metrics it also writes the drift coverage fixture (aggregates only) measured on the scratch silver, and checks that the
old columns' coverage equals the committed fixture's. Production tables are only read. Prints counts only, never a value.
--reuse skips the rebuild and checks the scratch silver left by an earlier `run` (the rebuild takes about 9 minutes).
Reads DATABRICKS_HOST and DATABRICKS_TOKEN from the file or the environment.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / "p2_lakehouse" / "bootstrap"))
sys.path.insert(0, str(ROOT / "p2_lakehouse"))
import crash_test as ct  # noqa: E402
from silver_lib import contract, drift  # noqa: E402

BR_PROD, SI_PROD = ct.PROD_BRONZE, ct.PROD_SILVER
SI = "workspace.ps_v4_silver"
BRANCH = "silver-v4"
RUN_COLS = {"bronze_ingested_at", "silver_processed_at", "job_run_id", "silver_contract_version"}
NEW_TAGS = ["additives_tags", "ingredients_analysis_tags", "nutrient_levels_tags", "food_groups_tags", "packaging_tags", "origins_tags"]
NEW_COLUMNS = NEW_TAGS + ["product_quantity_unit", "environmental_score_grade", "checked", "last_checked_t"]
CONTACT = r"(?i)@|https?|www\."
DIGITS7 = r"\d{7,}"


def lit(s: str) -> str:
    """A Spark SQL string literal that carries the regex exactly as written."""
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def cmd_run(w, q, args):
    c = contract.load()
    tag_rx, enum_rx = "(?U)" + c["shape"]["tag"], "(?U)" + c["shape"]["enum"]
    problems = []
    n_bronze = int(q.one(f"SELECT count(*) FROM {BR_PROD}.bronze_delta_raw"))
    n_files = int(q.one(f"SELECT count(*) FROM {BR_PROD}.bronze_manifest"))
    print(f"production bronze: {n_bronze} rows in {n_files} files (read only)")

    if args.reuse:
        print("--reuse: checking the scratch silver left by the earlier run")
    else:
        q.run(f"DROP SCHEMA IF EXISTS {SI} CASCADE")
        t0 = time.time()
        params = {"bronze_schema": BR_PROD, "silver_schema": SI, "ping_healthchecks": "false", "bronze_result": "n/a", "run_id": "v4-check"}
        waiter = ct.submit(w, "packsense-silver-v4-check", ct.SILVER_NB, params, BRANCH)
        res, r = ct.wait_terminal(w, waiter.run_id, 60)
        text, err = ct.run_output(w, r)
        print(f"silver v4 run: {res} in {round(time.time() - t0)} s", text[:900], err, flush=True)
        if res != "SUCCESS":
            sys.exit("the scratch silver run failed")
        stats = json.loads(text) if text.startswith("{") else {}
        if stats.get("problems", 1) != 0:
            problems.append(f"notebook reported problems: {stats.get('problems')}")

    T, P = f"{SI}.silver_product_versions", f"{SI_PROD}.silver_product_versions"
    # 1. balance --------------------------------------------------------------------------------------------------------
    n_s = int(q.one(f"SELECT count(*) FROM {T}"))
    n_q = int(q.one(f"SELECT count(*) FROM {SI}.silver_quarantine"))
    n_ps = int(q.one(f"SELECT count(*) FROM {P}"))
    n_pq = int(q.one(f"SELECT count(*) FROM {SI_PROD}.silver_quarantine"))
    print(f"\n1 balance: bronze {n_bronze} = silver {n_s} + quarantine {n_q}; production silver {n_ps} + quarantine {n_pq}")
    if n_s + n_q != n_bronze:
        problems.append("silver + quarantine != bronze")
    if (n_s, n_q) != (n_ps, n_pq):
        problems.append(f"counts differ from production: {(n_s, n_q)} vs {(n_ps, n_pq)}")
    dup = int(q.one(f"SELECT count(*) FROM (SELECT code, last_modified_t FROM {T} GROUP BY 1, 2 HAVING count(*) > 1)"))
    man = q.run(f"SELECT file_name, rows_in, rows_silver, rows_quarantine FROM {SI}.silver_manifest")
    if dup or len(man) != n_files or any(int(x[1]) != int(x[2]) + int(x[3]) for x in man):
        problems.append(f"{dup} duplicate keys; manifest rows {len(man)} of {n_files} files, balanced: {all(int(x[1]) == int(x[2]) + int(x[3]) for x in man)}")
    print(f"  duplicate keys {dup}; manifest rows {len(man)} (bronze files {n_files})")

    # 2. keys ------------------------------------------------------------------------------------------------------------
    miss = q.run(f"SELECT sum(CASE WHEN b.code IS NULL THEN 1 ELSE 0 END), sum(CASE WHEN a.code IS NULL THEN 1 ELSE 0 END) FROM {T} a "
                 f"FULL OUTER JOIN {P} b ON a.code <=> b.code AND a.last_modified_t <=> b.last_modified_t WHERE a.code IS NULL OR b.code IS NULL")[0]
    qmiss = int(q.one(f"SELECT count(*) FROM {SI}.silver_quarantine a FULL OUTER JOIN {SI_PROD}.silver_quarantine b "
                      f"ON a.source_file = b.source_file AND a.record_sha256 = b.record_sha256 WHERE a.record_sha256 IS NULL OR b.record_sha256 IS NULL"))
    only_v4, only_prod = int(miss[0] or 0), int(miss[1] or 0)
    print(f"2 keys: only in v4 {only_v4}, only in production {only_prod}; quarantine rows not matched {qmiss}")
    if only_v4 or only_prod:
        problems.append(f"key sets differ: only in v4 {only_v4}, only in production {only_prod}")
    if qmiss:
        problems.append(f"{qmiss} quarantine rows not matched")

    # 3. every old column identical ----------------------------------------------------------------------------------------
    def cols_of(schema):
        rows = q.run(f"SELECT column_name, data_type FROM system.information_schema.columns WHERE table_schema = '{schema.split('.')[1]}' "
                     f"AND table_name = 'silver_product_versions' AND table_catalog = 'workspace' ORDER BY ordinal_position")
        return {x[0]: x[1] for x in rows}
    new_cols, old_cols = cols_of(SI), cols_of(SI_PROD)
    added = [n for n in new_cols if n not in old_cols]
    print(f"3 columns: production {len(old_cols)}, v4 {len(new_cols)}; added {sorted(added)}")
    if sorted(added) != sorted(NEW_COLUMNS) or len(new_cols) != len(c["columns"]) or any(n not in new_cols for n in old_cols):
        problems.append("column sets are not production + the ten new columns")
    compare = [n for n in old_cols if n not in RUN_COLS]

    complex_cols = {x["name"] for x in c["columns"] if "map" in x["type"] or "struct" in x["type"]}   # information_schema gives only 'ARRAY' for these

    def expr(n, a, b):
        return f"to_json({a}.`{n}`) <=> to_json({b}.`{n}`)" if n in complex_cols else f"{a}.`{n}` <=> {b}.`{n}`"
    sums = ", ".join(f"sum(CASE WHEN NOT ({expr(n, 'a', 'b')}) THEN 1 ELSE 0 END)" for n in compare)
    row = q.run(f"SELECT count(*), {sums} FROM {T} a JOIN {P} b ON a.code <=> b.code AND a.last_modified_t <=> b.last_modified_t")[0]
    joined, diffs = int(row[0]), {n: int(v or 0) for n, v in zip(compare, row[1:])}
    differing = {n: v for n, v in diffs.items() if v}
    print(f"  joined {joined} rows; columns that differ from production (count of rows): {differing or 'none'}")
    changed_rows = q.run(f"SELECT a.nutrition_format, b.nutrition_format, count(*) FROM {T} a JOIN {P} b ON a.code <=> b.code AND a.last_modified_t <=> b.last_modified_t "
                         f"WHERE a.nutrition_format <> b.nutrition_format GROUP BY 1, 2")
    print("  rows whose nutrition_format changed (v4, production, rows):", [tuple(x) for x in changed_rows] or "none")
    expected_change = changed_rows and all(x[0] == "legacy" and x[1] == "none" for x in changed_rows)
    if differing and not expected_change:
        problems.append(f"old columns differ without the expected none->legacy change: {differing}")
    if expected_change:
        n_changed = sum(int(x[2]) for x in changed_rows)
        stray = {n: v for n, v in differing.items() if v > n_changed}
        if n_changed > 5 or stray:
            problems.append(f"{n_changed} format changes (expected 2 old-format delta rows); columns differing on more rows than that: {stray}")

    # 4. new columns against bronze's raw JSON ------------------------------------------------------------------------
    print("4 new columns: bronze raw-JSON count | silver count | note")
    base = f"FROM {BR_PROD}.bronze_delta_raw WHERE code RLIKE '^[0-9]+$'"
    for n in NEW_TAGS:
        b = q.run(f"WITH y AS (SELECT from_json(get_json_object(raw_json, '$.{n}'), 'array<string>') a {base}) "
                  f"SELECT sum(coalesce(size(filter(a, e -> e rlike {lit(tag_rx)})), 0)), sum(CASE WHEN size(filter(a, e -> e rlike {lit(tag_rx)})) > 0 THEN 1 ELSE 0 END) FROM y")[0]
        s = q.run(f"SELECT sum(coalesce(size({n}), 0)), sum(CASE WHEN size({n}) > 0 THEN 1 ELSE 0 END) FROM {T}")[0]
        be, bp, se, sp = int(b[0] or 0), int(b[1] or 0), int(s[0] or 0), int(s[1] or 0)
        ok = abs(be - se) <= max(2, 0.0005 * be) and abs(bp - sp) <= max(2, 0.0005 * bp)
        print(f"  {n}: elements {be} | {se}; products with any {bp} | {sp}  {'ok' if ok else 'MISMATCH'}")
        if not ok:
            problems.append(f"{n}: bronze {be}/{bp} vs silver {se}/{sp}")
    for n in ("product_quantity_unit", "environmental_score_grade", "checked"):
        b = int(q.one(f"SELECT count(*) {base} AND get_json_object(raw_json, '$.{n}') rlike {lit(enum_rx)}"))
        s = int(q.one(f"SELECT count({n}) FROM {T}"))
        print(f"  {n}: {b} | {s}  {'ok' if b == s else 'MISMATCH'}")
        if b != s:
            problems.append(f"{n}: bronze {b} vs silver {s}")
    b = int(q.one(f"SELECT count(*) {base} AND get_json_object(raw_json, '$.last_checked_t') rlike '^-?[0-9]+$'"))
    s = int(q.one(f"SELECT count(last_checked_t) FROM {T}"))
    print(f"  last_checked_t: {b} | {s}  {'ok' if b == s else 'MISMATCH'}")
    if b != s:
        problems.append(f"last_checked_t: bronze {b} vs silver {s}")
    print("  coverage of the new columns in v4 silver (% of rows with a value):",
          {n: round(100 * float(q.one(f"SELECT avg(CASE WHEN {n} IS NOT NULL THEN 1 ELSE 0 END) FROM {T}")), 2) for n in NEW_COLUMNS})

    # 5. residue in the new tag columns ----------------------------------------------------------------------------------
    print("5 residue in the new tag columns (elements | products): contact-shaped (@, http, www.) | 7+ digit run | scrubbed '[removed]'")
    for n in NEW_TAGS:
        row = q.run(f"WITH e AS (SELECT code, last_modified_t, explode({n}) t FROM {T} WHERE {n} IS NOT NULL) "
                    f"SELECT sum(CASE WHEN t rlike {lit(CONTACT)} THEN 1 ELSE 0 END), count(DISTINCT CASE WHEN t rlike {lit(CONTACT)} THEN code END), "
                    f"sum(CASE WHEN t rlike {lit(DIGITS7)} THEN 1 ELSE 0 END), count(DISTINCT CASE WHEN t rlike {lit(DIGITS7)} THEN code END), "
                    f"sum(CASE WHEN t LIKE '%[removed]%' THEN 1 ELSE 0 END) FROM e")[0]
        v = [int(x or 0) for x in row]
        print(f"  {n}: contact {v[0]} | {v[1]}; digits {v[2]} | {v[3]}; scrubbed {v[4]}")
        if v[0]:
            problems.append(f"{n}: {v[0]} contact-shaped elements survived the scrub")
        if n == "origins_tags" and v[3]:
            print("  NOTE origins_tags has digit-run elements: decide whether it stays in v4")

    # 6. lineage ----------------------------------------------------------------------------------------------------------
    orphan = int(q.one(f"SELECT count(*) FROM {T} s LEFT JOIN {BR_PROD}.bronze_delta_raw b ON s.source_file = b.source_file AND s.file_sha256 = b.file_sha256 "
                       f"AND s.code = b.code AND s.last_modified_t = b.last_modified_t WHERE b.code IS NULL"))
    multi = int(q.one(f"SELECT count(*) FROM (SELECT s.code, s.last_modified_t FROM {T} s JOIN {BR_PROD}.bronze_delta_raw b ON s.source_file = b.source_file "
                      f"AND s.code = b.code AND s.last_modified_t = b.last_modified_t GROUP BY 1, 2 HAVING count(*) > 1)"))
    ver = [tuple(x) for x in q.run(f"SELECT silver_contract_version, count(*) FROM {T} GROUP BY 1")]
    print(f"6 lineage: silver rows without exactly one bronze row {orphan} / {multi}; contract versions {ver}")
    if orphan or multi or ver != [("4", str(n_s))]:
        problems.append(f"lineage: {orphan} orphans, {multi} multi, versions {ver}")

    if args.write_metrics:
        fixture = json.loads((ROOT / "p2_lakehouse" / "tests" / "fixtures" / "drift_metrics.json").read_text(encoding="utf-8"))
        cols = drift.coverage_columns(c)
        out = {}
        for key, prefix in (("delta_days", "openfoodfacts_products_"), ("seed_parts", "seed-dump:")):
            rows = q.run(drift.metrics_sql(c, T, prefix))
            names = ["source_file", "rows"] + [f"cov_{x}" for x in cols] + [f"fmt_{f}" for f in drift.FORMATS] + ["schema_versions"]
            out[key] = [drift.metrics_from_row(dict(zip(names, r)), cols) for r in rows]
        old_cols_set = set(fixture["delta_days"][0]["coverage"])
        moved = 0
        for key in out:
            old_by_file = {d["file"]: d for d in fixture[key]}
            for d in out[key]:
                o = old_by_file.get(d["file"])
                if o:
                    moved += sum(1 for k in old_cols_set if abs(o["coverage"][k] - d["coverage"][k]) > 0.0015) + (o["rows"] != d["rows"])
        print(f"drift fixture: {len(out['delta_days'])} delta days, {len(out['seed_parts'])} seed parts; old-column coverage values that moved vs the committed fixture: {moved}")
        Path(args.write_metrics).write_text(json.dumps(out, indent=1, sort_keys=True), encoding="utf-8")
        print("wrote", args.write_metrics)

    print("\nproblems:", problems or "none")
    print("RESULT:", "PASS" if not problems else "FAIL")


def cmd_cleanup(w, q, args):
    q.run(f"DROP SCHEMA IF EXISTS {SI} CASCADE")
    print("scratch schemas left:", int(q.one("SELECT count(*) FROM system.information_schema.schemata WHERE schema_name LIKE 'ps_v4%'") or 0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["run", "cleanup"])
    ap.add_argument("--env-file")
    ap.add_argument("--write-metrics")
    ap.add_argument("--reuse", action="store_true")
    a = ap.parse_args()
    if a.env_file:
        ct.load_env_file(a.env_file)
    w = ct.client()
    q = ct.Sql(w)
    {"run": cmd_run, "cleanup": cmd_cleanup}[a.command](w, q, a)


if __name__ == "__main__":
    main()
