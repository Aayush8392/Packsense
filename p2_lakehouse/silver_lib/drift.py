"""Schema-drift checks for silver: does today's data still look like the recent normal?

The problem: silver reads only the fields listed in contracts/silver.yml (an allowlist) and has explicit column types. If OFF renames
or restructures a field, nothing fails: the column simply arrives empty. These checks notice that.

Pure Python, no Spark: the notebook (notebooks/drift_check.py) runs the SQL built here, hands the numbers to `judge`, and stores the
findings. A "day" is one delta file. The baseline for a day is the last WINDOW earlier days of the same kind (delta days are never
compared with the seed from the full dump: a different population).

Two layers:
  1. Fields we use. Per day: the share of products with a value for each nullable contract column, the mix of nutrition formats
     (new / legacy / none), the products per day, the set of schema_version values. A share that falls clearly below the lowest recent
     day is an ALERT; a rise or a volume change is a WARN.
  2. Fields we do not use. Per run: OFF sends thousands of top-level field names, many generated per language or timestamp, so names are
     first grouped into families; a family never seen before is a WARN (silver drops it by design, nothing breaks; a human decides).
  3. How often the shape checks change a value. The notebook re-runs the silver transform in memory over each delta day (nothing is
     written to silver) and counts dropped tags, values that fail their column type, dropped nutrient entries and nulled enums. A rate
     (per 100 products) clearly above the highest recent day is an ALERT. This catches the partial breakage that layer 1 cannot see:
     a column whose share barely moves while more of its values stop fitting.
Limits: it sees presence and shape, not meaning (a field that keeps its name but changes unit is invisible); with fewer than
MIN_BASELINE earlier days it only records a warm-up; the thresholds below are judgement calls from 14 real days and are re-checked
as history grows (the window then moves with it).
"""
import re
from dataclasses import dataclass

MIN_BASELINE = 5         # earlier days needed before a day can be judged
WINDOW = 30              # how many earlier days form the baseline
MARGIN_POINTS = 5.0      # percentage points beyond the recent range before a share counts as changed
COLLAPSED = 0.25         # a share below this fraction of the lowest recent day is a collapse, if that low level meant at least...
MIN_EXPECTED_ROWS = 15   # ...this many products (so a column present on only 0.3% of 6,000 products is still watched, but not noise)
VOLUME_LOW, VOLUME_HIGH = 0.5, 2.0   # products per day outside [0.5 x lowest, 2 x highest] is a WARN
RATE_FACTOR = 3.0        # layer 3 (judgement call from 15 real days: 2.0 flagged traces_tags, which varies 0.3-3.4 per 100 day to day): an
RATE_FLOOR = 0.5         # ALERT needs a rate above this multiple of the highest recent day AND this many points per 100 above it, and...
MIN_RATE_COUNT = 15      # ...this many failures that day (a handful of odd values is noise)
ROWS_METRIC = "_rows"    # stored with every measured day: the products behind the counts, and the proof the day was measured
FORMATS = ("new", "legacy", "none")
COVERAGE_CLASSES = ("public", "hashed")


@dataclass(frozen=True)
class Finding:
    level: str            # ALERT | WARN | WARMUP
    check: str
    observed: float | None
    low: float | None
    high: float | None
    detail: str


# ---- which numbers are measured ---------------------------------------------------------------------------------------

def coverage_columns(contract: dict) -> list[str]:
    """Nullable contract columns of class public or hashed: those that can silently become empty."""
    return [c["name"] for c in contract["columns"] if c["class"] in COVERAGE_CLASSES and c["nullable"]]


def metrics_sql(contract: dict, table: str, prefix: str) -> str:
    """One row per silver source file whose name starts with prefix: products, share non-null per column, format mix, versions."""
    cov = ",\n  ".join(f"round(100 * avg(CASE WHEN `{c}` IS NOT NULL THEN 1 ELSE 0 END), 3) AS cov_{c}" for c in coverage_columns(contract))
    fmt = ",\n  ".join(f"round(100 * avg(CASE WHEN nutrition_format = '{f}' THEN 1 ELSE 0 END), 3) AS fmt_{f}" for f in FORMATS)
    p = prefix.replace("'", "''")
    return (f"SELECT source_file, count(*) AS rows,\n  {cov},\n  {fmt},\n"
            f"  concat_ws(',', sort_array(collect_set(CAST(schema_version AS STRING)))) AS schema_versions\n"
            f"FROM {table}\nWHERE left(source_file, {len(prefix)}) = '{p}'\nGROUP BY source_file\nORDER BY source_file")


def metrics_from_row(row: dict, columns: list[str]) -> dict:
    """The SQL row (column name -> value, numbers possibly as text) as the dict `judge` takes."""
    return {
        "file": row["source_file"], "rows": int(row["rows"]),
        "coverage": {c: float(row[f"cov_{c}"]) for c in columns},
        "format": {f: float(row[f"fmt_{f}"]) for f in FORMATS},
        "schema_versions": sorted(v for v in (row["schema_versions"] or "").split(",") if v),
    }


def measure(batch) -> dict[str, int]:
    """Counts for one measured day from a run.BatchResult: {metric: count}, only non-zero counts plus ROWS_METRIC.

    Metric names: coerce:<column or nutrient field> (a value did not fit its type and became NULL), tags:<column> (tags dropped by the
    shape check), nutrient_entries_dropped, enums_nulled. Counts only; no record content is ever kept.
    """
    out = {ROWS_METRIC: int(batch.rows_in)}
    for k, n in batch.coerce_failures.items():
        if n:
            out[f"coerce:{k}"] = int(n)
    for k, n in batch.tags_dropped.items():
        if n:
            out[f"tags:{k}"] = int(n)
    for k in ("nutrient_entries_dropped", "enums_nulled"):
        if getattr(batch, k):
            out[k] = int(getattr(batch, k))
    return out


def failures_by_file(rows) -> dict[str, dict[str, int]]:
    """Rows of silver_drift_metrics (source_file, metric, count) -> {file: {metric: count}}."""
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        out.setdefault(r["source_file"], {})[r["metric"]] = int(r["count"])
    return out


def attach_failures(days: list[dict], by_file: dict[str, dict[str, int]]) -> list[dict]:
    """Days (metrics dicts) with their measured counts under 'failures'; a day that was not measured stays without the key."""
    for d in days:
        if d["file"] in by_file:
            d["failures"] = by_file[d["file"]]
    return days


def _rate(counts: dict[str, int], metric: str) -> float:
    return 100.0 * counts.get(metric, 0) / counts[ROWS_METRIC]


def failure_findings(day: dict, earlier: list[dict]) -> list[Finding]:
    """Layer 3 for a measured day. Only a rise matters (a fall in failures is already visible as coverage or mix moving)."""
    hist = [e["failures"] for e in earlier if e.get("failures") and e["failures"].get(ROWS_METRIC)]
    if len(hist) < MIN_BASELINE:
        return [Finding("WARMUP", "failure_rates_baseline_short", float(len(hist)), float(MIN_BASELINE), None,
                        f"only {len(hist)} earlier measured day(s); {MIN_BASELINE} are needed before failure rates are judged")]
    today = day["failures"]
    out = []
    for metric in sorted(m for m in today if m != ROWS_METRIC):
        rates = [_rate(h, metric) for h in hist]
        lo, hi, rate = min(rates), max(rates), _rate(today, metric)
        if today[metric] >= MIN_RATE_COUNT and rate > max(RATE_FACTOR * hi, hi + RATE_FLOOR):
            out.append(Finding("ALERT", "failure_rate", rate, lo, hi,
                               f"{metric}: {today[metric]} of {today[ROWS_METRIC]} products ({rate:.2f} per 100), the recent days had {lo:.2f}-{hi:.2f}"))
    return out


# ---- layer 1: the fields we use ---------------------------------------------------------------------------------------

def band(values: list[float]) -> tuple[float, float]:
    return min(values), max(values)


def _share_change(name: str, kind: str, value: float, history: list[float], rows: int) -> Finding | None:
    """kind 'coverage': a drop is an ALERT, a rise a WARN. kind 'mix': a move either way is an ALERT.

    A drop is: more than MARGIN_POINTS below the lowest recent day, or (for rare columns that cannot fall that far) below COLLAPSED
    times the lowest recent day when that low level stood for at least MIN_EXPECTED_ROWS products.
    """
    lo, hi = band(history)
    dropped = value < lo - MARGIN_POINTS or (lo / 100 * rows >= MIN_EXPECTED_ROWS and value < COLLAPSED * lo)
    rose = value > hi + MARGIN_POINTS
    if kind == "coverage":
        if dropped:
            return Finding("ALERT", "coverage_drop", value, lo, hi, f"{name}: {value:.1f}% of products have a value, the recent days had {lo:.1f}-{hi:.1f}%")
        if rose:
            return Finding("WARN", "coverage_rise", value, lo, hi, f"{name}: {value:.1f}% of products have a value, the recent days had {lo:.1f}-{hi:.1f}%")
    elif dropped or rose:
        return Finding("ALERT", "format_mix", value, lo, hi, f"nutrition format '{name}': {value:.1f}% of products, the recent days had {lo:.1f}-{hi:.1f}%")
    return None


def judge(day: dict, earlier: list[dict]) -> list[Finding]:
    """Findings for one day against the earlier days (already limited to the window). [] means nothing drifted."""
    if len(earlier) < MIN_BASELINE:
        return [Finding("WARMUP", "baseline_too_short", float(len(earlier)), float(MIN_BASELINE), None,
                        f"only {len(earlier)} earlier day(s); {MIN_BASELINE} are needed before a day is judged")]
    out = []
    lo, hi = band([e["rows"] for e in earlier])
    if day["rows"] < VOLUME_LOW * lo or day["rows"] > VOLUME_HIGH * hi:
        out.append(Finding("WARN", "volume", float(day["rows"]), float(lo), float(hi), f"{day['rows']} products, the recent days had {lo}-{hi}"))
    for col, value in day["coverage"].items():
        history = [e["coverage"][col] for e in earlier if col in e["coverage"]]
        f = _share_change(col, "coverage", value, history, day["rows"]) if history else None
        if f:
            out.append(f)
    for fmt in FORMATS:
        f = _share_change(fmt, "mix", day["format"][fmt], [e["format"][fmt] for e in earlier], day["rows"])
        if f:
            out.append(f)
    seen = {v for e in earlier for v in e["schema_versions"]}
    for v in day["schema_versions"]:
        if v not in seen:
            out.append(Finding("ALERT", "schema_version", None, None, None, f"schema_version {v} was never seen in the recent days ({', '.join(sorted(seen))})"))
    if day.get("failures"):          # layer 3 runs only for measured days; a day without counts is judged by layers 1 and 2 as before
        out.extend(failure_findings(day, earlier))
    return out


def baseline_for(files: list[dict], index: int) -> list[dict]:
    """The earlier days for files[index]: up to WINDOW days before it in file-name order (names embed the delta's time range)."""
    return files[max(0, index - WINDOW):index]


# ---- layer 2: the fields we do not use --------------------------------------------------------------------------------

_DIGITS = re.compile(r"\d{6,}")      # timestamps and ids; short numbers (pnns_groups_1, _2) are real, different fields
_LANG = re.compile(r"(?<=_)[a-z]{2}(?=_|$)")


def field_family(name: str) -> str:
    """Group generated names: a run of 6+ digits becomes '#', a two-letter token after an underscore becomes <lang>.

    ingredients_text_de_ocr_1668029324_result -> ingredients_text_<lang>_ocr_#_result;  product_name_fr -> product_name_<lang>.
    A name without generated parts is its own family (lc, rev, nutrition, ...).
    """
    return _LANG.sub("<lang>", _DIGITS.sub("#", name))


def families(names) -> set[str]:
    return {field_family(n) for n in names}


def new_families(run_fields, known: set[str]) -> list[str]:
    """Families in this run that no earlier delta run had, sorted."""
    return sorted(families(run_fields) - known)


# ---- putting it together: what still has to be judged -----------------------------------------------------------------

def evaluate_pending(days: list[dict], evaluated: set[str], baseline_days: list[dict] | None = None) -> list[tuple[str, list[Finding]]]:
    """(file, findings) for every day not judged yet, in file-name order. A day with nothing to report gets one OK finding.

    days: metrics dicts sorted by file name. By default each day is judged against the days before it in the same list. With
    baseline_days (a different population, e.g. the daily files when judging the seed), the baseline is the last WINDOW of those.
    """
    out = []
    for i, day in enumerate(days):
        if day["file"] in evaluated:
            continue
        earlier = baseline_for(baseline_days, len(baseline_days)) if baseline_days is not None else baseline_for(days, i)
        findings = judge(day, earlier) or [Finding("OK", "all_checks", None, None, None, "nothing drifted")]
        out.append((day["file"], findings))
    return out


def family_pass(runs: list[dict], evaluated: set[str]) -> list[tuple[str, list[Finding]]]:
    """Layer 2 over silver runs of the daily files, oldest first: [{"run": id, "fields": [top-level field names]}].

    The first run only establishes what is known (a WARMUP finding, no judgement). Every later run not yet judged gets a WARN for each
    family no earlier run had, or one OK finding.
    """
    out, known = [], set()
    for i, run in enumerate(runs):
        fam = families(run["fields"])
        if run["run"] not in evaluated:
            if i == 0:
                out.append((run["run"], [Finding("WARMUP", "field_families", float(len(fam)), None, None,
                                                 f"first run: {len(fam)} field families recorded as the known set")]))
            else:
                new = sorted(fam - known)
                out.append((run["run"], [Finding("WARN", "new_field_family", None, None, None, f"new field family: {f}") for f in new]
                            or [Finding("OK", "field_families", float(len(fam)), None, None, "no new field family")]))
        known |= fam
    return out


def summary(findings: list[Finding], files: int, runs: int, limit: int = 6) -> str:
    """One short line for the healthchecks ping body (the full detail is in the report table)."""
    count = {lvl: sum(f.level == lvl for f in findings) for lvl in ("ALERT", "WARN", "WARMUP")}
    head = f"drift: {files} day(s) and {runs} run(s) judged; {count['ALERT']} alert, {count['WARN']} warn, {count['WARMUP']} warm-up"
    shown = [f.detail for f in findings if f.level == "ALERT"][:limit] or [f.detail for f in findings if f.level == "WARN"][:limit]
    return (head + ("; " + " | ".join(shown) if shown else ""))[:1000]
