# Databricks notebook source
# The four-product showcase (roadmap Phase B item 12; context amendment A88): ONE one-off run by the admin, not a job. It follows four real products through bronze, silver and gold
# and writes ONE redacted JSON file to a scratch folder of the landing volume; the owner reads that file, fetches it (p6_serving/bootstrap/fetch_showcase.py) and commits it.
#
# Runs as the ADMIN: the raw record holds plaintext contributor names that only bronze keeps and no narrower identity may read. The names are read into memory, replaced by
# labelled stand-ins (contributor-A, ...) and checked to be gone; they are never printed, written or returned. The result of the notebook is COUNTS ONLY.
# Widgets: dry_run=true does everything and the gate check but writes nothing.

# COMMAND ----------
import datetime as dt
import json
import os
import sys
import tempfile


def find_root():
    starts = [os.getcwd()]
    try:
        nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
        starts.insert(0, os.path.dirname(nb if nb.startswith("/Workspace") else "/Workspace" + nb))
    except Exception:
        pass
    for start in starts:
        p = start
        for _ in range(6):
            if os.path.isfile(os.path.join(p, "p6_serving", "showcase_lib.py")) and os.path.isdir(os.path.join(p, "p2_lakehouse", "silver_lib")):
                return p
            p = os.path.dirname(p)
    raise RuntimeError("cannot find p6_serving/showcase_lib.py and p2_lakehouse/silver_lib; looked from " + repr(starts))


ROOT = find_root()
for sub in ("p6_serving", "p2_lakehouse", "p5_governance"):
    sys.path.insert(0, os.path.join(ROOT, sub))
import export_lib as ex  # noqa: E402
import licence_gate as gate  # noqa: E402
import release_lib as rl  # noqa: E402
import showcase_lib as sl  # noqa: E402
from silver_lib import contract as silver_contract  # noqa: E402
from silver_lib import personal  # noqa: E402

dbutils.widgets.text("products", "ordinary_food=8000500026731,several_flags=4337256191760,long_history=0856312002795,india=8901719135170")
dbutils.widgets.text("gold_schema", "workspace.packsense_gold")
dbutils.widgets.text("bronze_table", "workspace.packsense_bronze.bronze_delta_raw")
dbutils.widgets.text("silver_table", "workspace.packsense_silver.silver_product_versions")
dbutils.widgets.text("out_dir", "/Volumes/workspace/packsense/landing/_showcase")
dbutils.widgets.text("dry_run", "false")
PRODUCTS = [p.split("=", 1) for p in dbutils.widgets.get("products").split(",") if "=" in p]
GOLD = dbutils.widgets.get("gold_schema").strip()
BRONZE = dbutils.widgets.get("bronze_table").strip()
SILVER = dbutils.widgets.get("silver_table").strip()
OUT_DIR = dbutils.widgets.get("out_dir").strip().rstrip("/")
DRY = dbutils.widgets.get("dry_run").strip().lower() == "true"
if [k for k, _ in PRODUCTS] != gate.SHOWCASE_PRODUCT_KEYS:
    raise RuntimeError(f"the products must be {gate.SHOWCASE_PRODUCT_KEYS} in that order")
C = silver_contract.load()
PATTERNS = personal.compile_patterns(C)
SPEC = ex.load_spec()
summary = None


def rows_of(sql):
    return [sl.plain(r.asDict(recursive=True)) for r in spark.sql(sql).collect()]


def q(code):
    if code is None:
        raise RuntimeError("a value that must be text is missing")
    return "'" + code.replace("'", "''") + "'"


# COMMAND ----------
try:
    built_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")

    # 1. Bronze: EVERY version of each product (the names come from all of them), and the newest version we hold (the one shown).
    versions = {}
    for key, code in PRODUCTS:
        rs = spark.table(BRONZE).where(f"code = {q(code)}").select("last_modified_t", "source_file", "raw_json").collect()
        if not rs:
            raise RuntimeError(f"{key}: no bronze record")
        versions[key] = sorted(((r["last_modified_t"], r["source_file"], json.loads(r["raw_json"])) for r in rs), key=lambda x: (x[0], x[1]))
    all_names = set()
    for vs in versions.values():
        for _, _, rec in vs:
            all_names |= {personal.normalise(n) for n in sl.identity_names(rec, C)}
    print("bronze versions read:", {k: len(v) for k, v in versions.items()}, "; distinct contributor names across them:", len(all_names))

    # 2. Names that are ordinary words across the WHOLE catalogue are not replaced inside text (only in the contributor fields).
    handles = {n for n in all_names if len(n) >= sl.NAME_MIN_LENGTH}
    cat = spark.table(f"{GOLD}.product_history").where("is_latest_observed = 1").select("product_name", "brands")
    catalogue = [{"product_name": r["product_name"], "brands": r["brands"]} for r in cat.collect()]
    ordinary = rl.catalogue_ordinary_names(catalogue, handles, C)
    del catalogue
    text_handles = handles - ordinary
    print("names of 8+ characters:", len(handles), "; ordinary across the catalogue (left alone in text):", len(ordinary))

    # 3. Each product, in the fixed order (so a stand-in label is the same in every product).
    standins = sl.StandIns()
    products = []
    report = []
    for key, code in PRODUCTS:
        t_last, source_file, raw = versions[key][-1]
        redacted, raw_counts = sl.redact_raw(raw, standins, text_handles, PATTERNS, C)

        srow = rows_of(f"select * from {SILVER} where code = {q(code)} and last_modified_t = {int(t_last)}")
        if not srow:
            raise RuntimeError(f"{key}: no silver row for the newest bronze version")
        srow = srow[0]
        silver = {"row": sl.hide_silver(srow, C), "counts": sl.silver_counts(raw, srow, C)}

        hist = rows_of(f"select * from {GOLD}.product_history where code = {q(code)} order by period_no")
        if not hist:
            raise RuntimeError(f"{key}: no gold history")
        latest = hist[-1]
        last_day = str(dt.datetime.fromtimestamp(int(latest["last_version_t"]), dt.timezone.utc).date())
        gold = {
            "product_history": hist,
            "product_flag_spans": rows_of(f"select * from {GOLD}.product_flag_spans where code = {q(code)} order by first_seen_t, flag"),
            "product_nutrition_sets": rows_of(f"select * from {GOLD}.product_nutrition_sets where code = {q(code)} order by source, preparation, per"),
            "product_rule_verdicts": rows_of(f"select * from {GOLD}.product_rule_verdicts where code = {q(code)} order by source, preparation, per, rule"),
            "mart_product_card": rows_of(f"select * from {GOLD}.mart_product_card where code = {q(code)}"),
        }
        # The summary tables: the public export's own columns and small-number suppression; the day is the product's newest edit day, or the newest complete day.
        brand = latest.get("first_brand")
        sc_cols = ", ".join(SPEC["datasets"]["brand_scorecard"]["columns"])
        sc = rows_of(f"select {sc_cols} from {GOLD}.mart_brand_scorecard where scope = 'all' and is_ranked = 1 and brand_name = {q(brand)}") if brand else []
        day = rows_of(f"select least(to_date('{last_day}'), max(change_date)) as d from {GOLD}.fct_product_change_daily")[0]["d"]
        ch_cols = ", ".join(SPEC["datasets"]["change_daily"]["columns"])
        ch = rows_of(f"select {ch_cols} from {GOLD}.fct_product_change_daily where scope = 'all' and change_date = to_date('{day}')")
        # the quality fact files a flag under its taxonomy family, under the flag itself when it is a root flag, and under 'unmapped' otherwise (see fct_catalogue_quality_daily)
        fams = [r["fam"] for r in rows_of(
            f"select distinct case when f.family_source = 'taxonomy' then f.family when f.family_source = 'root' then f.flag else 'unmapped' end as fam "
            f"from {GOLD}.product_flag_spans s join {GOLD}.dim_flag f on f.flag = s.flag where s.code = {q(code)}") if r["fam"]]
        ql_cols = ", ".join(SPEC["datasets"]["quality_daily"]["columns"])
        fam_sql = ", ".join(q(f) for f in fams) if fams else "''"
        qd = rows_of(f"select {ql_cols} from {GOLD}.fct_catalogue_quality_daily where scope = 'all' and snapshot_date = to_date('{day}') and flag_family in ({fam_sql}) "
                     f"order by open_spans desc limit 8")
        if not qd:
            qd = rows_of(f"select {ql_cols} from {GOLD}.fct_catalogue_quality_daily where scope = 'all' and snapshot_date = to_date('{day}') order by open_spans desc limit 3")
        for name, rows in (("brand_scorecard", sc), ("change_daily", ch), ("quality_daily", qd)):
            if rows:
                rows, _ = ex.build_dataset(name, rows, SPEC)
            gold[{"brand_scorecard": "mart_brand_scorecard", "change_daily": "fct_product_change_daily", "quality_daily": "fct_catalogue_quality_daily"}[name]] = rows

        products.append({"key": key, "code": code, "name": latest.get("product_name") or "", "brand": latest.get("brands") or "",
                         "bronze": {"record": redacted, "counts": raw_counts}, "silver": silver, "gold": sl.plain(gold)})
        report.append({"key": key, "versions": len(versions[key]), "periods": len(hist), "raw_fields": len(raw), "day": str(day), **raw_counts})
        print(key, "done:", json.dumps(report[-1]))

    doc = sl.assemble(sl.plain(products), standins, built_at, " ".join(SPEC["attribution"].split()))

    # 4. Checks, all counts: no known name anywhere (exact value, or 8+ characters inside any string), the gate's own showcase rules, and the size.
    remaining = sl.names_remaining(doc, all_names)
    text = json.dumps(doc, indent=1, ensure_ascii=False)
    tmp = os.path.join(tempfile.mkdtemp(prefix="showcase_"), "showcase.json")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text + "\n")
    violations = gate.check_showcase(tmp)
    print("names still present after redaction:", remaining, "; gate violations:", len(violations), "; bytes:", os.path.getsize(tmp), "; stand-ins used:", len(standins))
    if remaining:
        for path, how, length in sl.names_remaining_where(doc, all_names)[:12]:
            print("  still present:", how, "of length", length, "at", path[:140], "; ordinary across the catalogue:", "unknown")
        raise RuntimeError(f"{remaining} known contributor name(s) are still present: nothing was written")
    if violations:
        raise RuntimeError("licence gate (showcase): " + "; ".join(violations))

    if DRY:
        print("dry_run: nothing written")
    else:
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(os.path.join(OUT_DIR, "showcase.json"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text + "\n")
        print("written:", os.path.join(OUT_DIR, "showcase.json"))
    summary = json.dumps({"products": len(products), "stand_ins": len(standins), "names_remaining": remaining, "gate_violations": len(violations),
                          "bytes": os.path.getsize(tmp), "dry_run": DRY, "report": report})
except Exception as e:
    print("FAILED:", type(e).__name__, str(e)[:300])
    raise

# COMMAND ----------
# outside the try on purpose: dbutils.notebook.exit works by raising, and the handler above would report it as a failure
dbutils.notebook.exit(summary)
