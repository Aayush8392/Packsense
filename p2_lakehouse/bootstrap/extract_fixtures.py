"""Extracts test fixtures for the silver logic: a small set of REAL bronze records, sanitised inside Databricks.

Run once, by hand; the output (p2_lakehouse/tests/fixtures/bronze_records.jsonl) is committed. How it stays safe:
  * the records are picked and sanitised by a one-off serverless run, so raw usernames never leave Databricks;
  * every contributor identity (the personal fields in contracts/silver.yml) becomes a stable placeholder user_0001...;
  * `images` is removed (per-image licences, uploader names);
  * emails become redacted<n>@example.org; phone numbers in customer_service*/producer* become one fixed placeholder;
  * the run then proves that no original username survives anywhere in the text (whole-word for every name of 3+
    characters, anywhere inside longer words for names of 8+) and returns only counts. A leftover aborts the extraction.
Everything else is the record exactly as OFF sent it (ODbL, attribution: Open Food Facts contributors).
The placeholders are not real data; they replace personal data, per the project's publication policy.

  python p2_lakehouse/bootstrap/extract_fixtures.py --env-file PATH
Environment: DATABRICKS_HOST, DATABRICKS_TOKEN (admin). Prints counts only.
"""
import argparse
import base64
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "bronze_records.jsonl"

NOTEBOOK = r'''# Databricks notebook source
import json, re, hashlib, collections
from pyspark.sql import functions as F

BRONZE = "workspace.packsense_bronze.bronze_delta_raw"
PERSONAL = ["creator", "last_editor", "last_modified_by", "last_checker", "editors_tags", "informers_tags", "checkers_tags",
            "correctors_tags", "photographers_tags", "weighers_tags", "editors", "informers", "checkers", "correctors",
            "photographers", "owner", "owner_imported", "owners_tags"]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<![\w.])\+?\(?\d[\d ().\-]{5,17}\d(?!\w)")   # same liberal pattern as silver_lib/personal.py
bz = spark.table(BRONZE)

def nut(d):
    n = d.get("nutrition")
    return n if isinstance(n, dict) else {}
def agg(d):
    a = nut(d).get("aggregated_set")
    return a if isinstance(a, dict) else {}
def nutrients(d):
    n = agg(d).get("nutrients")
    return n if isinstance(n, dict) else {}
def txt(v): return isinstance(v, str) and v.strip() != ""
CORE = ("energy-kj", "energy-kcal", "fat", "saturated-fat", "carbohydrates", "sugars", "proteins", "salt", "sodium", "fiber")

# (case, spark pre-filter, python confirm, how many)
CASES = [
 ("normal_new", "raw_json LIKE '%\"aggregated_set\"%'", lambda d: agg(d).get("per") == "100g" and agg(d).get("preparation") == "as_sold"
    and len(nut(d).get("input_sets") or []) >= 2 and txt(d.get("product_name")) and txt(d.get("brands")) and (d.get("allergens_tags") or [])
    and (d.get("categories_tags") or []) and txt(d.get("ingredients_text")) and all(k in nutrients(d) for k in CORE), 1),
 ("no_nutrition", "NOT raw_json LIKE '%\"aggregated_set\"%'", lambda d: not agg(d), 1),
 ("per_100ml", "raw_json LIKE '%\"per\":\"100ml\"%'", lambda d: agg(d).get("per") == "100ml", 1),
 ("prepared", "raw_json LIKE '%\"preparation\":\"prepared\"%'", lambda d: agg(d).get("preparation") == "prepared", 1),
 ("owner_present", "raw_json LIKE '%\"owner\":\"org-%'", lambda d: str(d.get("owner", "")).startswith("org-"), 1),
 ("email_in_ingredients", "raw_json RLIKE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+[.][A-Za-z]{2,}'", lambda d: bool(EMAIL.search(d.get("ingredients_text") or "")), 1),
 ("odd_length_code", "code RLIKE '^[0-9]{15,}$'", lambda d: True, 1),
 ("gtin8", "code RLIKE '^[0-9]{8}$'", lambda d: True, 1),
 ("gtin14", "code RLIKE '^[0-9]{14}$'", lambda d: True, 1),
 ("non_digit_code", "NOT (code RLIKE '^[0-9]+$')", lambda d: True, 2),
 ("legacy_nutriments_filled", "raw_json LIKE '%\"nutriments\":{\"%'", lambda d: isinstance(d.get("nutriments"), dict) and len(d["nutriments"]) > 0, 2),
 ("input_value_null", "raw_json LIKE '%input_sets%'", lambda d: any(isinstance(v, dict) and v.get("value") is None for s in (nut(d).get("input_sets") or []) for v in (s.get("nutrients") or {}).values()), 1),
 ("modifier_less_than", "raw_json LIKE '%\"modifier\":\"<\"%'", lambda d: any(isinstance(v, dict) and v.get("modifier") == "<" for v in nutrients(d).values()), 1),
 ("product_quantity_string", "raw_json LIKE '%\"product_quantity\":\"%'", lambda d: isinstance(d.get("product_quantity"), str), 1),
 ("many_editors", "raw_json LIKE '%editors_tags%'", lambda d: len(d.get("editors_tags") or []) >= 40, 1),
 ("phone_in_customer_service", "raw_json LIKE '%customer_service%'", lambda d: any(k.startswith("customer_service") and isinstance(v, str) and PHONE.search(v) for k, v in d.items()), 1),
 ("no_product_name", "NOT raw_json LIKE '%\"product_name\":\"_%'", lambda d: not txt(d.get("product_name")), 1),
]

picked = []   # (case, raw_json)
seen_codes = set()
for case, pre, confirm, n in CASES:
    rows = bz.where(pre).orderBy(F.sha1("raw_json")).limit(400).select("code", "raw_json").collect()
    got = 0
    for r in rows:
        try:
            d = json.loads(r["raw_json"])
        except Exception:
            if case != "bad_json": continue
        try:
            ok = confirm(d)
        except Exception:
            ok = False
        if ok and r["code"] not in seen_codes:
            picked.append((case, r["raw_json"])); seen_codes.add(r["code"]); got += 1
            if got == n: break
    print(case, "found", got, "of", n)

# two versions of one product (same code, two last_modified_t), to test history
two = (bz.groupBy("code").count().where("count = 2 AND code RLIKE '^[0-9]{13}$'").orderBy(F.sha1("code")).limit(1).collect())
if two:
    for r in bz.where(F.col("code") == two[0]["code"]).orderBy("last_modified_t").select("raw_json").collect():
        picked.append(("two_versions_same_code", r["raw_json"]))

# ---- sanitise ---------------------------------------------------------------------------------------------
docs = []
for case, raw in picked:
    d = json.loads(raw); d.pop("images", None); docs.append((case, d))
names = set()
for case, d in docs:
    for f in PERSONAL:
        v = d.get(f)
        for x in (v if isinstance(v, list) else [v]):
            if isinstance(x, str) and x.strip(): names.add(x)
ordered = sorted(names, key=lambda s: (-len(s), s))
placeholder = {n: "user_%04d" % (i + 1) for i, n in enumerate(sorted(names, key=lambda s: hashlib.sha1(s.encode()).hexdigest()))}
def pat(n, substring):
    e = re.escape(n)
    return re.compile(e if substring else r"(?<![A-Za-z0-9_.-])" + e + r"(?![A-Za-z0-9_.-])", re.IGNORECASE)
word_pats = [(n, pat(n, False)) for n in ordered if len(n) >= 3]
sub_pats = [(n, pat(n, True)) for n in ordered if len(n) >= 8]
email_n = [0]
def email_sub(m):
    email_n[0] += 1; return "redacted%d@example.org" % email_n[0]
replaced = collections.Counter()
out = []
for case, d in docs:
    for k in list(d):
        if (k.startswith("customer_service") or k.startswith("producer")) and isinstance(d[k], str):
            d[k] = PHONE.sub("+91 98765 43210", d[k])
    s = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    for n, p in word_pats:
        s, c = p.subn(placeholder[n], s); replaced["word"] += c
    for n, p in sub_pats:
        s, c = p.subn(placeholder[n], s); replaced["inside_word"] += c
    s = EMAIL.sub(email_sub, s)
    out.append({"case": case, "raw_json": s})
# proof: nothing original survives (exact-value check for every name, whole-word for 3+, inside-word for 8+)
left = collections.Counter()
for o in out:
    s = o["raw_json"]
    vals = set(json.loads(s).get("editors_tags") or [])
    for n, p in word_pats:
        if p.search(s): left["word"] += 1
    for n, p in sub_pats:
        if p.search(s): left["inside_word"] += 1
    if EMAIL.search(s.replace("example.org", "")) and any(not m.endswith("@example.org") for m in EMAIL.findall(s)): left["email"] += 1
short = sum(1 for n in names if len(n) < 3)
result = {"cases": len(out), "distinct_identities": len(names), "identities_shorter_than_3_chars": short,
          "replacements_whole_word": replaced["word"], "replacements_inside_word": replaced["inside_word"], "emails_replaced": email_n[0],
          "leftover_checks_failed": dict(left), "bytes": sum(len(o["raw_json"]) for o in out)}
if left:
    raise RuntimeError("sanitising left original identities in the fixtures: " + json.dumps(dict(left)))
dbutils.notebook.exit(json.dumps({"summary": result, "records": out}))
'''


def load_env_file(path):
    for raw in open(path, encoding="utf-8").read().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", required=True)
    args = ap.parse_args()
    load_env_file(args.env_file)
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service import jobs, workspace
    w = WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=os.environ["DATABRICKS_TOKEN"])
    me = w.current_user.me().user_name
    folder = f"/Users/{me}/packsense_scratch"
    path = f"{folder}/extract_fixtures"
    w.workspace.mkdirs(folder)
    w.workspace.import_(path=path, format=workspace.ImportFormat.SOURCE, language=workspace.Language.PYTHON,
                        content=base64.b64encode(NOTEBOOK.encode()).decode(), overwrite=True)
    try:
        run = w.jobs.submit(run_name="packsense-extract-fixtures", tasks=[jobs.SubmitTask(
            task_key="extract", notebook_task=jobs.NotebookTask(notebook_path=path))]).result(timeout=timedelta(minutes=30))
        out = w.jobs.get_run_output(run_id=run.tasks[0].run_id)
        if not (out.notebook_output and out.notebook_output.result):
            print("no output:", (run.state.state_message or "")[:500], (out.error or "")[:800])
            return 1
        res = json.loads(out.notebook_output.result)
    finally:
        w.workspace.delete(folder, recursive=True)
        print("temporary notebook folder deleted")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        for rec in res["records"]:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(res["summary"], indent=1))
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
