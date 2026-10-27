"""Flag history from OFF's dated Hugging Face snapshots (P9 operations; roadmap Phase A).

Why this exists: the flag-fix label needs to know when a flag was on a product and when it went away, and our own daily deltas only start on
30 Sep and rarely show a product before its fix. OFF's dataset `openfoodfacts/product-database` is rebuilt about twice a day and every build
is a git commit, so a dated snapshot of the whole catalogue can be read back for about a year. We read a small number of columns of a weekly
snapshot with DuckDB, compare consecutive snapshots and keep only the CHANGES (flag appeared or disappeared, product left), never the snapshots.

What is measured (2026-10-20, three snapshots 1, 10 and 19 Oct): one snapshot costs about 310 MB for these columns and about 190 s on
Databricks; the Hugging Face resolver allows 3,000 requests per 5 minutes, so the signed CDN address is resolved once and read directly.
What is not known: Databricks Free Edition publishes no storage or daily compute cap, so every run is bounded on our side (byte guard per
snapshot, a cap on pairs per run, a rolling retention of the event tables).

Everything here is plain Python except `compute_pair`, which takes a DuckDB connection; the notebook does the network and Delta work.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import threading
import urllib.error
import urllib.request

REPO = "openfoodfacts/product-database"
UA = {"User-Agent": "packsense-snapshots/0.1 (portfolio project)"}
# (column alias in the loaded table, severity name, column in OFF's Parquet)
SEVERITIES = (
    ("e", "error", "data_quality_errors_tags"),
    ("w", "warning", "data_quality_warnings_tags"),
    ("i", "info", "data_quality_info_tags"),
)
FEATURE_GUARD = 1_500_000_000   # the feature read (nutrition, brands, categories): measured 2026-10-26 at about 380 MB over the footer; a read past 1.5 GB is stopped
BYTE_GUARD = 1_000_000_000      # one snapshot is ~310 MB for these columns; a read that passes 1 GB is stopped
RETENTION_MONTHS = 13           # flag events older than this (by the newer snapshot's date) are deleted at the end of a run

DEFAULT_SCHEMA = "workspace.packsense_snapshots"
TABLES = ("snapshot_flag_events", "snapshot_open_counts", "snapshot_presence_events", "snapshot_manifest",
          "snapshot_open_flags", "snapshot_features", "snapshot_open_flags_manifest")

# The open flags kept per product for the triage model (roadmap item 17, agreed 2026-10-26): every error flag, and the warning flags of the
# nutrition-number families the labelling gate covers. Measured 2026-10-18: 259,679 error and 647,429 such warning flags open in one snapshot,
# against 21.5 million warnings in all (13 million of them OFF's computed environmental-score and ecoscore warnings, which no editor fixes).
WARNING_SCOPE = re.compile(r"^(?:value-very-(?:high|low)-for-category-.+|value-under-0-0*1-g-salt|3-or-more-values-are-identical)$")
WARNING_SCOPE_SQL = "value-very-(high|low)-for-category-|value-under-0-0*1-g-salt|3-or-more-values-are-identical"   # unanchored prefilter in DuckDB


def in_flag_scope(severity: str, tag: str) -> bool:
    """Whether an open flag is kept in `snapshot_open_flags`: any error, or a warning whose family is in WARNING_SCOPE."""
    if severity == "error":
        return True
    return severity == "warning" and bool(WARNING_SCOPE.match(family_key(tag)))


# --- the flag family -----------------------------------------------------------------------------------------------------------------------
# OFF writes one check under several tags: a plain tag (`en:nutrition-value-total-over-105`) and one per nutrition source and basis
# (`en:nutrition-packaging-as-sold-100g-value-total-over-105`). A product that moves from the plain tag to the source tag has not been
# fixed, so the label is built on the FAMILY, the tag with the source and basis stripped. Measured 2026-10-20: 176 of 215 'gone but still
# violating' error cases were exactly this move.

# The per-source tags seen on 2026-10-20 (1,538 distinct tags in two snapshots): source `packaging` or `manufacturer`, `as-sold` or (without `as-`)
# `prepared`, basis `100g`, `100ml`, `serving`, `100kj`, `100-` or `100mmol-l`.
_SOURCE_TAG = re.compile(r"^nutrition-[a-z0-9]+-(?:as-)?(?:sold|prepared)-(?:serving|100[a-z]*(?:-l)?-?)-")
_LEFTOVER = re.compile(r"(?:^|-)(?:as-)?(?:sold|prepared)-(?:serving|100)")


def family_key(tag: str) -> str:
    """`en:nutrition-packaging-as-sold-100g-value-total-over-105` and `en:nutrition-value-total-over-105` both give `value-total-over-105`;
    a tag with no such prefix keeps its text (without the language prefix)."""
    body = tag.split(":", 1)[1] if ":" in tag else tag
    stripped = _SOURCE_TAG.sub("", body, count=1)
    if stripped != body:
        return stripped
    return body[len("nutrition-"):] if body.startswith("nutrition-") else body


def looks_unparsed(tag: str) -> bool:
    """True when the family still carries a source/basis marker: OFF added a source or basis this module does not know. Such a tag would be
    mistaken for its own family, so the notebook counts them and a test asserts there are none among the real tags."""
    return bool(_LEFTOVER.search(family_key(tag)))


# --- which snapshots ----------------------------------------------------------------------------------------------------------------------

class Snapshot:
    __slots__ = ("sha", "date")

    def __init__(self, sha: str, date: dt.datetime):
        self.sha, self.date = sha, date

    def __repr__(self):
        return f"Snapshot({self.sha[:8]}, {self.date.isoformat()})"

    def __eq__(self, other):
        return isinstance(other, Snapshot) and (self.sha, self.date) == (other.sha, other.date)


def parse_commit_date(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


def weekly_targets(now: dt.datetime, weeks: int) -> list[dt.datetime]:
    """Monday 00:00 UTC of the current week and of each of the `weeks` weeks before it, oldest first. Anchored to Mondays so that a rerun
    on any day picks the same snapshots (and therefore the same pair ids)."""
    now = now.astimezone(dt.timezone.utc)
    monday = (now - dt.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return [monday - dt.timedelta(weeks=k) for k in range(weeks, -1, -1)]


def pick_snapshots(commits: list[dict], targets: list[dt.datetime]) -> list[Snapshot]:
    """For every target time the newest commit made at or before it. A target older than the oldest commit is skipped; neighbours that pick the
    same commit are kept once. `commits` are Hugging Face's commit records ({'id', 'date'}), in any order."""
    dated = sorted(((parse_commit_date(c["date"]), c["id"]) for c in commits), reverse=True)
    out: list[Snapshot] = []
    for target in targets:
        for date, sha in dated:
            if date <= target:
                if not out or out[-1].sha != sha:
                    out.append(Snapshot(sha, date))
                break
    return out


def pair_id(a: Snapshot, b: Snapshot) -> str:
    return f"{a.sha[:12]}_{b.sha[:12]}"


def pairs_to_do(snapshots: list[Snapshot], done: set[str], max_pairs: int) -> list[tuple[Snapshot, Snapshot]]:
    """Consecutive pairs (oldest first) whose id is not in `done`, at most `max_pairs`."""
    out = []
    for a, b in zip(snapshots, snapshots[1:]):
        if pair_id(a, b) not in done:
            out.append((a, b))
        if len(out) >= max_pairs:
            break
    return out


def retention_cutoff(now: dt.datetime, months: int = RETENTION_MONTHS) -> dt.date:
    """The date `months` calendar months before `now` (the day clipped to the month's length); events with a newer-snapshot date before it go."""
    y, m = now.year, now.month - months
    while m <= 0:
        y, m = y - 1, m + 12
    last = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)).day
    return dt.date(y, m, min(now.day, last))


# --- the network --------------------------------------------------------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch_commits(pages: int = 4, opener=urllib.request.urlopen) -> list[dict]:
    """Hugging Face's commit list for the dataset, newest first, 50 per page (about two commits a day: 4 pages are about 100 days)."""
    out: list[dict] = []
    for p in range(pages):
        req = urllib.request.Request(f"https://huggingface.co/api/datasets/{REPO}/commits/main?p={p}&limit=50", headers=UA)
        got = json.load(opener(req))
        out += got
        if len(got) < 50:
            break
    return out


def resolve_cdn(sha: str, build_opener=urllib.request.build_opener) -> str:
    """One request to Hugging Face's resolver for `food.parquet` at a commit; returns the signed CDN address it redirects to. Reading that
    address directly spends none of the resolver's quota (3,000 requests per 5 minutes, measured) on the thousands of range reads."""
    url = f"https://huggingface.co/datasets/{REPO}/resolve/{sha}/food.parquet"
    try:
        build_opener(_NoRedirect).open(urllib.request.Request(url, method="HEAD", headers=UA))
    except urllib.error.HTTPError as e:
        if e.code == 302 and e.headers.get("location"):
            return e.headers["location"]
        raise
    return url


def snapshot_size(sha: str, build_opener=urllib.request.build_opener, opener=urllib.request.urlopen) -> int | None:
    """The byte size of `food.parquet` at a commit, from one HEAD request on the CDN address (nothing is downloaded); None if it cannot be read."""
    try:
        req = urllib.request.Request(resolve_cdn(sha, build_opener), method="HEAD", headers=UA)
        return int(opener(req).headers["Content-Length"])
    except (urllib.error.URLError, KeyError, TypeError, ValueError):
        return None


def newest_complete(commits: list[dict], size_of, look: int = 6, min_ratio: float = 0.9) -> tuple[dict, list[dict]]:
    """The newest of the first `look` commits whose file is at least `min_ratio` of the MEDIAN size of those commits, and the newer ones skipped as too small.
    On 2026-10-27 OFF published a 4.3 GB file between 8.0 GB ones; a deletion check on it listed 138,395 live products as missing. A size that cannot be read
    is skipped (a commit we cannot measure is not trusted); raises if no commit qualifies."""
    sized = [(c, size_of(c["id"])) for c in commits[:look]]
    known = sorted(s for _, s in sized if s)
    if not known:
        raise RuntimeError("cannot read the size of any recent snapshot")
    median = known[len(known) // 2] if len(known) % 2 else (known[len(known) // 2 - 1] + known[len(known) // 2]) / 2
    skipped = []
    for c, s in sized:
        if s and s >= min_ratio * median:
            return c, skipped
        skipped.append({"sha": c["id"][:8], "date": c["date"], "bytes": s, "median_bytes": int(median)})
    raise RuntimeError(f"no recent snapshot is at least {min_ratio:.0%} of the median size ({median / 1e9:.2f} GB)")


class ByteGuard:
    """Stops a read that downloads more than `limit` bytes: a watcher thread compares the machine's received bytes with the count at the start
    and calls `interrupt` once. Used around every snapshot load, because Databricks Free Edition publishes no limit of its own."""

    def __init__(self, read_rx, limit: int, interrupt, poll: float = 1.0):
        self.read_rx, self.limit, self.interrupt, self.poll = read_rx, limit, interrupt, poll
        self.tripped = False
        self._done = threading.Event()
        self._start = 0
        self._thread: threading.Thread | None = None

    def __enter__(self):
        self._start = self.read_rx()
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()
        return self

    def _watch(self):
        while not self._done.wait(self.poll):
            if self.read_rx() - self._start > self.limit:
                self.tripped = True
                self.interrupt()
                return

    def __exit__(self, *exc):
        self._done.set()
        if self._thread:
            self._thread.join(timeout=5)
        return False

    def received(self) -> int:
        return self.read_rx() - self._start


def read_rx_bytes(path: str = "/proc/net/dev") -> int:
    """Bytes received on every interface except loopback (Linux: the Databricks driver)."""
    total = 0
    with open(path) as fh:
        for line in fh.read().splitlines()[2:]:
            name, rest = line.split(":", 1)
            if name.strip() != "lo":
                total += int(rest.split()[0])
    return total


# --- tables -------------------------------------------------------------------------------------------------------------------------------

def ddl(schema: str) -> dict[str, str]:
    """CREATE TABLE statements, keyed by table name. `schema` is `catalog.schema`."""
    return {
        "snapshot_flag_events": f"""CREATE TABLE IF NOT EXISTS {schema}.snapshot_flag_events (
            pair_id STRING, date_from DATE, date_to DATE, code STRING, severity STRING, flag STRING, family STRING, event STRING,
            family_remains BOOLEAN, edited BOOLEAN, lm_from BIGINT, lm_to BIGINT) USING DELTA""",
        "snapshot_open_counts": f"""CREATE TABLE IF NOT EXISTS {schema}.snapshot_open_counts (
            snapshot_sha STRING, snapshot_date DATE, severity STRING, flag STRING, family STRING, open_pairs BIGINT) USING DELTA""",
        "snapshot_open_flags": f"""CREATE TABLE IF NOT EXISTS {schema}.snapshot_open_flags (
            snapshot_sha STRING, snapshot_date DATE, code STRING, severity STRING, flag STRING, family STRING, lm BIGINT) USING DELTA""",
        "snapshot_features": f"""CREATE TABLE IF NOT EXISTS {schema}.snapshot_features (
            snapshot_sha STRING, snapshot_date DATE, code STRING, lm BIGINT, serving_size STRING, brand STRING, categories ARRAY<STRING>,
            nutrients MAP<STRING, DOUBLE>, n_nutrients INT, max_mass_g DOUBLE,
            created_t BIGINT, last_updated_t BIGINT, data_sources_tags ARRAY<STRING>, popularity_key BIGINT, scans_n INT, unique_scans_n INT,
            completeness DOUBLE, states_tags ARRAY<STRING>, labels_tags ARRAY<STRING>, countries_tags ARRAY<STRING>, last_image_t BIGINT,
            max_imgid INT, nutriscore_grade STRING, nova_group INT, rev INT) USING DELTA""",
        "snapshot_open_flags_manifest": f"""CREATE TABLE IF NOT EXISTS {schema}.snapshot_open_flags_manifest (
            snapshot_sha STRING, snapshot_date DATE, flag_rows BIGINT, products_with_flags BIGINT, products_in_snapshot BIGINT,
            rx_mb BIGINT, seconds DOUBLE, job_run_id STRING, finished_at TIMESTAMP, feature_rows BIGINT, products_with_nutrients BIGINT,
            columns_version INT) USING DELTA""",
        "snapshot_presence_events": f"""CREATE TABLE IF NOT EXISTS {schema}.snapshot_presence_events (
            pair_id STRING, date_from DATE, date_to DATE, code STRING, event STRING, lm_from BIGINT) USING DELTA""",
        "snapshot_manifest": f"""CREATE TABLE IF NOT EXISTS {schema}.snapshot_manifest (
            pair_id STRING, snapshot_from STRING, snapshot_to STRING, date_from DATE, date_to DATE, rows_from BIGINT, rows_to BIGINT,
            in_both BIGINT, left_count BIGINT, entered_count BIGINT, edited_count BIGINT, flag_events BIGINT,
            rx_mb BIGINT, seconds DOUBLE, job_run_id STRING, finished_at TIMESTAMP) USING DELTA""",
    }


def ddl_columns(sql: str) -> list[str]:
    body = sql[sql.index("(") + 1: sql.rindex(")")]
    return [p.split()[0] for p in body.split(",") if p.strip()]


# --- loading and comparing (DuckDB) -------------------------------------------------------------------------------------------------------

def load_sql(table: str, url: str) -> str:
    """Create `table` from one snapshot: only the columns that matter, one row per barcode (OFF's Parquet has about 60 duplicates)."""
    cols = ", ".join(f"{c} as {a}" for a, _, c in SEVERITIES)
    return (f"create table {table} as select code, last_modified_t as lm, {cols} from read_parquet('{url}') "
            f"qualify row_number() over (partition by code order by last_modified_t desc) = 1")


def open_counts(con, table: str) -> list[tuple[str, str, int]]:
    """(severity, tag, number of products carrying it) for one loaded snapshot. A tag listed twice on one product counts once (OFF's lists
    can repeat a tag: seen on 2026-10-20 in `en:nutri-score-grade-from-label-does-not-match-calculated-grade`)."""
    rows = []
    for alias, sev, _ in SEVERITIES:
        for tag, n in con.execute(f"select tag, count(*) from (select unnest(list_distinct({alias})) as tag from {table}) group by 1").fetchall():
            rows.append((sev, tag, n))
    return rows


def open_flag_rows(con, table: str) -> tuple[list[list], int, int]:
    """([code, lm, severity, tag, family] for every open flag in scope, products with such a flag, products in the snapshot). One row per
    product and distinct tag; the family is computed here (it needs `family_key`), the scope prefilter for warnings runs in DuckDB."""
    rows: list[list] = []
    for alias, sev, _ in SEVERITIES:
        if sev == "error":
            where = ""
        elif sev == "warning":
            where = f"where regexp_matches(tag, '{WARNING_SCOPE_SQL}')"
        else:
            continue
        for code, lm, tag in con.execute(f"select code, lm, tag from (select code, lm, unnest(list_distinct({alias})) as tag from {table}) {where}").fetchall():
            if in_flag_scope(sev, tag):
                rows.append([code, lm, sev, tag, family_key(tag)])
    products = len({r[0] for r in rows})
    return rows, products, con.execute(f"select count(*) from {table}").fetchone()[0]


# --- the product features of each snapshot (roadmap item 17, option 2 agreed 2026-10-26) ----------------------------------------------------
# The triage model must see each flagged product as it WAS at snapshot t (today's numbers would contain the fix). Measured 2026-10-26 on the
# 25 Oct snapshot (4,833,923 products, 4,721 row groups): the nutriments columns cost 256 MB compressed (name 60, 100g 168, unit 29), brand tags
# 33, category tags 44, serving size 11, on top of the 107 MB footer and 124 MB for code, last-modified time and the three flag lists that every
# read already pays. A filter on `code` does NOT skip row groups (a one-code lookup read the whole code column: 59 MB, 248 s), so the read is a
# full column scan and the features are taken for the flagged products only AFTER the scan.
# What the Parquet carries is OFF's AGGREGATED nutriments (name, 100g, unit), not the per-source input sets: rules checked on it agree poorly with
# OFF's flags for five of the 11 rules (context file A71), so the numbers are features and context, not rule verdicts.

CORE_NUTRIENTS = ("energy", "energy-kj", "energy-kcal", "fat", "saturated-fat", "carbohydrates", "sugars", "starch", "proteins", "salt", "sodium",
                  "fiber", "polyols", "erythritol", "isomalt", "maltitol", "sorbitol", "alcohol")
NUTRIMENTS_TYPE = ('STRUCT("name" VARCHAR, "value" FLOAT, "100g" FLOAT, serving FLOAT, unit VARCHAR, prepared_value FLOAT, prepared_100g FLOAT, '
                   'prepared_serving FLOAT, prepared_unit VARCHAR)[]')
REQUIRED_TYPES = {"code": "VARCHAR", "last_modified_t": "BIGINT", "nutriments": NUTRIMENTS_TYPE, "brands_tags": "VARCHAR[]",
                  "categories_tags": "VARCHAR[]", "serving_size": "VARCHAR", "data_quality_errors_tags": "VARCHAR[]",
                  "data_quality_warnings_tags": "VARCHAR[]", "data_quality_info_tags": "VARCHAR[]"}


# Version 2 of the feature table (2026-10-28): 15 more columns of the same snapshot, chosen from the history look of that day (see the buildlog): only columns that are
# filled at a stable share from 22 Mar 2026 on; no contributor column of any kind (names or lists of names), no retiring fields (`nutrition_data_per`, `no_nutrition_data`).
# Types read from the 22 Mar and 27 Oct snapshots (identical). `completeness` is FLOAT in the file and becomes a DOUBLE through text, like the nutrient values.
COLUMNS_VERSION = 2
EXTRA_COLUMNS = (("created_t", "BIGINT"), ("last_updated_t", "BIGINT"), ("data_sources_tags", "VARCHAR[]"), ("popularity_key", "BIGINT"), ("scans_n", "INTEGER"),
                 ("unique_scans_n", "INTEGER"), ("completeness", "FLOAT"), ("states_tags", "VARCHAR[]"), ("labels_tags", "VARCHAR[]"), ("countries_tags", "VARCHAR[]"),
                 ("last_image_t", "BIGINT"), ("max_imgid", "INTEGER"), ("nutriscore_grade", "VARCHAR"), ("nova_group", "INTEGER"), ("rev", "INTEGER"))
EXTRA_NAMES = tuple(n for n, _ in EXTRA_COLUMNS)
EXTRA_SPARK_TYPES = ("BIGINT", "BIGINT", "ARRAY<STRING>", "BIGINT", "INT", "INT", "DOUBLE", "ARRAY<STRING>", "ARRAY<STRING>", "ARRAY<STRING>", "BIGINT", "INT", "STRING", "INT", "INT")
EXTRA_ARRAYS = tuple(i for i, (_, t) in enumerate(EXTRA_COLUMNS) if t.endswith("[]"))      # a NULL list is stored as an empty one
BASE_FEATURE_FIELDS = 9                                                                     # code, lm, serving_size, brand, categories, names, values, n, max mass
EXTRA_MIN_FILLED = ("created_t", "rev")                                                     # filled on 100% of products on every date looked at; under 99% means a broken read


REQUIRED_TYPES.update(dict(EXTRA_COLUMNS))


def feature_extras(extra: list) -> list:
    """The 15 extra values of one product as they are stored: a NULL list becomes an empty list, everything else stays."""
    return [[] if (i in EXTRA_ARRAYS and v is None) else v for i, v in enumerate(extra)]


class SchemaError(RuntimeError):
    """A snapshot's Parquet schema is not the one this module was written for. Raised BEFORE any heavy read, so nothing is written."""


def check_schema(described: dict) -> None:
    """`described` maps column name to the type DuckDB reports. Raises SchemaError naming every missing or changed column."""
    problems = []
    for col, want in REQUIRED_TYPES.items():
        have = described.get(col)
        if have is None:
            problems.append(f"{col}: missing")
        elif have != want:
            problems.append(f"{col}: is {have}, expected {want}")
    if problems:
        raise SchemaError("snapshot schema changed: " + "; ".join(problems))


def flagged_table_sql(table: str) -> str:
    """A table `flagged(code)` of every product with an error flag or a warning flag that might be in scope (the SQL prefilter is looser than
    `in_flag_scope`, so the products with flag rows are a subset)."""
    return (f"create or replace table flagged as select distinct code from (select code, unnest(list_distinct(e)) as tag from {table} "
            f"where e is not null) union select distinct code from (select code, unnest(list_distinct(w)) as tag from {table} where w is not null) "
            f"where regexp_matches(tag, '{WARNING_SCOPE_SQL}')")


def feature_load_sql(table: str, source: str) -> str:
    """`table` from the snapshot at `source` (a URL or a local Parquet file): one row per flagged product, newest row per barcode."""
    return (f"create table {table} as select code, last_modified_t as lm, serving_size, brands_tags[1] as brand, categories_tags, nutriments, "
            f"{', '.join(EXTRA_NAMES)} from read_parquet('{source}') where code in (select code from flagged) "
            f"qualify row_number() over (partition by code order by last_modified_t desc) = 1")


def _extra_select(name: str) -> str:
    """FLOAT goes to DOUBLE through text, so 0.8 stays 0.8 (a plain cast gives 0.800000011920929)."""
    return f"cast(cast({name} as varchar) as double)" if dict(EXTRA_COLUMNS)[name] == "FLOAT" else name


def feature_rows(con, table: str) -> list[list]:
    """[code, lm, serving_size, brand, categories, nutrient names, per-100 values, number of nutrients with a value, largest mass value, then the 15 EXTRA_COLUMNS] per product.
    Values go FLOAT to text to DOUBLE so 68.8 stays 68.8 (a plain cast gives 68.80000305175781)."""
    core = "[" + ", ".join(f"'{k}'" for k in CORE_NUTRIENTS) + "]"
    sql = (f"select code, lm, serving_size, brand, categories_tags, list_transform(sel, x -> x.name), "
           f"list_transform(sel, x -> cast(cast(x.\"100g\" as varchar) as double)), "
           f"coalesce(len(list_filter(nutriments, x -> x.\"100g\" is not null)), 0), "
           f"list_max(list_transform(list_filter(nutriments, x -> x.\"100g\" is not null and not starts_with(x.name, 'energy') and x.unit = 'g'), "
           f"x -> cast(cast(x.\"100g\" as varchar) as double))), "
           f"{', '.join(_extra_select(n) for n in EXTRA_NAMES)} "
           f"from (select *, list_filter(nutriments, x -> x.\"100g\" is not null and list_contains({core}, x.name)) as sel from {table})")
    return [list(r[:BASE_FEATURE_FIELDS]) + feature_extras(list(r[BASE_FEATURE_FIELDS:])) for r in con.execute(sql).fetchall()]


def validate_snapshot(flag_rows: list[list], features: list[list], products_in_snapshot: int, min_products: int = 1_000_000) -> dict:
    """Checks made before anything is written. Raises ValueError naming the first thing that is wrong; returns counts for the manifest."""
    if not flag_rows:
        raise ValueError("no open flags were read")
    flag_lm = {}
    for code, lm, *_ in flag_rows:
        flag_lm[code] = lm
    feature_lm = {f[0]: f[1] for f in features}
    if len(feature_lm) != len(features):
        raise ValueError("a barcode appears twice in the product features")
    missing = [c for c in flag_lm if c not in feature_lm]
    if missing:
        raise ValueError(f"{len(missing)} flagged products have no feature row (first: {missing[0]})")
    differing = [c for c, lm in flag_lm.items() if feature_lm[c] != lm]
    if differing:
        raise ValueError(f"{len(differing)} products have a different last-modified time in the flag read and the feature read (first: {differing[0]})")
    with_nutrients = sum(1 for f in features if f[5])
    share = with_nutrients / len(features)
    if not 0.2 <= share <= 1.0:
        raise ValueError(f"only {share:.1%} of the flagged products carry any core nutrient; expected 20% or more")
    if products_in_snapshot < min_products:
        raise ValueError(f"the snapshot holds only {products_in_snapshot} products")
    if len(features[0]) > BASE_FEATURE_FIELDS:
        for name in EXTRA_MIN_FILLED:
            filled = sum(1 for f in features if f[BASE_FEATURE_FIELDS + EXTRA_NAMES.index(name)] is not None) / len(features)
            if filled < 0.99:
                raise ValueError(f"`{name}` is filled on only {filled:.1%} of the flagged products; it is 100% in every snapshot looked at")
    return {"feature_rows": len(features), "products_with_nutrients": with_nutrients}


def compute_pair(con, prev: str = "p", cur: str = "n") -> dict:
    """Compare two loaded snapshots. Returns
      stats     counts for the manifest;
      events    one dict per tag that disappeared from or appeared on a product present in both snapshots;
      left      products in `prev` and not in `cur` (deletion candidates).
    A NULL tag list (a product OFF lists with no flags at all) counts as an empty list: without that, `list_contains(NULL, x)` is NULL and every
    tag that appeared on such a product was silently dropped (found 2026-10-20 by an independent recount: 372 warning and 561 info events).
    For a disappeared tag `family_remains` is True when the product still carries ANOTHER tag of the same family in `cur` (a rename, not a fix);
    for an appeared tag it is True when the product already carried that family in `prev`. `edited` is whether last_modified_t changed."""
    def q(sql):
        return con.execute(sql).fetchall()

    # Memory: the 2026-10-20 production run was killed (out of memory) after 7 pairs. The first version copied BOTH snapshots' flag lists into a joined
    # temp table for every pair. Now the join is read twice but only counts come out of the first pass and only the products that changed (tens of
    # thousands, not 4.7 million) are kept in `_d`.
    joined = f"from {prev} p join {cur} c on p.code = c.code"
    in_both, edited = q(f"select count(*), count(*) filter (where p.lm <> c.lm) {joined}")[0]
    con.execute("create or replace temp table _d as select p.code, p.lm as lm_from, c.lm as lm_to, "
                + ", ".join(f"coalesce(p.{a}, []::varchar[]) as {a}_p, coalesce(c.{a}, []::varchar[]) as {a}_c" for a, _, _ in SEVERITIES)
                + f" {joined} where p.lm <> c.lm or "
                + " or ".join(f"coalesce(p.{a}, []::varchar[]) <> coalesce(c.{a}, []::varchar[])" for a, _, _ in SEVERITIES))
    stats = {
        "rows_from": q(f"select count(*) from {prev}")[0][0],
        "rows_to": q(f"select count(*) from {cur}")[0][0],
        "in_both": in_both,
        "edited_count": edited,
    }
    left = [(code, lm) for code, lm in q(f"select code, lm from {prev} where code not in (select code from {cur}) order by code")]
    stats["left_count"] = len(left)
    stats["entered_count"] = q(f"select count(*) from {cur} where code not in (select code from {prev})")[0][0]

    events = []
    for alias, sev, _ in SEVERITIES:
        for event, a, b in (("disappeared", f"{alias}_p", f"{alias}_c"), ("appeared", f"{alias}_c", f"{alias}_p")):
            rows = q(f"select code, lm_from, lm_to, tag, {b} as other from (select code, lm_from, lm_to, {b}, "
                     f"unnest(list_distinct(list_filter({a}, x -> not list_contains({b}, x)))) as tag from _d)")
            # the tags the product carries on the OTHER side, as family sets, to tell a rename from a real change
            for code, lm_from, lm_to, tag, other in rows:
                fam = family_key(tag)
                remains = any(family_key(t) == fam for t in (other or []))
                events.append({"code": code, "severity": sev, "flag": tag, "family": fam, "event": event, "family_remains": remains,
                               "edited": lm_from != lm_to, "lm_from": lm_from, "lm_to": lm_to})
    stats["flag_events"] = len(events)
    con.execute("drop table if exists _d")
    return {"stats": stats, "events": events, "left": left}


# --- watching a long run ------------------------------------------------------------------------------------------------------------------
# Added after the 2026-10-20 production run: it was killed (out of memory) after 117 minutes with 7 of 12 pairs written, the time per pair rising
# from 554 s to 1,355 s, and nothing in the run said so until it died. Every pair now logs its memory and seconds and the run stops by itself, with
# its progress saved, as soon as either runs away.

def process_rss_mb(path: str = "/proc/self/status") -> float:
    """Resident memory of this process in MB (Linux)."""
    with open(path) as fh:
        for line in fh:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    raise RuntimeError("VmRSS not found in " + path)


def mem_total_mb(path: str = "/proc/meminfo") -> float:
    """Total memory of the machine in MB, or of the cgroup limit when that is lower (a container sees the host's memory in /proc/meminfo)."""
    with open(path) as fh:
        for line in fh:
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) / 1024
    raise RuntimeError("MemTotal not found in " + path)


def should_stop(seconds_history: list[float], rss_mb: float, total_mb: float, rss_fraction: float = 0.6, slowdown: float = 2.0, min_history: int = 3):
    """(stop, reason) after a finished pair. Stop when the process holds more than `rss_fraction` of the machine's memory, or when the last pair
    took more than `slowdown` times the median of the earlier ones (needs `min_history` earlier pairs)."""
    if total_mb and rss_mb > rss_fraction * total_mb:
        return True, f"memory {rss_mb:.0f} MB is over {rss_fraction:.0%} of {total_mb:.0f} MB"
    if len(seconds_history) > min_history:
        earlier = sorted(seconds_history[:-1])
        median = earlier[len(earlier) // 2]
        if seconds_history[-1] > slowdown * median:
            return True, f"the last pair took {seconds_history[-1]:.0f} s, over {slowdown:g} x the median {median:.0f} s of the earlier ones"
    return False, ""


# --- one pair in its own process ----------------------------------------------------------------------------------------------------------
# The notebook runs every pair in a separate Python process (`python snapshot_lib.py worker <spec.json>`): when the process ends, all its memory
# goes back to the machine, so one pair can never inherit what the one before it left behind, and a pair that is killed for memory takes down only
# itself (the notebook sees the exit code, keeps the pairs already written and reports). A snapshot read from the network is also written to a local
# Parquet file (`cache`), so the next pair, whose older snapshot is this one, reads it from disk instead of downloading it again.

def _load_side(con, table: str, side: dict, byte_guard: int) -> int:
    """Create `table` from one side of a pair: a local Parquet file when `local` is set, otherwise the snapshot over the network (then copied to
    `cache` when given). Returns the bytes received from the network."""
    local = side.get("local")
    if local:
        con.execute(f"create table {table} as select * from read_parquet('{local}')")
        return 0
    received = guarded_execute(con, load_sql(table, resolve_cdn(side["sha"])), byte_guard, side["sha"])
    if side.get("cache"):
        con.execute(f"copy {table} to '{side['cache']}' (format parquet, compression zstd)")
    return received


def guarded_execute(con, sql: str, byte_guard: int, sha: str) -> int:
    """Run one statement that reads a snapshot over the network under the byte guard; returns the bytes the machine received meanwhile."""
    guard = None
    try:
        with ByteGuard(read_rx_bytes, byte_guard, con.interrupt) as guard:
            con.execute(sql)
    except Exception:
        # the guard's interrupt makes DuckDB raise before the check below: name the cause and the bytes seen (found 2026-10-26, a bare 'Interrupted!')
        if guard is not None and guard.tripped:
            raise RuntimeError(f"byte guard: reading snapshot {sha[:8]} passed {byte_guard / 1e6:.0f} MB "
                               f"({guard.received() / 1e6:.0f} MB received by the machine); stopped") from None
        raise
    if guard.tripped:
        raise RuntimeError(f"byte guard: reading snapshot {sha[:8]} passed {byte_guard / 1e6:.0f} MB; stopped")
    return guard.received()


def peak_rss_mb() -> float | None:
    """Highest resident memory this process has reached, in MB (None where the platform has no `resource` module)."""
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024      # Linux reports kilobytes
    except ImportError:
        return None


def run_worker(spec: dict) -> dict:
    """Compare one pair. spec: prev and cur ({sha, local?, cache?}), out (path of the result JSON), memory_limit_mb, temp_dir, threads,
    byte_guard, count_prev / count_cur (whether to compute the open-flag counts of that side). Returns and writes the result."""
    import time

    import duckdb
    t0 = time.time()
    con = duckdb.connect()
    if not (spec["prev"].get("local") and spec["cur"].get("local")):
        con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(f"SET threads={int(spec.get('threads', 8))}")
    con.execute("SET allow_asterisks_in_http_paths = true")           # the signed CDN address has a '*' in its query string
    if spec.get("memory_limit_mb"):
        con.execute(f"SET memory_limit='{int(spec['memory_limit_mb'])}MB'")
    if spec.get("temp_dir"):
        con.execute(f"SET temp_directory='{spec['temp_dir']}'")
    guard = int(spec.get("byte_guard", BYTE_GUARD))
    rx = _load_side(con, "p", spec["prev"], guard) + _load_side(con, "n", spec["cur"], guard)
    res = compute_pair(con, "p", "n")
    res["open_counts"] = {"prev": open_counts(con, "p") if spec.get("count_prev") else None,
                          "cur": open_counts(con, "n") if spec.get("count_cur") else None}
    res["rx_bytes"] = rx
    res["seconds"] = round(time.time() - t0, 1)
    res["peak_rss_mb"] = peak_rss_mb()
    with open(spec["out"], "w", encoding="utf-8") as fh:
        json.dump(res, fh)
    return res


def run_flags_worker(spec: dict) -> dict:
    """Read ONE snapshot: check its schema, then write its open flags in scope and the features of the flagged products, validated before anything
    leaves this process. spec: sha, out (path of the result JSON), local_features? (an OFF-style Parquet file instead of the network, for tests), memory_limit_mb, temp_dir, threads, byte_guard (the flag read), feature_guard (the feature read),
    check_only (stop after the schema check)."""
    import time

    import duckdb
    t0 = time.time()
    con = duckdb.connect()
    if not spec.get("local_features"):
        con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(f"SET threads={int(spec.get('threads', 8))}")
    con.execute("SET allow_asterisks_in_http_paths = true")
    if spec.get("memory_limit_mb"):
        con.execute(f"SET memory_limit='{int(spec['memory_limit_mb'])}MB'")
    if spec.get("temp_dir"):
        con.execute(f"SET temp_directory='{spec['temp_dir']}'")
    flag_guard = int(spec.get("byte_guard", BYTE_GUARD))
    feature_guard = int(spec.get("feature_guard", FEATURE_GUARD))
    source = spec.get("local_features") or resolve_cdn(spec["sha"])

    def read(sql, limit):
        """A statement that reads the snapshot: under the byte guard on the network, plain for a local test file (bytes: 0)."""
        if spec.get("local_features"):
            con.execute(sql)
            return 0
        return guarded_execute(con, sql, limit, spec["sha"])

    rx = read(f"create view v as select * from read_parquet('{source}')", flag_guard)
    check_schema({r[0]: r[1] for r in con.execute("describe v").fetchall()})
    res = {"schema_ok": True, "rx_bytes": rx, "peak_rss_mb": None}
    if not spec.get("check_only"):
        rx += read(load_sql("s", source), flag_guard)
        rows, products, in_snapshot = open_flag_rows(con, "s")
        con.execute(flagged_table_sql("s"))
        rx += read(feature_load_sql("f", source), feature_guard)
        features = feature_rows(con, "f")
        counts = validate_snapshot(rows, features, in_snapshot, int(spec.get("min_products", 1_000_000)))
        res.update({"rows": rows, "features": features, "products_with_flags": products, "products_in_snapshot": in_snapshot, **counts})
    res.update({"rx_bytes": rx, "seconds": round(time.time() - t0, 1), "peak_rss_mb": peak_rss_mb()})
    with open(spec["out"], "w", encoding="utf-8") as fh:
        json.dump(res, fh)
    return res


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "worker":
        with open(sys.argv[2], encoding="utf-8") as fh:
            run_worker(json.load(fh))
    elif len(sys.argv) == 3 and sys.argv[1] == "flags-worker":
        with open(sys.argv[2], encoding="utf-8") as fh:
            run_flags_worker(json.load(fh))
    else:
        raise SystemExit("usage: python snapshot_lib.py (worker|flags-worker) <spec.json>")
