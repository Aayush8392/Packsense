"""The privacy audit (P5 step 6): SQL that MEASURES how much personal-looking text is left in what we keep, the shaping of the results, and the
generated report PRIVACY_AUDIT.md. Everything here is counts. The queries run inside Databricks (the raw OFF record holds plaintext contributor
names): only integers come back, and a test checks that the stored result holds nothing but integers, a date and fixed labels.

Two kinds of claim, never mixed up:
  * the scrub patterns (email, URL, social link, @handle, Aadhaar, PAN, GSTIN, obfuscated email) are measured raw (bronze) against kept (silver);
  * the known-name bound: contributor names (every name in the raw contributor fields) found as whole words in the kept free text, outside
    ordinary words (a name that occurs in 10 or more products' text). Words are split at everything except letters, digits, underscore, dot and
    hyphen, so `name-bakery` and `name.com` do not count and a sentence-ending dot is ignored: the same rule as the pipeline's regex, applied by token.
These are bounds measured with Spark's regex engine on one date, not guarantees."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "p2_lakehouse"))
from silver_lib import contract as silver_contract  # noqa: E402

RESULT_PATH = HERE / "privacy_audit.json"
DOC_PATH = HERE.parent / "PRIVACY_AUDIT.md"
PATTERNS = ("email", "obfuscated_email", "social_link", "url", "at_handle", "aadhaar", "gstin", "pan")
DIGIT_SHAPES = {
    "run_7_plus": r"\d{7,}",
    "run_8": r"(?<!\d)\d{8}(?!\d)",
    "mobile_shape_10": r"(?<!\d)[6-9]\d{9}(?!\d)",
    "barcode_shape_13": r"(?<!\d)\d{13}(?!\d)",
}
SCALAR_FIELDS = ("creator", "last_editor", "last_checker", "owner", "last_modified_by")
ARRAY_FIELDS = ("editors_tags", "informers_tags", "checkers_tags", "correctors_tags", "photographers_tags", "weighers_tags", "owners_tags")
ORDINARY_MIN_PRODUCTS = 10
LABEL_RE = re.compile(r"^[a-z0-9_]+$")


def _raw(pattern: str) -> str:
    if "'" in pattern:
        raise ValueError("a pattern with a single quote cannot be written as a SQL raw string")
    return "r'" + pattern + "'"


def tables() -> dict:
    sc = silver_contract.load()
    return {"bronze": sc["source_table"], "silver": sc["table"], "quarantine": sc["quarantine_table"], "stats": sc["stats_table"],
            "patterns": {n: sc["scrub"][n] for n in PATTERNS}, "min_length": sc["own_handle_redaction"]["min_length"],
            "replacement": sc["scrub"]["replacement"]}


# --- the queries -------------------------------------------------------------------------------------------------------------------

def rows_sql(t: dict) -> str:
    return (f"SELECT (SELECT count(*) FROM {t['bronze']}) AS bronze_rows, (SELECT count(*) FROM {t['silver']}) AS silver_rows, "
            f"(SELECT count(*) FROM {t['quarantine']}) AS quarantine_rows, (SELECT count(DISTINCT code) FROM {t['silver']}) AS silver_codes")


def _flag(col: str, pattern: str) -> str:
    return f"CASE WHEN {col} RLIKE {_raw(pattern)} THEN 1 ELSE 0 END"


def pattern_counts_sql(t: dict, source: str) -> str:
    """Rows whose product_name / brands (or the quarantine payload) match each scrub pattern. source: bronze | silver | quarantine."""
    if source == "bronze":
        frm = f"(SELECT get_json_object(raw_json, '$.product_name') AS name, get_json_object(raw_json, '$.brands') AS brands FROM {t['bronze']})"
        cols = ("name", "brands")
    elif source == "silver":
        frm = f"(SELECT product_name AS name, brands AS brands FROM {t['silver']})"
        cols = ("name", "brands")
    else:
        frm = f"(SELECT payload AS name FROM {t['quarantine']})"
        cols = ("name",)
    parts = []
    for col in cols:
        for p, rx in t["patterns"].items():
            parts.append(f"sum({_flag(col, rx)}) AS {col}__{p}")
        any_rx = " OR ".join(f"{col} RLIKE {_raw(rx)}" for rx in t["patterns"].values())
        parts.append(f"sum(CASE WHEN {any_rx} THEN 1 ELSE 0 END) AS {col}__any")
        for s, rx in DIGIT_SHAPES.items():
            parts.append(f"sum({_flag(col, rx)}) AS {col}__{s}")
        if source == "silver":
            parts.append(f"sum(CASE WHEN {col} LIKE '%{t['replacement']}%' THEN 1 ELSE 0 END) AS {col}__replacement_marker")
    return f"SELECT {', '.join(parts)} FROM {frm}"


def known_names_sql(t: dict) -> str:
    """One query for both sources and both name classes. Counts rows (not names) with at least one non-ordinary hit."""
    scalars = ", ".join(f"get_json_object(raw_json, '$.{f}')" for f in SCALAR_FIELDS)
    arrays = " UNION ALL ".join(
        f"SELECT explode(from_json(get_json_object(raw_json, '$.{f}'), 'array<string>')) AS n FROM {t['bronze']}" for f in ARRAY_FIELDS)
    split = r"split(regexp_replace(lower({c}), r'[^\p{{L}}\p{{N}}_.-]+', ' '), ' ')"
    tok = "regexp_replace(t, r'\\.+$', '')"
    sources = []
    for src, frm in (
        ("bronze", f"SELECT '{{s}}' AS src, concat(code, '|', cast(last_modified_t AS string)) AS rid, "
                   f"get_json_object(raw_json, '$.product_name') AS name, get_json_object(raw_json, '$.brands') AS brands FROM {t['bronze']}"),
        ("silver", f"SELECT '{{s}}' AS src, concat(code, '|', cast(last_modified_t AS string)) AS rid, product_name AS name, brands AS brands FROM {t['silver']}"),
    ):
        sources.append(frm.replace("{s}", src))
    docs = " UNION ALL ".join(sources)
    return f"""
WITH people AS (
  SELECT lower(trim(n)) AS nm FROM (
    SELECT explode(array({scalars})) AS n FROM {t['bronze']}
    UNION ALL {arrays}
  ) WHERE n IS NOT NULL
),
names AS (
  SELECT DISTINCT nm, length(nm) AS len FROM people WHERE length(nm) BETWEEN 5 AND 100 AND nm RLIKE '^[a-z0-9_.-]+$'
),
docs AS ({docs}),
toks AS (
  SELECT src, rid, 'name' AS col, {tok} AS tok FROM (SELECT src, rid, explode({split.format(c='name')}) AS t FROM docs WHERE name IS NOT NULL)
  UNION ALL
  SELECT src, rid, 'brands' AS col, {tok} AS tok FROM (SELECT src, rid, explode({split.format(c='brands')}) AS t FROM docs WHERE brands IS NOT NULL)
),
hits AS (SELECT DISTINCT k.src, k.rid, k.col, k.tok, n.len FROM toks k JOIN names n ON k.tok = n.nm),
ordinary AS (SELECT src, tok FROM hits GROUP BY src, tok HAVING count(DISTINCT rid) >= {ORDINARY_MIN_PRODUCTS}),
flagged AS (
  SELECT h.src, h.rid, h.col, CASE WHEN h.len >= {t['min_length']} THEN '8_plus' ELSE '5_to_7' END AS cls, (o.tok IS NULL) AS non_ordinary
  FROM hits h LEFT JOIN ordinary o ON h.src = o.src AND h.tok = o.tok
)
SELECT src, cls,
  count(DISTINCT CASE WHEN col = 'name' AND non_ordinary THEN rid END) AS name_rows,
  count(DISTINCT CASE WHEN col = 'brands' AND non_ordinary THEN rid END) AS brands_rows,
  count(DISTINCT CASE WHEN non_ordinary THEN rid END) AS either_rows,
  count(DISTINCT CASE WHEN NOT non_ordinary THEN rid END) AS ordinary_only_rows
FROM flagged GROUP BY src, cls ORDER BY src, cls"""


def tags_dropped_sql(t: dict) -> str:
    return f"SELECT k, sum(v) AS dropped FROM (SELECT explode(tags_dropped) AS (k, v) FROM {t['stats']}) GROUP BY k ORDER BY k"


# --- shaping the answers ---------------------------------------------------------------------------------------------------------------

def _int(x) -> int:
    return int(x) if x is not None else 0


def shape_rows(row) -> dict:
    names = ("bronze_rows", "silver_rows", "quarantine_rows", "silver_codes")
    return {n: _int(v) for n, v in zip(names, row)}


def shape_patterns(names: list[str], row) -> dict:
    out: dict = {}
    for n, v in zip(names, row):
        col, key = n.split("__", 1)
        out.setdefault(col, {})[key] = _int(v)
    return out


def shape_known(rows) -> dict:
    out: dict = {}
    for src, cls, name_rows, brands_rows, either_rows, ordinary_only in rows:
        out.setdefault(cls, {})[src] = {"name": _int(name_rows), "brands": _int(brands_rows), "either": _int(either_rows),
                                        "ordinary_only": _int(ordinary_only)}
    return out


def shape_tags(rows) -> dict:
    return {k: _int(v) for k, v in rows if isinstance(k, str) and LABEL_RE.match(k)}


def measure(run, measured_at: str) -> dict:
    """run(sql) -> (column names, rows). Returns the result dict that is stored and rendered."""
    t = tables()
    _, r = run(rows_sql(t))
    result = {"measured_at": measured_at, "engine": "Databricks SQL, Spark regex engine", "rows": shape_rows(r[0]), "patterns": {}}
    for src in ("bronze", "silver", "quarantine"):
        cols, r = run(pattern_counts_sql(t, src))
        result["patterns"][src] = shape_patterns(cols, r[0])
    _, r = run(known_names_sql(t))
    result["known_names"] = {"ordinary_min_products": ORDINARY_MIN_PRODUCTS, **shape_known(r)}
    _, r = run(tags_dropped_sql(t))
    result["tags_dropped"] = shape_tags(r)
    return result


def only_counts(obj, path="") -> list[str]:
    """Problems with a stored result: anything that is not a date, a fixed label or an integer count."""
    bad = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str) or not LABEL_RE.match(k.replace("-", "_")):
                bad.append(f"{path}/{k}: key is not a plain label")
            if k in ("measured_at", "engine"):
                if not isinstance(v, str):
                    bad.append(f"{path}/{k}: must be text")
                continue
            bad += only_counts(v, f"{path}/{k}")
    elif not (isinstance(obj, int) and not isinstance(obj, bool)):
        bad.append(f"{path}: {type(obj).__name__} is not an integer count")
    return bad


def load_result(path: str | Path = RESULT_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# --- the report --------------------------------------------------------------------------------------------------------------------------

def pct(n: int, d: int) -> str:
    return f"{100.0 * n / d:.3f}%" if d else "n/a"


def render(res: dict) -> str:
    rows, pat, known = res["rows"], res["patterns"], res["known_names"]
    b, s = rows["bronze_rows"], rows["silver_rows"]
    t = tables()
    L = [f"""# Privacy audit

*Generated by `p5_governance/bootstrap/render_privacy_audit.py` from `p5_governance/privacy_audit.json`, which `p5_governance/bootstrap/privacy_audit.py`
measures on production (read-only; **counts only**, no value or name is read out). Measured **{res['measured_at']}** with {res['engine']}. Do not edit by hand.*

## What this is, and what it is not
It reports how much personal-looking text is still in what the pipeline keeps, **measured on all rows**, as bounds. It is **not a guarantee**:
- OFF publishes contributor usernames and contributions are public and irrevocable, so the hashed contributor codes protect only against our own readers.
  The design never claims anonymisation, and pseudonymised data remains personal data.
- Free text is kept in two silver columns only (`product_name`, `brands`). Everything else that could carry text is dropped, shape-checked or replaced by a fingerprint.
- Patterns are measured with Spark's regex engine (`\\w` is ASCII), the pipeline scrubs with Python's: the two can differ on accented text.
- A pattern with a clear shape is scrubbed. **Phone numbers are not scrubbed by pattern** (a liberal pattern also deletes dates and lot codes); they are counted by shape below.
- This audit says nothing about the correctness of any value, only about personal-looking text.

## Rows measured
{b:,} bronze rows (versions of {rows['silver_codes']:,} products in silver), {s:,} silver rows, {rows['quarantine_rows']:,} quarantined rows.

## Contact-shaped text: raw against kept
Rows with at least one match, in the raw record (bronze) and in the kept column (silver, after the scrub). The scrub is **field-aware**: it runs on `product_name` and `brands` only.

| Pattern | bronze name | bronze brands | silver name | silver brands |
|---|---|---|---|---|"""]
    for p in (*PATTERNS, "any"):
        L.append(f"| {p} | {pat['bronze']['name'][p]:,} | {pat['bronze']['brands'][p]:,} | {pat['silver']['name'][p]:,} | {pat['silver']['brands'][p]:,} |")
    sn, sb = pat["silver"]["name"], pat["silver"]["brands"]
    L.append(f"""
Raw rows with any match: name {pct(pat['bronze']['name']['any'], b)}, brands {pct(pat['bronze']['brands']['any'], b)}. After the scrub: name {pct(sn['any'], s)} ({sn['any']:,} rows), brands {pct(sb['any'], s)} ({sb['any']:,} rows).
The replacement marker `{t['replacement']}` is in {sn['replacement_marker']:,} names and {sb['replacement_marker']:,} brands: those are the scrubbed hits.

## Long digit runs and phone-shaped values (NOT scrubbed, by design)
| Shape | silver name | silver brands |
|---|---|---|""")
    for k, label in (("run_7_plus", "7+ digits in a row"), ("run_8", "exactly 8 digits"), ("mobile_shape_10", "10 digits starting 6 to 9 (an Indian mobile shape)"), ("barcode_shape_13", "exactly 13 digits (a barcode shape)")):
        L.append(f"| {label} | {sn[k]:,} ({pct(sn[k], s)}) | {sb[k]:,} ({pct(sb[k], s)}) |")
    L.append("""
Most of these are quantities, lot codes and barcodes; the mobile-shaped row is the upper bound on phone-shaped values in kept text (by shape, not verified by eye).

## Contributor names in kept free text (the known-name bound)""")
    mp = known["ordinary_min_products"]
    L.append(f"""Every name in the raw contributor fields is looked for as a whole word in `product_name` and `brands`. A name that occurs in the text of {mp} or more products is
treated as an **ordinary word** (chocolat, carrefour...) and not counted. Names of 8+ characters are the ones the pipeline replaces in `product_name` when they are the
record's OWN contributors (`brands` is exempt: producer accounts write their own brand); names of 5 to 7 characters are **counted, not replaced** (mostly brand words).

| Names | Where | Source | Rows with a non-ordinary hit | Rows with only ordinary hits |
|---|---|---|---|---|""")
    for cls, label in (("8_plus", "8+ characters"), ("5_to_7", "5 to 7 characters")):
        for src, total in (("bronze", b), ("silver", s)):
            v = known[cls][src]
            L.append(f"| {label} | product_name | {src} | {v['name']:,} ({pct(v['name'], total)}) | |")
            L.append(f"| {label} | brands | {src} | {v['brands']:,} ({pct(v['brands'], total)}) | |")
            L.append(f"| {label} | either | {src} | {v['either']:,} ({pct(v['either'], total)}) | {v['ordinary_only']:,} |")
    k8s = known["8_plus"]["silver"]
    L.append(f"""
**The bound:** after the pipeline, at most {k8s['name']:,} silver product names ({pct(k8s['name'], s)}) and {k8s['brands']:,} brands ({pct(k8s['brands'], s)}) contain a known contributor name of 8 or more
characters outside ordinary words. That counts every name in the catalogue, not only the record's own contributors, and includes names that are also real brand or product words.

## Tags dropped by the shape rule
Counted over every silver run (values that failed their closed vocabulary and were dropped, never kept):

| Column | Dropped |
|---|---|""")
    for k, v in sorted(res["tags_dropped"].items()):
        L.append(f"| `{k}` | {v:,} |")
    q = pat["quarantine"]["name"]
    L.append(f"""
## Quarantine
{rows['quarantine_rows']:,} records could not be loaded; {q['any']:,} of their payloads match a scrub pattern. The payload is classed **personal** in `DATA_CLASSIFICATION.md`, and
analysts and gold are denied the table (grants and nightly policy checks).

## What was not measured
- Free text in fields silver does not keep (ingredients text, customer-service fields): not kept, so not in scope; ingredients are replaced by a fingerprint.
- Images: the licence gate forbids them in every public output (see `p5_governance/licence_gate.py`).
- Names shorter than 5 characters, and contributor names in other languages or spellings than the one recorded.
- A name hidden inside a longer word or joined by a hyphen or dot (`name-bakery`, `name.com`): by the whole-word rule these are not counted.
""")
    return "\n".join(L)
